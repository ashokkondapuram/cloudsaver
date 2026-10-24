"""Data-use audit, retention, legal holds and narrowly scoped content erasure."""
revision='0018_ai_data_governance'
down_revision='0017_agent_execution'
branch_labels=depends_on=None


def upgrade():
    from alembic import op
    op.execute('ALTER TABLE ai_inference_attempts ADD COLUMN content_erased_at timestamptz')
    op.execute('ALTER TABLE ai_inference_attempts DROP CONSTRAINT ai_inference_attempts_check')
    op.execute('''ALTER TABLE ai_inference_attempts ADD CONSTRAINT ai_inference_content_state CHECK(
        (status='completed' AND completed_at IS NOT NULL AND ((response IS NOT NULL AND content_erased_at IS NULL)
            OR (response IS NULL AND content_erased_at IS NOT NULL)))
        OR (status<>'completed' AND response IS NULL AND completed_at IS NULL))''')
    op.execute('''CREATE TABLE ai_data_events (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,purpose varchar(40) NOT NULL,decision varchar(16) NOT NULL,
        reason varchar(80) NOT NULL,policy_digest char(64) NOT NULL,target_id varchar(40),metadata jsonb NOT NULL,
        actor char(64) NOT NULL,created_at timestamptz NOT NULL,CHECK(octet_length(metadata::text)<=2000))''')
    op.execute('CREATE INDEX ix_ai_data_events ON ai_data_events(tenant_id,created_at DESC,id DESC)')
    # Approval/event hashes remain; old event copies must not retain model-generated plan bodies.
    op.execute('ALTER TABLE agent_task_events NO FORCE ROW LEVEL SECURITY')
    op.execute("UPDATE agent_task_events SET payload=(payload-'plan') || jsonb_build_object('plan_body_removed_by_data_governance',true) WHERE payload ? 'plan'")
    op.execute('ALTER TABLE agent_task_events FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE agent_tasks NO FORCE ROW LEVEL SECURITY')
    op.execute("UPDATE agent_tasks SET payload=payload || jsonb_build_object('data_retention_expires_at',clock_timestamp()+interval '7 days') WHERE payload->>'data_retention_expires_at' IS NULL")
    op.execute('ALTER TABLE agent_tasks FORCE ROW LEVEL SECURITY')
    op.execute('''CREATE TABLE ai_data_retention (
        attempt_id uuid PRIMARY KEY,tenant_id uuid NOT NULL,purpose varchar(40) NOT NULL,policy_digest char(64) NOT NULL,
        expires_at timestamptz NOT NULL,erased_at timestamptz,created_at timestamptz NOT NULL,
        CHECK(expires_at>created_at AND expires_at<=created_at+interval '30 days'),
        FOREIGN KEY(attempt_id,tenant_id) REFERENCES ai_inference_attempts(id,tenant_id) ON DELETE RESTRICT)''')
    op.execute('ALTER TABLE ai_inference_attempts NO FORCE ROW LEVEL SECURITY')
    op.execute('''INSERT INTO ai_data_retention(attempt_id,tenant_id,purpose,policy_digest,expires_at,created_at)
        SELECT id,tenant_id,'legacy_inference',repeat('0',64),clock_timestamp()+interval '7 days',clock_timestamp() FROM ai_inference_attempts''')
    op.execute('ALTER TABLE ai_inference_attempts FORCE ROW LEVEL SECURITY')
    op.execute('''CREATE TABLE ai_data_holds (
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,attempt_id uuid NOT NULL,review_reference varchar(120) NOT NULL,
        hold_until timestamptz NOT NULL,actor char(64) NOT NULL,created_at timestamptz NOT NULL,
        CHECK(hold_until>created_at AND hold_until<=created_at+interval '30 days'),
        FOREIGN KEY(attempt_id,tenant_id) REFERENCES ai_inference_attempts(id,tenant_id) ON DELETE RESTRICT)''')
    for table in ('ai_data_events','ai_data_retention','ai_data_holds'):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid) WITH CHECK(tenant_id=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid)")
        op.execute(f'REVOKE ALL ON {table} FROM PUBLIC')
        op.execute(f'GRANT SELECT,INSERT ON {table} TO cloudsaver_app')
    op.execute('''CREATE OR REPLACE FUNCTION protect_inference_outcome() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF current_user<>'cloudsaver_app' AND NEW.response IS NULL AND NEW.content_erased_at IS NOT NULL
            AND (to_jsonb(OLD)-'response'-'content_erased_at')=(to_jsonb(NEW)-'response'-'content_erased_at') THEN RETURN NEW; END IF;
          IF OLD.status<>'pending' OR NEW.status NOT IN ('completed','uncertain') THEN
            RAISE EXCEPTION 'Inference outcomes are final' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$''')
    op.execute('''CREATE FUNCTION erase_ai_content(target uuid,actor_reference text,privacy_reference text DEFAULT NULL)
        RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
        DECLARE tid uuid:=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid; retention_row public.ai_data_retention;
        BEGIN
          IF tid IS NULL OR actor_reference !~ '^[a-f0-9]{64}$' THEN RETURN false; END IF;
          IF privacy_reference IS NOT NULL AND privacy_reference !~ '^[A-Za-z0-9][A-Za-z0-9._/-]{2,119}$' THEN RETURN false; END IF;
          SELECT * INTO retention_row FROM public.ai_data_retention WHERE tenant_id=tid AND attempt_id=target FOR UPDATE;
          IF NOT FOUND OR retention_row.erased_at IS NOT NULL THEN RETURN false; END IF;
          PERFORM 1 FROM public.ai_inference_attempts WHERE tenant_id=tid AND id=target AND status<>'pending' FOR UPDATE;
          IF NOT FOUND THEN RETURN false; END IF;
          IF privacy_reference IS NULL AND retention_row.expires_at>clock_timestamp() THEN RETURN false; END IF;
          IF EXISTS(SELECT 1 FROM public.ai_data_holds WHERE tenant_id=tid AND attempt_id=target AND hold_until>clock_timestamp()) THEN RETURN false; END IF;
          UPDATE public.ai_inference_attempts SET response=NULL,content_erased_at=clock_timestamp() WHERE tenant_id=tid AND id=target;
          UPDATE public.ai_followups SET question='[ERASED BY DATA RETENTION]' WHERE tenant_id=tid AND attempt_id=target;
          UPDATE public.ai_data_retention SET erased_at=clock_timestamp() WHERE tenant_id=tid AND attempt_id=target;
          INSERT INTO public.ai_data_events VALUES(gen_random_uuid(),tid,retention_row.purpose,'erased',
            CASE WHEN privacy_reference IS NULL THEN 'RETENTION_EXPIRED' ELSE 'PRIVACY_REQUEST' END,
            retention_row.policy_digest,NULL,jsonb_build_object('review_reference',privacy_reference),actor_reference,clock_timestamp());
          RETURN true;
        END $$''')
    op.execute('REVOKE ALL ON FUNCTION erase_ai_content(uuid,text,text) FROM PUBLIC')
    op.execute('GRANT EXECUTE ON FUNCTION erase_ai_content(uuid,text,text) TO cloudsaver_app')


def downgrade():
    from alembic import op
    op.execute('ALTER TABLE ai_inference_attempts NO FORCE ROW LEVEL SECURITY')
    erased=op.get_bind().exec_driver_sql('SELECT 1 FROM ai_inference_attempts WHERE content_erased_at IS NOT NULL LIMIT 1').fetchone()
    op.execute('ALTER TABLE ai_inference_attempts FORCE ROW LEVEL SECURITY')
    if erased:
        raise RuntimeError('Erased content is irreversible. Downgrade would violate the old completed-response contract; no content is restored.')
    op.execute('DROP FUNCTION erase_ai_content(uuid,text,text)')
    op.execute('''CREATE OR REPLACE FUNCTION protect_inference_outcome() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.status<>'pending' OR NEW.status NOT IN ('completed','uncertain') THEN
            RAISE EXCEPTION 'Inference outcomes are final' USING ERRCODE='23514'; END IF;
          RETURN NEW;
        END $$''')
    for table in ('ai_data_holds','ai_data_retention','ai_data_events'):op.execute('DROP TABLE '+table)
    op.execute('ALTER TABLE ai_inference_attempts DROP CONSTRAINT ai_inference_content_state')
    op.execute('ALTER TABLE ai_inference_attempts DROP COLUMN content_erased_at')
    op.execute("ALTER TABLE ai_inference_attempts ADD CONSTRAINT ai_inference_attempts_check CHECK((status='completed' AND response IS NOT NULL AND completed_at IS NOT NULL) OR (status<>'completed' AND response IS NULL AND completed_at IS NULL))")
