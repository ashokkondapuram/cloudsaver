"""Durable attempt fences and usage metadata. No provider call holds a DB transaction."""
from datetime import datetime, timedelta, timezone
import json
import re
from uuid import UUID, uuid4

from app.enterprise_store import decode

COLUMNS='id,request_key,scan_id,metadata,status,input_tokens,output_tokens,created_at,completed_at'


def instant(value):
    return value.astimezone(timezone.utc) if isinstance(value,datetime) else datetime.fromisoformat(value).astimezone(timezone.utc)


def attribution(finding):
    """Observed structured tag identifiers stay in the ledger, never in model input."""
    from app.assessment import tags_of
    tags=tags_of(finding)
    result={}
    for output,keys in (('cost_center',{'costcenter'}),('application_id',{'applicationid'})):
        values={value for key,value in tags.items() if re.sub(r'[^a-z]','',key.casefold()) in keys}
        value=next(iter(values)) if len(values)==1 else ''
        result[output]=value if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}',value) else 'unassigned'
    return result


class InferenceLedger:
    durable = True

    def __init__(self, store):
        self.store=store

    @staticmethod
    def now(db):
        return instant(db.execute('SELECT clock_timestamp()').fetchone()[0]) if db.postgres else datetime.now(timezone.utc)

    def event(self,db,tenant_id,attempt_id,action,now):
        db.execute('INSERT INTO ai_inference_events(id,tenant_id,attempt_id,action,created_at) VALUES (%s,%s,%s,%s,%s)',
                   (str(uuid4()),tenant_id,attempt_id,action,now.isoformat()))

    def run(self,tenant_id,key,fingerprint,limit,invoke,*,metadata,monthly_token_limit=None,token_reservation=None,data_governance=None):
        if data_governance:
            metadata=dict(metadata,source_provider=data_governance.get('source_provider'),scope_id=data_governance.get('scope_id'))
        from app.ai_advisory import AIError
        attempt_id=str(uuid4())
        tenant_id,key=str(UUID(tenant_id)),str(UUID(key))
        from app.data_retention import DataRetention
        try:DataRetention(self.store).purge(tenant_id)
        except Exception:raise AIError('Durable AI coordination unavailable; no inference was started') from None
        try:
            with self.store.transaction(tenant_id,write=True) as db:
                now=self.now(db)
                prior=db.execute('SELECT fingerprint,status,response FROM ai_inference_attempts WHERE tenant_id=%s AND request_key=%s',(tenant_id,key)).fetchone()
                if prior:
                    if prior[0]!=fingerprint:
                        raise AIError('Idempotency key belongs to a different request',409)
                    if prior[1]!='completed':
                        raise AIError('This durable AI attempt is pending or uncertain; it will not be repeated automatically',409)
                    expiry=db.execute('SELECT expires_at FROM ai_data_retention WHERE tenant_id=%s AND attempt_id=(SELECT id FROM ai_inference_attempts WHERE tenant_id=%s AND request_key=%s)',(tenant_id,tenant_id,key)).fetchone()
                    if expiry and instant(expiry[0])<=now:raise AIError('AI content expired under data governance. This request key cannot be replayed.',410)
                    if prior[2] is None:raise AIError('AI content was erased under data governance. This request key cannot be replayed.',410)
                    return dict(decode(prior[2]),cached=True)
                if not db.execute('SELECT 1 FROM scans WHERE tenant_id=%s AND id=%s',(tenant_id,metadata['scan_id'])).fetchone():
                    raise AIError('Owned assessment scan not found',404)
                hour=now.replace(minute=0,second=0,microsecond=0).isoformat()
                count=db.execute('SELECT count(*) FROM ai_inference_attempts WHERE tenant_id=%s AND created_at>=%s',(tenant_id,hour)).fetchone()[0]
                if count>=limit:
                    raise AIError('Workspace AI hourly attempt budget reached',429)
                if monthly_token_limit is not None:
                    if (type(monthly_token_limit) is not int or type(token_reservation) is not int
                            or monthly_token_limit < 1 or not 512 <= token_reservation <= 20096):
                        raise AIError('Invalid server token reservation', 422)
                    start = now.replace(day=1,hour=0,minute=0,second=0,microsecond=0).isoformat()
                    used, unknown = self.token_totals(db, tenant_id, start)
                    if unknown:
                        raise AIError('Unmetered historical attempts prevent verification of the monthly token budget.', 429)
                    if used + token_reservation > monthly_token_limit:
                        raise AIError('Workspace AI monthly token budget cannot reserve this request.', 429)
                    metadata = dict(metadata, reserved_tokens=token_reservation)
                if len(json.dumps(metadata).encode())>8000:
                    raise AIError('Assessment metadata exceeded the allowed bound',422)
                db.execute('''INSERT INTO ai_inference_attempts(id,tenant_id,request_key,fingerprint,scan_id,metadata,created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)''',(attempt_id,tenant_id,key,fingerprint,metadata['scan_id'],db.json(metadata),now.isoformat()))
                retention=data_governance or {}
                expiry=instant(retention['response_expires_at']) if retention.get('response_expires_at') else now+timedelta(days=7)
                db.execute('INSERT INTO ai_data_retention(attempt_id,tenant_id,purpose,policy_digest,expires_at,created_at) VALUES(%s,%s,%s,%s,%s,%s)',
                    (attempt_id,tenant_id,retention.get('purpose',metadata.get('kind','assessment')),retention.get('policy_digest','0'*64),expiry.isoformat(),now.isoformat()))
                self.event(db,tenant_id,attempt_id,'claimed',now)
        except AIError:
            raise
        except Exception:
            raise AIError('Durable AI coordination unavailable; no inference was started') from None
        # The committed pending record persists across process restart and Redis expiry.
        try:
            response=dict(invoke(),assessment_id=attempt_id)
            if len(json.dumps(response).encode())>60000:
                raise AIError('AI assessment exceeded the durable result bound',502)
            usage=response.get('usage') or {}
            with self.store.transaction(tenant_id,write=True) as db:
                now=self.now(db)
                row=db.execute('''UPDATE ai_inference_attempts SET status='completed',response=%s,input_tokens=%s,
                    output_tokens=%s,completed_at=%s WHERE tenant_id=%s AND id=%s AND status='pending' RETURNING id''',
                    (db.json(response),usage.get('input_tokens'),usage.get('output_tokens'),now.isoformat(),tenant_id,attempt_id)).fetchone()
                if not row:
                    raise AIError('AI attempt ownership was lost; no result was committed',409)
                self.event(db,tenant_id,attempt_id,'completed',now)
            return dict(response,cached=False,assessment_id=attempt_id)
        except Exception as error:
            try:
                with self.store.transaction(tenant_id,write=True) as db:
                    changed=db.execute("UPDATE ai_inference_attempts SET status='uncertain' WHERE tenant_id=%s AND id=%s AND status='pending' RETURNING id",(tenant_id,attempt_id)).fetchone()
                    if changed:
                        self.event(db,tenant_id,attempt_id,'uncertain',self.now(db))
            except Exception:
                pass # An already committed pending row still fences repeats.
            if isinstance(error,AIError):
                raise
            raise AIError('AI outcome or durable result is uncertain; no automatic retry was issued') from None

    @staticmethod
    def token_totals(db, tenant_id, start):
        # Pending, uncertain, or partially metered calls keep their complete reservation.
        # A legacy unmetered call without a reservation blocks capped inference until the period expires.
        return db.execute('''SELECT COALESCE(SUM(CASE WHEN status='completed' AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL
            THEN input_tokens+output_tokens ELSE CAST(metadata->>'reserved_tokens' AS BIGINT) END),0),
            COALESCE(SUM(CASE WHEN (status<>'completed' OR input_tokens IS NULL OR output_tokens IS NULL)
            AND metadata->>'reserved_tokens' IS NULL THEN 1 ELSE 0 END),0)
            FROM ai_inference_attempts WHERE tenant_id=%s AND created_at>=%s''', (tenant_id,start)).fetchone()

    def window_summary(self, tenant_id):
        with self.store.transaction(tenant_id) as db:
            now = self.now(db)
            month = now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
            used, unknown = self.token_totals(db, tenant_id, month.isoformat())
            rows = db.execute('''SELECT count(*),COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0),
                COALESCE(SUM(CASE WHEN input_tokens IS NULL OR output_tokens IS NULL THEN 1 ELSE 0 END),0)
                FROM ai_inference_attempts WHERE tenant_id=%s AND created_at>=%s''',
                (tenant_id,(now-timedelta(days=30)).isoformat())).fetchone()
            hour = now.replace(minute=0,second=0,microsecond=0)
            hourly = db.execute('SELECT count(*) FROM ai_inference_attempts WHERE tenant_id=%s AND created_at>=%s',
                                (tenant_id,hour.isoformat())).fetchone()[0]
        return dict(attempts_last_30d=rows[0], known_input_tokens=rows[1], known_output_tokens=rows[2],
                    unmetered_attempts=rows[3], attempts_current_hour=hourly,
                    monthly_tokens_used_or_reserved=used, monthly_unbounded_legacy_attempts=unknown,
                    monthly_period_start=month.isoformat(), hourly_resets_at=(hour+timedelta(hours=1)).isoformat(),
                    monthly_period='UTC calendar month', partial_usage_is_not_zero=True)

    @staticmethod
    def public(row):
        result=dict(zip(COLUMNS.split(','),row))
        for key in ('id','request_key','scan_id'):
            result[key]=str(result[key])
        result['metadata']=decode(result['metadata'])
        return result

    @staticmethod
    def _tenant(tenant):
        return tenant if isinstance(tenant, dict) else {'tenant_id': tenant}

    def page(self,tenant,limit=25,before=None,scan_id=None,resource_reference=None):
        from app.data_retention import DataRetention
        from app.data_scope import predicate
        tenant=self._tenant(tenant);tenant_id=tenant['tenant_id']
        DataRetention(self.store).purge(tenant_id)
        from app.ai_advisory import AIError
        scope_filter,scope_args=predicate(tenant,"metadata->>'source_provider'","metadata->>'scope_id'")
        with self.store.transaction(tenant_id) as db:
            cursor=None
            if before:
                cursor=db.execute('SELECT created_at,id FROM ai_inference_attempts WHERE tenant_id=%s AND id=%s',(tenant_id,before)).fetchone()
                if not cursor:
                    raise AIError('Assessment cursor does not belong to this workspace',422)
            # JSON field filtering uses the shared SQLite/PostgreSQL ->> operator.
            rows=db.execute(f'''SELECT {COLUMNS} FROM ai_inference_attempts WHERE tenant_id=%s
                AND COALESCE(metadata->>'kind','')<>'agent_plan'
                {scope_filter}
                AND (CAST(%s AS TEXT) IS NULL OR scan_id=%s)
                AND (CAST(%s AS TEXT) IS NULL OR metadata->>'resource_reference'=%s)
                AND (CAST(%s AS TEXT) IS NULL OR created_at<%s OR (created_at=%s AND id<%s))
                ORDER BY created_at DESC,id DESC LIMIT %s''',
                (tenant_id,*scope_args,scan_id,scan_id,resource_reference,resource_reference,
                 cursor[0] if cursor else None,cursor[0] if cursor else None,cursor[0] if cursor else None,cursor[1] if cursor else None,limit+1)).fetchall()
            return dict(items=[self.public(r) for r in rows[:limit]],next_cursor=str(rows[limit-1][0]) if len(rows)>limit else None,
                        durable=True)

    def get(self,tenant,attempt_id):
        from app.data_retention import DataRetention
        from app.data_scope import metadata_visible
        tenant=self._tenant(tenant);tenant_id=tenant['tenant_id']
        DataRetention(self.store).purge(tenant_id)
        with self.store.transaction(tenant_id) as db:
            row=db.execute(f'SELECT {COLUMNS},response FROM ai_inference_attempts WHERE tenant_id=%s AND id=%s',(tenant_id,attempt_id)).fetchone()
            if not row:
                return None
            if not metadata_visible(tenant,decode(row[3])):
                return None
            if decode(row[3]).get('kind')=='agent_plan':
                # Planning shares metering, but its response is not an assessment/advisory schema.
                return None
            result=self.public(row[:-1]);result['response']=decode(row[-1]) if row[-1] else None
            expiry=db.execute('SELECT expires_at,erased_at FROM ai_data_retention WHERE tenant_id=%s AND attempt_id=%s',(tenant_id,attempt_id)).fetchone()
            if expiry:
                result['content_retention']=dict(expires_at=str(expiry[0]),erased_at=str(expiry[1]) if expiry[1] else None)
                if expiry[1] or instant(expiry[0])<=self.now(db):result['response']=None
            result['events']=[dict(action=r[0],created_at=r[1]) for r in db.execute('SELECT action,created_at FROM ai_inference_events WHERE tenant_id=%s AND attempt_id=%s ORDER BY created_at,id',(tenant_id,attempt_id)).fetchall()]
            return result

    def usage(self,tenant,days=30):
        from app.data_scope import metadata_visible
        tenant=self._tenant(tenant);tenant_id=tenant['tenant_id']
        with self.store.transaction(tenant_id) as db:
            start=(self.now(db)-timedelta(days=days)).isoformat()
            rows=db.execute("SELECT metadata,status,input_tokens,output_tokens FROM ai_inference_attempts WHERE tenant_id=%s AND created_at>=%s ORDER BY created_at LIMIT 10001",(tenant_id,start)).fetchall()
        if len(rows)>10000:
            from app.ai_advisory import AIError
            raise AIError('Usage window exceeds 10000 attempts; select fewer days',422)
        groups={}
        for raw,status,input_tokens,output_tokens in rows:
            meta=decode(raw)
            if not metadata_visible(tenant,meta):
                continue
            key=(meta['provider'],meta['model'],meta['target_id'],meta.get('cost_center','unassigned'),meta.get('application_id','unassigned'))
            group=groups.setdefault(key,dict(provider=key[0],model=key[1],target_id=key[2],cost_center=key[3],application_id=key[4],attribution_source='observed_tags_unverified',attempts=0,completed=0,
                incomplete_outcomes=0,unmetered_completions=0,input_tokens=None,output_tokens=None,billed_cost_usd=None))
            group['attempts']+=1;group['completed']+=status=='completed';group['incomplete_outcomes']+=status!='completed'
            group['unmetered_completions']+=status=='completed' and (input_tokens is None or output_tokens is None)
            for field,value in (('input_tokens',input_tokens),('output_tokens',output_tokens)):
                if value is not None:
                    group[field]=(group[field] or 0)+value
        return dict(days=days,durable=True,source='provider_reported_completed_attempts',billed_cost_available=False,
                    groups=[groups[key] for key in sorted(groups)])
