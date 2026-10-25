"""Deterministic billing investigations. Alerts describe delayed evidence, never invented causes."""

from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from statistics import median
from uuid import uuid4
from app.enterprise_store import decode
from app.focus import digest
from app.principals import actor
from app.outcome_store import scope_allowed, OutcomeConflict
from app.telemetry_contract import moment

RULE = "daily-same-weekday-median-v1"


class Investigations:
    def __init__(self, store, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def ownership(self, tenant):
        with self.store.transaction(tenant["tenant_id"]) as db:
            rows = db.execute(
                "SELECT provider,scope_id,resource_id,version,payload,actor,created_at FROM finops_ownership WHERE tenant_id=%s ORDER BY version DESC,created_at DESC LIMIT 10001",
                (tenant["tenant_id"],),
            ).fetchall()
        if len(rows) > 10000:
            raise ValueError("Ownership history exceeds the pilot limit")
        latest = {}
        for row in rows:
            key = row[0], row[1], row[2]
            if key not in latest and scope_allowed(tenant, *key[:2]):
                latest[key] = dict(
                    provider=row[0],
                    scope_id=row[1],
                    resource_id=row[2],
                    version=row[3],
                    **decode(row[4]),
                    actor=row[5],
                    effective_at=str(row[6]),
                )
        return list(latest.values())

    def save_ownership(self, tenant, resource, body):
        provider = resource.get("cloud_provider", "azure")
        scope = resource.get("scope_id") or resource.get("subscription_id")
        rid = (
            resource["resource_id"].lower()
            if provider == "azure"
            else resource["resource_id"]
        )
        tid = tenant["tenant_id"]
        if not scope_allowed(tenant, provider, scope):
            raise ValueError("Ownership must reference an authorized resource")
        with self.store.transaction(tid, write=True) as db:
            prior = (
                db.execute(
                    "SELECT max(version) FROM finops_ownership WHERE tenant_id=%s AND provider=%s AND scope_id=%s AND resource_id=%s",
                    (tid, provider, scope, rid),
                ).fetchone()[0]
                or 0
            )
            if prior != body.version:
                raise OutcomeConflict(
                    "Ownership mapping changed. Refresh before saving."
                )
            payload = body.model_dump(
                mode="json", exclude={"scan_id", "version", "resource_id"}
            )
            payload.update(
                allocation_method="direct",
                basis="explicit_resource_mapping",
                resource_name=resource.get("resource_name", rid),
                resource_type=resource["resource_type"],
            )
            db.execute(
                "INSERT INTO finops_ownership(id,tenant_id,provider,scope_id,resource_id,version,payload,actor,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    str(uuid4()),
                    tid,
                    provider,
                    scope,
                    rid,
                    prior + 1,
                    db.json(payload),
                    actor(tenant),
                    self.clock().isoformat(),
                ),
            )
        return dict(payload, provider=provider, scope_id=scope, version=prior + 1)

    def history(self, tenant, provider, scope, rid):
        if not scope_allowed(tenant, provider, scope):
            return []
        with self.store.transaction(tenant["tenant_id"]) as db:
            rows = db.execute(
                "SELECT version,payload,actor,created_at FROM finops_ownership WHERE tenant_id=%s AND provider=%s AND scope_id=%s AND resource_id=%s ORDER BY version DESC LIMIT 100",
                (tenant["tenant_id"], provider, scope, rid),
            ).fetchall()
        return [
            dict(version=r[0], mapping=decode(r[1]), actor=r[2], effective_at=str(r[3]))
            for r in rows
        ]

    def _row(self, row):
        if row is None:
            return None
        return dict(
            id=str(row[0]),
            provider=row[1],
            scope_id=row[2],
            resource_id=row[3],
            currency=row[4],
            state=row[5],
            version=row[6],
            payload=decode(row[7]),
            created_at=str(row[8]),
            updated_at=str(row[9]),
        )

    def _get(self, db, tid, id):
        return self._row(
            db.execute(
                "SELECT id,provider,scope_id,resource_id,currency,state,version,payload,created_at,updated_at FROM finops_anomalies WHERE tenant_id=%s AND id=%s",
                (tid, id),
            ).fetchone()
        )

    def anomalies(self, tenant):
        with self.store.transaction(tenant["tenant_id"]) as db:
            rows = db.execute(
                "SELECT id,provider,scope_id,resource_id,currency,state,version,payload,created_at,updated_at FROM finops_anomalies WHERE tenant_id=%s ORDER BY created_at DESC,id DESC LIMIT 500",
                (tenant["tenant_id"],),
            ).fetchall()
        return [
            a
            for r in rows
            if scope_allowed(tenant, (a := self._row(r))["provider"], a["scope_id"])
        ]

    def detail(self, tenant, id):
        with self.store.transaction(tenant["tenant_id"]) as db:
            item = self._get(db, tenant["tenant_id"], id)
            if item is None or not scope_allowed(
                tenant, item["provider"], item["scope_id"]
            ):
                return None
            events = db.execute(
                "SELECT action,version,payload,actor,created_at FROM finops_anomaly_events WHERE tenant_id=%s AND anomaly_id=%s ORDER BY version LIMIT 200",
                (tenant["tenant_id"], id),
            ).fetchall()
            item["events"] = [
                dict(
                    action=r[0],
                    version=r[1],
                    payload=decode(r[2]),
                    actor=r[3],
                    created_at=str(r[4]),
                )
                for r in events
            ]
            return item

    def _event(self, db, tenant, item, action, payload):
        db.execute(
            "INSERT INTO finops_anomaly_events(id,tenant_id,anomaly_id,version,action,payload,actor,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                str(uuid4()),
                tenant["tenant_id"],
                item["id"],
                item["version"],
                action,
                db.json(payload),
                actor(tenant),
                self.clock().isoformat(),
            ),
        )

    def suppress(self, tenant, body):
        if not scope_allowed(tenant, body.provider, body.scope_id):
            raise ValueError("Suppression is outside the authorized scope")
        if (
            not 0 < (body.end - body.start).days <= 30
            or body.start < self.clock().date()
        ):
            raise ValueError(
                "Choose a current/future suppression lasting at most 30 days"
            )
        rid = (
            body.resource_id.lower()
            if body.resource_id and body.provider == "azure"
            else body.resource_id
        )
        with self.store.transaction(tenant["tenant_id"], write=True) as db:
            id = str(uuid4())
            db.execute(
                "INSERT INTO finops_suppressions(id,tenant_id,provider,scope_id,resource_id,start_date,end_date,payload,actor,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    id,
                    tenant["tenant_id"],
                    body.provider,
                    body.scope_id,
                    rid,
                    str(body.start),
                    str(body.end),
                    db.json(body.model_dump(mode="json")),
                    actor(tenant),
                    self.clock().isoformat(),
                ),
            )
        return dict(
            id=id,
            expires_on=str(body.end),
            scope="exact_resource_or_account_aggregate",
            automatic_execution=False,
        )

    def detect(self, tenant, body):
        tid = tenant["tenant_id"]
        now = self.clock()
        with self.store.transaction(tid) as db:
            latest = db.execute(
                "SELECT max(period_end) FROM focus_charges WHERE tenant_id=%s AND currency=%s AND period_end<=%s",
                (
                    tid,
                    body.currency,
                    datetime.combine(now.date(), time.min, timezone.utc).isoformat(),
                ),
            ).fetchone()[0]
        day = body.day or (
            moment(latest).date() - timedelta(days=1) if latest else None
        )
        if day is None:
            return dict(
                items=[],
                status="missing_billing_evidence",
                warning="Import billing evidence before detection.",
            )
        if not now.date() - timedelta(days=90) <= day < now.date():
            raise ValueError("Choose one of the last 90 closed UTC days")
        start = datetime.combine(day - timedelta(days=28), time.min, timezone.utc)
        end = datetime.combine(day + timedelta(days=1), time.min, timezone.utc)
        with self.store.transaction(tid) as db:
            rows = db.execute(
                "SELECT id,fingerprint,provider,sub_account,resource_id,period_start,period_end,billed_cost,charge_category FROM focus_charges WHERE tenant_id=%s AND currency=%s AND period_start>=%s AND period_end<=%s ORDER BY id LIMIT 50001",
                (tid, body.currency, start.isoformat(), end.isoformat()),
            ).fetchall()
        if len(rows) > 50000:
            raise ValueError(
                "The pilot detector supports at most 50000 daily charge rows per window"
            )
        groups = {}
        skipped = 0
        for row in rows:
            a, b = moment(row[5]), moment(row[6])
            if not a or not b or b - a != timedelta(days=1) or a.time() != time.min:
                skipped += 1
                continue
            if not scope_allowed(tenant, row[2], row[3]):
                continue
            key = row[2], row[3], row[4]
            group = groups.setdefault(
                key,
                dict(
                    days=defaultdict(lambda: Decimal(0)),
                    categories=defaultdict(lambda: defaultdict(lambda: Decimal(0))),
                    hashes=[],
                ),
            )
            group["days"][a.date()] += Decimal(str(row[7]))
            group["categories"][a.date()][row[8]] += Decimal(str(row[7]))
            group["hashes"].append([str(row[0]), row[1]])
        with self.store.transaction(tid) as db:
            prior_rows = db.execute(
                "SELECT fingerprint,payload FROM finops_anomalies WHERE tenant_id=%s AND currency=%s ORDER BY created_at DESC LIMIT 501",
                (tid, body.currency),
            ).fetchall()
        prior_signals = {
            row[0] for row in prior_rows if decode(row[1]).get("day") == str(day)
        }
        owners = {
            (r["provider"], r["scope_id"], r["resource_id"]): r
            for r in self.ownership(tenant)
        }
        candidates = []
        insufficient = 0
        for key, g in groups.items():
            days = g["days"]
            baseline = [
                days[day - timedelta(days=7 * i)]
                for i in range(1, 5)
                if day - timedelta(days=7 * i) in days
            ]
            if day not in days or len(baseline) < 3:
                insufficient += 1
                continue
            center = median(baseline)
            mad = median([abs(v - center) for v in baseline])
            actual = days[day]
            delta = actual - center
            active = delta > max(Decimal("5"), abs(center) * Decimal(".2"), mad * 3)
            if (
                not active
                and digest([RULE, *key, body.currency, str(day)]) not in prior_signals
            ):
                continue
            ownership = owners.get(key)
            category_deltas = {}
            for category in ("Usage", "Credit", "Adjustment", "Tax", "Purchase"):
                previous = [
                    g["categories"][day - timedelta(days=7 * i)].get(
                        category, Decimal(0)
                    )
                    for i in range(1, 5)
                    if day - timedelta(days=7 * i) in days
                ]
                category_deltas[category] = format(
                    g["categories"][day].get(category, Decimal(0)) - median(previous),
                    "f",
                )
            payload = dict(
                signal_active=active,
                rule_version=RULE,
                day=str(day),
                baseline_same_weekday_observations=len(baseline),
                baseline_daily_cost=format(center, "f"),
                observed_daily_cost=format(actual, "f"),
                increase=format(delta, "f"),
                category_changes=category_deltas,
                evidence_digest=digest(g["hashes"]),
                billing_lag_days=(now.date() - day).days,
                source_freshness="stale"
                if (now.date() - day).days > 7
                else "delayed_billing",
                usage_vs_price="unavailable_without_usage_quantity_and_rate_evidence",
                provider_reconciled=False,
                causation="not_established",
                ownership=ownership,
                owner=(ownership or {}).get("owner"),
                ownership_basis="current_mapping_for_routing_not_historical_reallocation",
            )
            candidates.append((key, payload))
        if len(candidates) > 200:
            raise ValueError(
                "More than 200 candidates require a narrower supported dataset before publishing investigations"
            )
        ids = []
        with self.store.transaction(tid, write=True) as db:
            for (provider, scope, rid), payload in candidates:
                fingerprint = digest(
                    [RULE, provider, scope, rid, body.currency, str(day)]
                )
                prior = db.execute(
                    "SELECT id FROM finops_anomalies WHERE tenant_id=%s AND fingerprint=%s",
                    (tid, fingerprint),
                ).fetchone()
                suppression = db.execute(
                    "SELECT id FROM finops_suppressions WHERE tenant_id=%s AND provider=%s AND scope_id=%s AND (resource_id=%s OR (resource_id IS NULL AND %s IS NULL)) AND start_date<=%s AND end_date>%s ORDER BY created_at DESC LIMIT 1",
                    (tid, provider, scope, rid, rid, str(day), str(day)),
                ).fetchone()
                # Only an approval already saved before this detection can suppress
                # the matching exact resource/window; nothing is sent externally.
                if suppression:
                    payload["suppression_id"] = str(suppression[0])
                if prior:
                    item = self._get(db, tid, str(prior[0]))
                    ids.append(item["id"])
                    if item["payload"]["evidence_digest"] == payload["evidence_digest"]:
                        continue
                    p = {
                        **payload,
                        **{
                            k: item["payload"][k]
                            for k in (
                                "owner",
                                "acknowledged_at",
                                "resolution",
                                "resolved_at",
                            )
                            if k in item["payload"]
                        },
                    }
                    if item["state"] == "resolved":
                        p.pop("resolution", None)
                        p.pop("resolved_at", None)
                    state = (
                        "suppressed"
                        if suppression
                        else "open"
                        if item["state"] in ("resolved", "suppressed")
                        else item["state"]
                    )
                    if not payload["signal_active"] and not suppression:
                        state = "review_required"
                        p.pop("resolution", None)
                        p.pop("resolved_at", None)
                    db.execute(
                        "UPDATE finops_anomalies SET state=%s,version=version+1,payload=%s,updated_at=%s WHERE tenant_id=%s AND id=%s",
                        (state, db.json(p), self.clock().isoformat(), tid, item["id"]),
                    )
                    item = self._get(db, tid, item["id"])
                    self._event(
                        db,
                        tenant,
                        item,
                        "billing_evidence_updated",
                        dict(evidence_digest=payload["evidence_digest"]),
                    )
                else:
                    id = str(uuid4())
                    ids.append(id)
                    state = "suppressed" if suppression else "open"
                    resource_column = (
                        "LOWER(resource_id)" if provider == "azure" else "resource_id"
                    )
                    correlations = db.execute(
                        f"SELECT id,state FROM agent_tasks WHERE tenant_id=%s AND provider=%s AND scope_id=%s AND {resource_column}=%s AND created_at>=%s AND created_at<%s ORDER BY created_at LIMIT 10",
                        (
                            tid,
                            provider,
                            scope,
                            rid,
                            datetime.combine(
                                day - timedelta(days=1), time.min, timezone.utc
                            ).isoformat(),
                            end.isoformat(),
                        ),
                    ).fetchall()
                    payload["possible_change_correlations"] = [
                        dict(
                            agent_task_id=str(r[0]),
                            state=r[1],
                            basis="task_created_near_billing_window_not_proof_of_deployment_or_cause",
                        )
                        for r in correlations
                    ]
                    db.execute(
                        "INSERT INTO finops_anomalies(id,tenant_id,fingerprint,provider,scope_id,resource_id,currency,state,version,payload,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s)",
                        (
                            id,
                            tid,
                            fingerprint,
                            provider,
                            scope,
                            rid,
                            body.currency,
                            state,
                            db.json(payload),
                            now.isoformat(),
                            now.isoformat(),
                        ),
                    )
                    item = self._get(db, tid, id)
                    self._event(
                        db,
                        tenant,
                        item,
                        "detected",
                        dict(
                            evidence_digest=payload["evidence_digest"],
                            suppression_id=payload.get("suppression_id"),
                        ),
                    )
        return dict(
            items=[self.detail(tenant, id) for id in ids],
            status="evaluated",
            day=str(day),
            insufficient_baseline_groups=insufficient,
            excluded_nondaily_records=skipped,
            warning="Same-weekday cost-change signals on delayed imported billing. No missing day is filled with zero; category changes are not a usage/price root-cause diagnosis. Ownership routes investigations inside CloudSaver only.",
        )

    def act(self, tenant, id, body):
        with self.store.transaction(tenant["tenant_id"], write=True) as db:
            item = self._get(db, tenant["tenant_id"], id)
            if item is None or not scope_allowed(
                tenant, item["provider"], item["scope_id"]
            ):
                return None
            if item["version"] != body.version:
                raise OutcomeConflict("Investigation changed. Refresh before updating.")
            p = dict(item["payload"])
            state = item["state"]
            now = self.clock().isoformat()
            if state in ("resolved", "suppressed"):
                raise OutcomeConflict(
                    "Resolved or approved-suppressed investigations are retained read-only until source evidence changes"
                )
            if body.action == "acknowledge":
                p.setdefault("acknowledged_at", now)
                if state == "open":
                    state = "acknowledged"
            elif body.action == "assign":
                if not body.owner:
                    raise ValueError("An accountable owner is required")
                p["owner"] = body.owner
            elif body.action == "investigate":
                p.setdefault("acknowledged_at", now)
                state = "investigating"
            elif body.action == "resolve":
                if (
                    not body.resolution
                    or not p.get("owner")
                    or not p.get("acknowledged_at")
                ):
                    raise OutcomeConflict(
                        "Assign, acknowledge and provide a resolution classification before resolving"
                    )
                p.update(resolution=body.resolution, resolved_at=now)
                state = "resolved"
            db.execute(
                "UPDATE finops_anomalies SET state=%s,version=version+1,payload=%s,updated_at=%s WHERE tenant_id=%s AND id=%s AND version=%s",
                (state, db.json(p), now, tenant["tenant_id"], id, body.version),
            )
            updated = self._get(db, tenant["tenant_id"], id)
            self._event(
                db,
                tenant,
                updated,
                body.action,
                dict(
                    note=body.note, owner=p.get("owner"), resolution=p.get("resolution")
                ),
            )
            return updated

    def metrics(self, tenant):
        rows = self.anomalies(tenant)
        resolved = [r for r in rows if r["state"] == "resolved"]
        ack = []
        resolution = []
        for r in rows:
            created = moment(r["created_at"])
            p = r["payload"]
            if p.get("acknowledged_at"):
                ack.append(
                    max(0, (moment(p["acknowledged_at"]) - created).total_seconds())
                )
            if p.get("resolved_at"):
                resolution.append(
                    max(0, (moment(p["resolved_at"]) - created).total_seconds())
                )
        return dict(
            investigations=len(rows),
            unassigned=sum(
                not r["payload"].get("owner")
                for r in rows
                if r["state"] not in ("suppressed", "resolved")
            ),
            actionable_resolved_pct=round(
                sum(r["payload"].get("resolution") == "actionable" for r in resolved)
                * 100
                / len(resolved),
                2,
            )
            if resolved
            else None,
            mean_acknowledgment_seconds=sum(ack) / len(ack) if ack else None,
            mean_resolution_seconds=sum(resolution) / len(resolution)
            if resolution
            else None,
            sample_limit=500,
            warning="Metrics describe the saved in-app investigation sample, not external notification delivery or real-time cloud spend.",
        )
