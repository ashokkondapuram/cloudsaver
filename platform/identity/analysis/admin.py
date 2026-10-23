"""Analysis rule catalog and per-workspace enablement."""
from identity.domain import IdentityError, NotFound, StaleVersion, iso, text, uuid_text


class AnalysisOps:
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
        }

    def list_analysis_rules(self):
        with self.store.transaction() as tx:
            return {'items': [self._rule_view(r) for r in tx.list_rule_catalog()]}

    def list_workspace_analysis_rules(self, tenant_id):
        tenant_id = uuid_text(tenant_id)
        with self.store.transaction() as tx:
            if not tx.get_workspace(tenant_id):
                raise NotFound('Workspace not found.')
            overrides = {r['rule_id']: r for r in tx.list_workspace_rules(tenant_id)}
            items = [self._rule_view(r, overrides.get(r['id'])) for r in tx.list_rule_catalog()]
        return {'tenant_id': str(tenant_id), 'items': items}

    def update_workspace_analysis_rules(self, tenant_id, payload, actor, request_id=None):
        tenant_id = uuid_text(tenant_id)
        version = self._version(payload)
        rules = payload.get('rules')
        if not isinstance(rules, list) or not rules:
            raise IdentityError('Include at least one rule setting.')
        now = self.now()
        with self.store.transaction() as tx:
            workspace = tx.get_workspace(tenant_id, lock=True)
            if not workspace or workspace['status'] == 'deleted':
                raise NotFound('Workspace not found.')
            if workspace['version'] != version:
                raise StaleVersion()
            catalog = {r['id']: r for r in tx.list_rule_catalog()}
            for item in rules:
                rule_id = text(item.get('rule_id'), 'Rule', 80)
                if rule_id not in catalog:
                    raise IdentityError('Choose a published rule from the catalog.')
                enabled = bool(item.get('enabled', True))
                reason = item.get('unavailable_reason')
                if reason is not None:
                    reason = text(reason, 'Unavailable reason', 500)
                tx.upsert_workspace_rule(tenant_id, rule_id, {
                    'enabled': enabled, 'unavailable_reason': reason,
                    'updated_at': now, 'updated_by': actor['actor'][:120],
                })
            self._event(tx, actor, 'workspace_rules_updated', tenant_id, request_id=request_id)
        return self.list_workspace_analysis_rules(tenant_id)

    def effective_analysis_rules(self, tenant_id):
        """Internal: enabled rule ids for scanners."""
        data = self.list_workspace_analysis_rules(tenant_id)
        enabled = [r['id'] for r in data['items'] if r['status'] == 'published' and r['enabled'] and not r['unavailable_reason']]
        return {'tenant_id': data['tenant_id'], 'enabled_rule_ids': enabled}
