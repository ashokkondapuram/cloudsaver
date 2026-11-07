"""Build scan-level commitment_evidence from saved FOCUS usage and open waste (read-only)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.commitment_arbitrage import decimal_text, parse_strict_monetary_decimal
from app.focus import authorized, utc
from app.telemetry_contract import moment


def _aligned_window(scan: dict) -> tuple[datetime, datetime] | None:
    stamp = moment(scan.get("timestamp"))
    if not stamp:
        return None
    end = stamp.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=30)
    if start.minute or start.second or start.microsecond:
        return None
    return start, end


def _hourly_series(start: datetime, end: datetime, buckets: dict[datetime, Decimal]) -> dict | None:
    points = []
    cursor = start
    while cursor < end:
        hour = cursor + timedelta(hours=1)
        if hour > end:
            break
        value = buckets.get(hour)
        if value is None:
            return None
        points.append({"at": hour.isoformat(), "value": decimal_text(value)})
        cursor = hour
    if len(points) != 720:
        return None
    return {
        "unit": "USD/hour",
        "currency": "USD",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "points": points,
        "basis": "focus_usage_charges_hourly",
    }


def _distribute_charge(start: datetime, end: datetime, amount: Decimal, buckets: dict[datetime, Decimal]) -> bool:
    if amount < 0 or not start or not end or end <= start:
        return False
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return False
    rate = amount / Decimal(seconds)
    pos = start
    while pos < end:
        hour_start = pos.replace(minute=0, second=0, microsecond=0)
        hour_end = hour_start + timedelta(hours=1)
        slice_start = max(pos, hour_start)
        slice_end = min(end, hour_end)
        if slice_end > slice_start:
            bucket = hour_start + timedelta(hours=1)
            buckets[bucket] = buckets.get(bucket, Decimal(0)) + rate * Decimal((slice_end - slice_start).total_seconds())
        pos = hour_end
    return True


def _account_usage_series(store, tenant: dict, scan: dict) -> dict | None:
    window = _aligned_window(scan)
    if not window:
        return None
    start, end = window
    scopes = [("azure", v) for v in tenant.get("subscription_ids", []) if authorized("azure", v, tenant)]
    scopes += [("aws", a["account_id"]) for a in tenant.get("aws_accounts", []) if authorized("aws", a["account_id"], tenant)]
    scopes += [("gcp", p["project_id"]) for p in tenant.get("gcp_projects", []) if authorized("gcp", p["project_id"], tenant)]
    if not scopes:
        return None
    fence = " OR ".join("(provider=%s AND sub_account=%s)" for _ in scopes)
    args = [tenant["tenant_id"], *[v for pair in scopes for v in pair], start.isoformat(), end.isoformat()]
    buckets: dict[datetime, Decimal] = defaultdict(lambda: Decimal(0))
    with store.transaction(tenant["tenant_id"]) as db:
        rows = db.execute(
            f"SELECT period_start, period_end, billed_cost, charge_category, currency FROM focus_charges "
            f"WHERE tenant_id=%s AND currency='USD' AND charge_category='Usage' AND ({fence}) "
            f"AND period_start>=%s AND period_end<=%s ORDER BY period_start LIMIT 50001",
            args,
        ).fetchall()
    if not rows or len(rows) > 50000:
        return None
    for period_start, period_end, billed, category, currency in rows:
        if currency != "USD":
            return None
        start_at = utc(str(period_start))
        end_at = utc(str(period_end))
        try:
            amount = parse_strict_monetary_decimal(str(billed))
        except ValueError:
            return None
        if not _distribute_charge(start_at, end_at, amount, buckets):
            return None
    return _hourly_series(start, end, buckets)


def _cleanup_series(scan: dict, usage: dict, start: datetime, end: datetime) -> dict | None:
    total = Decimal(0)
    for finding in scan.get("findings") or []:
        if finding.get("outcome") not in (None, "condition_detected"):
            continue
        monthly = finding.get("estimated_savings_usd") or finding.get("monthly_savings_usd")
        if monthly is None:
            continue
        try:
            total += parse_strict_monetary_decimal(str(monthly)) / Decimal(730)
        except ValueError:
            return None
    if total <= 0:
        return None
    rate = decimal_text(total)
    points = [{"at": (start + timedelta(hours=i + 1)).isoformat(), "value": rate} for i in range(720)]
    return {
        "unit": "USD/hour",
        "currency": "USD",
        "window_start": usage["window_start"],
        "window_end": usage["window_end"],
        "points": points,
        "basis": "open_waste_run_rate_constant",
    }


def _existing_commitments_hr(store, tenant_id: str, tenant: dict) -> tuple[str, bool]:
    from app.commitment_store import latest

    snapshots = latest(store, tenant_id)
    hourly = Decimal(0)
    scopes = {("azure", v) for v in tenant.get("subscription_ids", [])}
    scopes |= {("aws", a["account_id"]) for a in tenant.get("aws_accounts", [])}
    scopes |= {("gcp", p["project_id"]) for p in tenant.get("gcp_projects", [])}
    verified = False
    for snap in snapshots:
        if (snap.get("provider"), snap.get("scope_id")) not in scopes or snap.get("status") != "ok":
            continue
        verified = True
        for item in snap.get("items") or []:
            amount = item.get("commitment_amount")
            if amount is None:
                continue
            try:
                hourly += parse_strict_monetary_decimal(str(amount)) / Decimal(730)
            except ValueError:
                return "0", False
    return decimal_text(hourly), verified


def attach_commitment_evidence(tenant: dict, scan: dict, store) -> dict:
    if scan.get("provider_filtered") or scan.get("scope_filtered"):
        return scan
    if scan.get("status") != "completed":
        return scan
    window = _aligned_window(scan)
    if not window:
        return scan
    usage = _account_usage_series(store, tenant, scan)
    if usage is None:
        return scan
    cleanup = _cleanup_series(scan, usage, window[0], window[1])
    if cleanup is None:
        return scan
    try:
        from app.nextgen_engines import hourly_profile

        hourly_profile(usage)
        hourly_profile(cleanup)
    except ValueError:
        return scan
    existing, coverage_ok = _existing_commitments_hr(store, tenant["tenant_id"], tenant)
    scan["commitment_evidence"] = {
        "source_verified": True,
        "commitment_coverage_verified": coverage_ok,
        "usage_series": usage,
        "cleanup_series": cleanup,
        "existing_commitments_hr": existing,
        "purchase_authorized": False,
    }
    return scan
