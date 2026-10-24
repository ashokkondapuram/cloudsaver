"""Scoped governance metadata, immutable preservation evidence and analysis audit fields."""
revision='0019_multicloud_governance_and_pillars'
down_revision='0018_ai_data_governance'
branch_labels=depends_on=None
EVENT_COLUMNS='id,tenant_id,purpose,decision,reason,policy_digest,target_id,metadata,actor,created_at'
ORIGINAL_TAIL='actor_reference,clock_timestamp());'
SCOPED_TAIL="actor_reference,clock_timestamp(),(SELECT a.metadata->>'source_provider' FROM public.ai_inference_attempts a WHERE a.tenant_id=tid AND a.id=target),(SELECT a.metadata->>'scope_id' FROM public.ai_inference_attempts a WHERE a.tenant_id=tid AND a.id=target));"

def upgrade():
    from alembic import op
    op.execute('ALTER TABLE alembic_version ALTER COLUMN version_num TYPE varchar(80)')
    op.execute('ALTER TABLE ai_data_events ADD COLUMN cloud_provider varchar(32), ADD COLUMN scope_id varchar(128)')
    op.execute('CREATE INDEX ix_ai_data_events_tenant_scope ON ai_data_events(tenant_id,cloud_provider,scope_id,created_at)')
    op.execute('ALTER TABLE ai_data_holds ADD COLUMN released_at timestamptz, ADD COLUMN released_by varchar(128), ADD COLUMN release_reason varchar(500), ADD COLUMN review_ticket varchar(120)')
    for table in ('cloud_findings','waste_findings'):
        op.execute(f'ALTER TABLE {table} ADD COLUMN opportunity_group_id varchar(160), ADD COLUMN slo_burn_rate numeric(10,4)')
    # JSON remains the canonical assessment store in this baseline. Do not create
    # fictitious resource_assessments_v2 / ai_processing_events parallel tables.
    source=op.get_bind().exec_driver_sql("SELECT pg_get_functiondef('erase_ai_content(uuid,text,text)'::regprocedure)").scalar_one()
    if 'INSERT INTO public.ai_data_events VALUES(' not in source or ORIGINAL_TAIL not in source:raise RuntimeError('Unexpected prior erasure function; inspect migration baseline.')
    source=source.replace('INSERT INTO public.ai_data_events VALUES(',f'INSERT INTO public.ai_data_events({EVENT_COLUMNS},cloud_provider,scope_id) VALUES(')
    source=source.replace(ORIGINAL_TAIL,SCOPED_TAIL).replace('AND hold_until>clock_timestamp()','AND released_at IS NULL AND hold_until>clock_timestamp()')
    op.execute(source)
    op.execute('''CREATE FUNCTION release_ai_hold(target uuid,actor_reference text,reason_text text,ticket text)
      RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      DECLARE tid uuid:=NULLIF(current_setting('app.current_tenant_id',true),'')::uuid; hold_row public.ai_data_holds;
      BEGIN
        IF tid IS NULL OR actor_reference IS NULL OR actor_reference !~ '^[a-f0-9]{64}$' OR reason_text IS NULL
          OR length(reason_text)<3 OR length(reason_text)>500 OR ticket IS NULL OR ticket !~ '^[A-Za-z0-9][A-Za-z0-9._/-]{2,119}$' THEN RETURN false; END IF;
        SELECT * INTO hold_row FROM public.ai_data_holds WHERE tenant_id=tid AND id=target FOR UPDATE;
        IF NOT FOUND OR hold_row.released_at IS NOT NULL OR hold_row.hold_until<=clock_timestamp() THEN RETURN false; END IF;
        UPDATE public.ai_data_holds SET released_at=clock_timestamp(),released_by=actor_reference,release_reason=reason_text,review_ticket=ticket WHERE tenant_id=tid AND id=target;
        INSERT INTO public.ai_data_events(id,tenant_id,purpose,decision,reason,policy_digest,target_id,metadata,actor,created_at,cloud_provider,scope_id)
          SELECT gen_random_uuid(),tid,r.purpose,'released','LEGAL_HOLD_RELEASED',r.policy_digest,NULL,
            jsonb_build_object('hold_reference',target,'review_ticket',ticket),actor_reference,clock_timestamp(),a.metadata->>'source_provider',a.metadata->>'scope_id'
          FROM public.ai_data_retention r JOIN public.ai_inference_attempts a ON a.id=r.attempt_id AND a.tenant_id=r.tenant_id
          WHERE r.tenant_id=tid AND r.attempt_id=hold_row.attempt_id;
        RETURN true;
      END $$''')
    op.execute('REVOKE ALL ON FUNCTION release_ai_hold(uuid,text,text,text) FROM PUBLIC')
    op.execute('GRANT EXECUTE ON FUNCTION release_ai_hold(uuid,text,text,text) TO cloudsaver_app')

def downgrade():
    from alembic import op
    # Early release changes preservation semantics; refuse to silently resurrect a hold.
    op.execute('ALTER TABLE ai_data_holds NO FORCE ROW LEVEL SECURITY')
    released=op.get_bind().exec_driver_sql('SELECT 1 FROM ai_data_holds WHERE released_at IS NOT NULL LIMIT 1').fetchone()
    op.execute('ALTER TABLE ai_data_holds FORCE ROW LEVEL SECURITY')
    if released:raise RuntimeError('Released legal holds require a forward fix; downgrade cannot silently reinstate preservation.')
    op.execute('DROP FUNCTION release_ai_hold(uuid,text,text,text)')
    source=op.get_bind().exec_driver_sql("SELECT pg_get_functiondef('erase_ai_content(uuid,text,text)'::regprocedure)").scalar_one()
    source=source.replace('AND released_at IS NULL AND hold_until>clock_timestamp()','AND hold_until>clock_timestamp()')
    source=source.replace(f'{EVENT_COLUMNS},cloud_provider,scope_id',EVENT_COLUMNS).replace(SCOPED_TAIL,ORIGINAL_TAIL)
    op.execute(source)
    op.execute('ALTER TABLE ai_data_holds DROP COLUMN released_at,DROP COLUMN released_by,DROP COLUMN release_reason,DROP COLUMN review_ticket')
    op.execute('DROP INDEX ix_ai_data_events_tenant_scope')
    op.execute('ALTER TABLE ai_data_events DROP COLUMN cloud_provider,DROP COLUMN scope_id')
    for table in ('cloud_findings','waste_findings'):
        op.execute(f'ALTER TABLE {table} DROP COLUMN opportunity_group_id,DROP COLUMN slo_burn_rate')
