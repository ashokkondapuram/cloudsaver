"""Analysis rule catalog and per-workspace enablement."""
from identity.domain import IdentityError, NotFound, StaleVersion, iso, text, uuid_text
from identity.analysis.contracts import BOUNDS, validate_parameters


class AnalysisOps:
    def customer_analysis_rules(self, tenant_id, grant, payload=None, request_id=None):
        with self.store.transaction() as tx:
            self._customer_workspace(tx, grant, tenant_id, admin=payload is not None)
            if payload is not None:
                self._roles_subset(['TenantAdmin'], self._issuer_roles(tx, tenant_id, grant))
        if payload is None:
            return self.list_workspace_analysis_rules(tenant_id)
        return self.update_workspace_analysis_rules(tenant_id, payload,
            {'actor': grant['subject_id'], 'actor_type': 'customer'}, request_id)

    def _rule_view(self, row, override=None):
        enabled = True
        unavailable = None
        if override is not None:
            enabled = bool(override['enabled'])
            unavailable = override.get('unavailable_reason')
        return {
            'id': row['id'], 'provider': row['provider'], 'service_category': row['service_category'],
            'resource_type': row['resource_type'], 'name': row['name'], 'description': row.get('description') or '',
            'pillar': row['pillar'], 'status': row['status'], 'enabled': enabled,
            'unavailable_reason': unavailable, 'catalog_version': row['version'],
            'override_version': override['version'] if override else None,
            'parameters': {k: v[0] for k, v in BOUNDS.get(row['id'], {}).items()} | ((override or {}).get('parameters') or {}),
            'allowed_override_bounds': {k: {'minimum': v[1], 'maximum': v[2]} for k, v in BOUNDS.get(row['id'], {}).items()},
        }

    def list_analysis_rules(self):
        with self.store.transaction() as tx:
            return {'items': [self._rule_view(r) for r in tx.list_rule_catalog()]}

    def list_workspace_analysis_rules(self, tenant_id):
        tenant_id = uuid_text(tenant_id)
        with self.store.transaction() as tx:
            workspace = tx.get_workspace(tenant_id)
            if not workspace:
                raise NotFound('Workspace not found.')
            overrides = {r['rule_id']: r for r in tx.list_workspace_rules(tenant_id)}
            items = [self._rule_view(r, overrides.get(r['id'])) for r in tx.list_rule_catalog()]
        return {'tenant_id': str(tenant_id), 'version': workspace['version'], 'items': items}

    def update_workspace_analysis_rules(self, tenant_id, payload, actor, request_id=None):
        tenant_id = uuid_text(tenant_id)
        version = self._version(payload)
        rules = payload.get('rules')
        if not isinstance(rules, list) or not rules or len(rules) > 100 or any(not isinstance(item, dict) for item in rules):
            raise IdentityError('Include at least one rule setting.')
        if len({item.get('rule_id') for item in rules if isinstance(item.get('rule_id'), str)}) != len(rules):
            raise IdentityError('Include each valid rule only once.')
        now = self.now()
        with self.store.transaction() as tx:
            workspace = tx.get_workspace(tenant_id, lock=True)
            if not workspace or workspace['status'] == 'deleted':
                raise NotFound('Workspace not found.')
            if workspace['version'] != version:
                raise StaleVersion()
            catalog = {r['id']: r for r in tx.list_rule_catalog()}
            current = {r['rule_id']: r for r in tx.list_workspace_rules(tenant_id)}
            for item in rules:
                rule_id = text(item.get('rule_id'), 'Rule', 80)
                if rule_id not in catalog:
                    raise IdentityError('Choose a published rule from the catalog.')
                if catalog[rule_id]['status'] != 'published':
                    raise IdentityError('Choose a published rule from the catalog.')
                enabled = item.get('enabled', True)
                if type(enabled) is not bool:
                    raise IdentityError('Enabled must be a boolean.')
                try:
                    params = validate_parameters(rule_id, item.get('parameters', current.get(rule_id, {}).get('parameters') or {}))
                except ValueError as exc:
                    raise IdentityError(str(exc)) from None
                reason = item.get('unavailable_reason')
                if reason is not None:
                    reason = text(reason, 'Unavailable reason', 500)
                tx.upsert_workspace_rule(tenant_id, rule_id, {
                    'enabled': enabled, 'unavailable_reason': reason, 'parameters': params,
                    'updated_at': now, 'updated_by': actor['actor'][:120],
                })
            updated = tx.update_workspace(tenant_id, version, {'updated_at': now, 'updated_by': actor['actor'][:120]})
            if updated is None:
                raise StaleVersion()
            self._changed(tx, updated)
            self._event(tx, actor, 'workspace_rules_updated', tenant_id, request_id=request_id)
            self._publish([{'tenant_id': tenant_id, 'event': 'rules_changed', 'directory': True}], tx)
        return self.list_workspace_analysis_rules(tenant_id)

    def effective_analysis_rules(self, tenant_id):
        """Internal: enabled rule ids for scanners."""
        data = self.list_workspace_analysis_rules(tenant_id)
        enabled = [r['id'] for r in data['items'] if r['status'] == 'published' and r['enabled'] and not r['unavailable_reason']]
        return {**data, 'enabled_rule_ids': enabled}
