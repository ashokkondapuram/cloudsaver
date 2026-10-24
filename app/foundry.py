"""Current policy, immutable approved bindings, and tenant-owned AI preferences."""
import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from app.ai_advisory import AIError, Target
from app.foundry_config import FoundrySettings, normalize, provider_fields, template


class FoundryController:
    def __init__(self, settings, targets=None, ledger=None, policy_reader=None, deployment_limit=None):
        self.settings, self.ledger = settings, ledger
        from app.ai_platform_policy import current
        self.policy_reader = policy_reader or current
        self.deployment_limit = int(os.getenv('CLOUDSAVER_AI_HOURLY_ATTEMPTS', '10')) if deployment_limit is None else deployment_limit
        self.targets = targets if targets is not None else [Target.model_validate(row) for row in json.loads(os.getenv('CLOUDSAVER_AI_TARGETS', '[]'))]

    def configuration(self, tenant):
        row = self.settings.registry.get(tenant['tenant_id']) if self.settings.registry is not None else tenant
        if row is None:
            raise AIError('Workspace settings are unavailable.', 404)
        try:
            return row, normalize(row.get('ai_foundry'))
        except ValueError:
            raise AIError('Saved AI preferences failed validation. Contact the workspace administrator.', 503) from None

    def catalog(self, tenant):
        return [target for target in self.targets if str(target.tenant_id) == tenant['tenant_id']]

    @staticmethod
    def plan_allowed(tenant):
        from app.entitlements import entitlements_for
        if not entitlements_for(tenant).can_use_ai_advisory:
            raise AIError('AI advisory is not included in this workspace plan.', 403)

    def binding(self, tenant, provider, config, platform):
        selected = config['providers'][provider]
        target = next((target for target in self.catalog(tenant) if target.target_id == selected['target_id'] and target.provider == provider), None)
        if target is None:
            raise AIError('Select an operator-approved model binding for this workspace.', 422)
        if provider not in platform['allowed_providers'] or provider in platform['disabled_providers']:
            raise AIError('This AI provider is disabled by platform policy.', 403)
        if target.model not in platform['allowed_models'][provider] or target.region not in platform['allowed_regions'][provider]:
            raise AIError('The selected model or destination region is not approved by current platform policy.', 403)
        expected = provider_fields(target, tenant['tenant_id'])
        if any(selected.get(key) != value for key, value in expected.items()):
            raise AIError('Endpoint, model, identity, region and guardrail must match the approved binding.', 422)
        if provider == 'aws' and target.guardrail_version == 'DRAFT' and os.getenv('CLOUDSAVER_ENVIRONMENT') == 'production':
            raise AIError('Production requires a published Bedrock guardrail version.', 422)
        return target

    def validate_configuration(self, tenant, value):
        self.plan_allowed(tenant)
        config = normalize(value)
        platform = self.policy_reader()['policy']
        policy = config['policy']
        for name, ceiling in (('max_input_tokens_per_request', 'max_input_tokens_per_request'),
            ('max_output_tokens_per_request', 'max_output_tokens_per_request'), ('hourly_attempt_budget', 'hourly_attempt_ceiling')):
            if policy[name] > platform[ceiling]:
                raise AIError('Workspace AI budgets exceed the platform ceilings.', 422)
        if policy['monthly_token_limit'] is not None and policy['monthly_token_limit'] > platform['monthly_token_ceiling']:
            raise AIError('Workspace token limit exceeds the platform ceiling.', 422)
        if policy['routing_mode'] != 'same_cloud_only':
            # A workspace key does not prove fresh human reauthentication. Do not silently substitute a checkbox.
            raise AIError('Cross-provider routing requires verified human step-up authentication; it is unavailable here.', 403)
        if policy['allow_anonymized_knowledge_candidates'] and not platform['allow_knowledge_candidates']:
            raise AIError('Knowledge candidate consent is disabled by platform policy.', 403)
        for provider, selected in config['providers'].items():
            if selected['target_id'] is not None:
                self.binding(tenant, provider, config, platform)
            elif selected['enabled']:
                raise AIError('Select an approved target before enabling an AI provider.', 422)
        if policy['advisory_enabled'] and (not platform['enabled'] or not any(item['enabled'] for item in config['providers'].values())):
            raise AIError('Enable an approved provider and obtain platform approval before enabling advisory.', 403)
        return config

    def check_write(self, tenant, value, acknowledgement):
        from app.config import directory_mode
        if 'TenantAdmin' not in tenant.get('roles', []) or tenant.get('all_providers') is False or tenant.get('scope_restrictions'):
            raise AIError('An unrestricted workspace administrator is required to configure AI.', 403)
        if directory_mode() == 'cutover':
            raise AIError('AI settings are locked while the platform directory owns this workspace configuration.', 403)
        if self.settings.registry is None:
            raise AIError('Durable workspace settings are unavailable.', 503)
        if value['policy']['advisory_enabled'] and acknowledgement is not True:
            raise AIError('Acknowledge the selected destination and unverified external advisory processing.', 422)

    def save(self, tenant, version, value, acknowledgement):
        from app.tenant_registry import VersionConflict
        from app.settings_api import actor_for
        self.check_write(tenant, value, acknowledgement)
        config = self.validate_configuration(tenant, value)
        try:
            row = self.settings.registry.update(tenant['tenant_id'], {'ai_foundry': config}, version, actor_for(tenant))
        except VersionConflict:
            raise AIError('Settings changed. Refresh before saving again.', 409) from None
        return dict(version=row['version'], ai_foundry=row['ai_foundry'])

    def resolved(self, tenant, provider=None, target_id=None, *, diagnostic=False):
        self.plan_allowed(tenant)
        _, config = self.configuration(tenant)
        remote = self.policy_reader()
        platform, policy = remote['policy'], config['policy']
        if not platform['enabled'] or (not diagnostic and not policy['advisory_enabled']):
            raise AIError('AI advisory is disabled by workspace or platform policy.', 403)
        if policy['routing_mode'] != 'same_cloud_only':
            raise AIError('Cross-provider inference is blocked until verified step-up authentication is supported.', 403)
        if provider == 'kubernetes':
            raise AIError('Kubernetes hosting-cloud identity is unverified. Same-cloud inference is blocked.', 403)
        source = provider
        candidates = [target for target in self.catalog(tenant) if target_id is None or target.target_id == target_id]
        result = []
        for target in candidates:
            selected = config['providers'][target.provider]
            if selected['target_id'] != target.target_id or not (selected['enabled'] or diagnostic):
                continue
            if source is not None and target.provider != source:
                continue
            target = self.binding(tenant, target.provider, config, platform)
            sources = [value for value in target.allowed_source_providers if value == target.provider]
            target = target.model_copy(update=dict(max_output_tokens=min(target.max_output_tokens, policy['max_output_tokens_per_request'], platform['max_output_tokens_per_request']),
                max_input_tokens=min(target.max_input_tokens, policy['max_input_tokens_per_request'], platform['max_input_tokens_per_request']),
                allowed_source_providers=sources, approved_regions=platform['allowed_regions'][target.provider]))
            result.append(target)
        if target_id is not None and not result:
            raise AIError('No approved same-cloud target is configured for this resource. Configure AI Foundry in Settings.', 403)
        return result, dict(hourly=min(policy['hourly_attempt_budget'], platform['hourly_attempt_ceiling'], self.deployment_limit),
            monthly=min(policy['monthly_token_limit'] or platform['monthly_token_ceiling'], platform['monthly_token_ceiling']),
            platform_version=remote['version'], routing_mode=policy['routing_mode'])

    def view(self, tenant):
        from app.config import directory_mode
        row, config = self.configuration(tenant)
        remote = self.policy_reader()
        editable = self.settings.registry is not None and 'TenantAdmin' in tenant.get('roles', []) and directory_mode() != 'cutover'
        from app.entitlements import entitlements_for
        plan_allowed = entitlements_for(tenant).can_use_ai_advisory
        return dict(version=row.get('version', 0), ai_foundry=config, platform_policy=remote,
            plan_allowed=plan_allowed, editable=editable and plan_allowed and not tenant.get('scope_restrictions') and tenant.get('all_providers') is not False,
            directory_mode=directory_mode(), catalog=[template(target, tenant['tenant_id']) for target in self.catalog(tenant)],
            usage=self.ledger.window_summary(tenant['tenant_id']) if self.ledger else None,
            diagnostics=self.diagnostics(tenant['tenant_id']),
            knowledge_retrieval='configured' if os.getenv('CLOUDSAVER_KNOWLEDGE_ENABLED') == 'true' else 'disabled',
            candidate_pipeline_enabled=False,
            message='Only operator-approved tenant bindings may be selected. Diagnostics never invoke a model or prove inference RBAC.')

    def diagnostics(self, tenant_id):
        if self.ledger is None:
            return []
        from app.enterprise_store import decode
        with self.ledger.store.transaction(tenant_id) as db:
            return [dict(id=str(row[0]), provider=row[1], created_at=row[2], result=decode(row[3]))
                for row in db.execute("SELECT id,provider,created_at,result FROM ai_connection_diagnostics WHERE tenant_id=%s AND result->>'phase'='completed' ORDER BY created_at DESC,id DESC LIMIT 10", (tenant_id,)).fetchall()]

    def diagnose(self, tenant, provider, target_id, probe=None):
        from app.foundry_diagnostics import metadata_probe
        targets, limits = self.resolved(tenant, provider, target_id, diagnostic=True)
        if self.ledger is None:
            raise AIError('Durable diagnostic history is unavailable.', 503)
        actor = hashlib.sha256((tenant.get('subject_id') or tenant['tenant_id']).encode()).hexdigest()
        attempt = str(uuid4())
        with self.ledger.store.transaction(tenant['tenant_id'], write=True) as db:
            now = self.ledger.now(db)
            count = db.execute("SELECT count(*) FROM ai_connection_diagnostics WHERE tenant_id=%s AND created_at>=%s AND result->>'phase'='started'",
                               (tenant['tenant_id'], (now-timedelta(minutes=1)).isoformat())).fetchone()[0]
            if count >= 3:
                raise AIError('AI connection checks are limited to three attempts per minute.', 429)
            db.execute('INSERT INTO ai_connection_diagnostics(id,tenant_id,provider,target_id,actor,result,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                (attempt, tenant['tenant_id'], provider, target_id, actor, db.json({'phase': 'started'}), now.isoformat()))
        result = (probe or metadata_probe)(targets[0], tenant)
        result = dict(result, platform_policy_version=limits['platform_version'], inference_invoked=False,
                      phase='completed', attempt_id=attempt)
        with self.ledger.store.transaction(tenant['tenant_id'], write=True) as db:
            # Bound repeated checks before a remote request in the router; this record contains sanitized stages only.
            db.execute('INSERT INTO ai_connection_diagnostics(id,tenant_id,provider,target_id,actor,result,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                (str(uuid4()), tenant['tenant_id'], provider, target_id, actor, db.json(result), datetime.now(timezone.utc).isoformat()))
        return result
