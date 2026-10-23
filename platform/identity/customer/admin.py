"""Customer-owned users, memberships, bootstrap claim, and delegated keys."""
import csv
import io
from datetime import timedelta
from uuid import uuid4

from identity.domain import (CUSTOMER_ADMIN_ROLES, DEFAULT_BOOTSTRAP_HOURS, DEFAULT_EXPIRY_DAYS, MAX_ACTIVE_KEYS,
                             MAX_BOOTSTRAP_HOURS, MAX_INVITES_PER_DAY, MAX_SERVICE_ACCOUNTS, ROLES, Conflict,
                             IdentityError, NotFound, StaleVersion, iso, normalize_roles, text, uuid_text)

FORBIDDEN = "You don't have permission to make this change."


def _actor(grant):
    return {'actor': grant['subject_id'], 'actor_type': 'customer'}


class CustomerOps:
    def _user_view(self, row):
        return {'user_id': str(row['id']), 'display_name': row['display_name'], 'email': row.get('email'),
                'email_verified': bool(row.get('email_verified')), 'status': row['status'],
                'idp_issuer': row['idp_issuer'], 'created_at': iso(row.get('created_at'))}

    def _membership_roles(self, tx, user_id, customer_id):
        row = tx.get_customer_membership(customer_id, user_id)
        if not row or row['status'] != 'active':
            return []
        return [row['role']]

    def _assert_customer_admin(self, tx, customer_id, roles):
        if not any(r in CUSTOMER_ADMIN_ROLES for r in (roles or [])):
            raise IdentityError(FORBIDDEN, status=403)

    def _roles_subset(self, requested, allowed):
        allowed = ROLES if 'TenantAdmin' in allowed else allowed
        if not set(requested) <= set(allowed):
            raise IdentityError(FORBIDDEN, status=403)

    def _customer_scope(self, tx, grant, customer_id=None, *, admin=True):
        """Resolve the caller's customer and enforce its customer role. Returns the caller's roles."""
        customer_id = uuid_text(customer_id) if customer_id else grant['customer_id']
        if customer_id != grant['customer_id']:
            raise NotFound('Customer not found.')
        roles = self._membership_roles(tx, grant['subject_id'], customer_id)
        if admin:
            self._assert_customer_admin(tx, customer_id, roles)
        elif not roles:
            raise IdentityError(FORBIDDEN, status=403)
        return customer_id, roles

    def _customer_workspace(self, tx, grant, tenant_id, *, admin=True, lock=False):
        workspace = tx.get_workspace(uuid_text(tenant_id), lock=lock)
        if not workspace or workspace['customer_id'] != grant['customer_id'] or workspace['status'] == 'deleted':
            raise NotFound('Workspace not found.')
        self._customer_scope(tx, grant, admin=admin)
        return workspace

    def _issuer_roles(self, tx, tenant_id, grant):
        membership = tx.get_workspace_membership(tenant_id, grant['subject_id'])
        return list(membership['roles']) if membership else []

    def _customer_workspaces(self, tx, customer_id):
        return [w for w in tx.list_workspaces(None, None, customer_id, 0, 10000) if w['status'] != 'deleted']

    def _revoke_subject_keys(self, tx, customer_id, actor, reason, request_id, *, user_id=None,
                             service_account_id=None, tenant_id=None):
        revoked = []
        for workspace in self._customer_workspaces(tx, customer_id):
            if tenant_id and workspace['tenant_id'] != tenant_id:
                continue
            for row in tx.list_keys(workspace['tenant_id']):
                if row['revoked_at']:
                    continue
                if (user_id and str(row.get('subject_user_id') or '') == user_id) or \
                        (service_account_id and str(row.get('service_account_id') or '') == service_account_id):
                    tx.update_key(row['key_id'], {'revoked_at': self.now(), 'revoked_by': actor['actor'][:120],
                                                  'revoke_reason': reason})
                    self._event(tx, actor, 'revoked', row['tenant_id'], row['key_id'],
                                {'name': row['name'], 'reason': reason}, request_id)
                    revoked.append({'key_id': row['key_id'], 'event': 'revoked'})
        return revoked

    # ----- operator bootstrap and first-owner claim ---------------------------------------------------
    def issue_bootstrap_key(self, customer_id, payload, actor, request_id=None):
        customer_id = uuid_text(customer_id)
        tenant_id = uuid_text(payload.get('tenant_id'), 'Workspace')
        name = text(payload.get('name') or 'Bootstrap onboarding', 'Key name', 80)
        now = self.now()
        with self.store.transaction() as tx:
            customer = tx.get_customer(customer_id, lock=True)
            if not customer or customer['status'] == 'deleted':
                raise NotFound('Customer not found.')
            if customer.get('claim_status', 'claimed') != 'pending':
                raise Conflict('This customer account is already claimed.')
            workspace = tx.get_workspace(tenant_id)
            if not workspace or workspace['customer_id'] != customer_id or workspace['status'] == 'deleted':
                raise NotFound('Workspace not found.')
            from identity.service import key_status
            if any(k.get('purpose') == 'bootstrap' and key_status(k, now) in ('active', 'expiring_soon')
                   for k in tx.list_keys(tenant_id)):
                raise Conflict('An active bootstrap key already exists for this workspace.')
            expires = self._expiry(payload.get('expires_at'), default=now + timedelta(hours=DEFAULT_BOOTSTRAP_HOURS))
            if expires > now + timedelta(hours=MAX_BOOTSTRAP_HOURS, minutes=5):
                raise IdentityError(f'Bootstrap keys can last at most {MAX_BOOTSTRAP_HOURS} hours.')
            grant = {'roles': ['TenantAdmin'], 'all_providers': True, 'allowed_providers': [],
                     'scope_restrictions': None, 'purpose': 'bootstrap', 'subject_type': 'operator'}
            row, secret = self._new_key_row(workspace, name, grant, expires, actor)
            tx.insert_key(row)
            self._event(tx, actor, 'bootstrap_issued', tenant_id, row['key_id'],
                        {'customer_id': customer_id, 'name': name, 'expires_at': iso(expires)}, request_id)
            view = self.key_view(row, workspace)
        return {'key': view, 'secret': secret}

    def claim_customer(self, payload, request_id=None):
        from identity import keys as keyfmt
        presented = payload.get('key')
        if not isinstance(presented, str) or not presented.strip():
            raise IdentityError('Enter a valid onboarding key.')
        idp_issuer = text(payload.get('idp_issuer'), 'Identity issuer', 512)
        idp_subject = text(payload.get('idp_subject'), 'Identity subject', 256)
        display_name = text(payload.get('display_name'), 'Display name', 120)
        email = text(payload.get('email') or None, 'Email', 320, required=False)
        kind, key_id = keyfmt.parse(presented.strip())
        if kind != 'v1':
            return {'valid': False, 'reason': 'unknown'}
        with self.store.transaction() as tx:
            row = self._match(tx, presented.strip(), kind, key_id)
            if row is None or row == 'mismatch' or row.get('purpose') != 'bootstrap':
                return {'valid': False, 'reason': 'unknown'}
            from identity.service import key_status
            now = self.now()
            if key_status(row, now) not in ('active', 'expiring_soon'):
                return {'valid': False, 'reason': 'unknown'}
            workspace = tx.get_workspace(row['tenant_id'])
            customer = tx.get_customer(workspace['customer_id'], lock=True) if workspace else None
            if not workspace or not customer or customer.get('claim_status') != 'pending':
                return {'valid': False, 'reason': 'unknown'}
            existing = tx.get_user_by_idp(idp_issuer, idp_subject)
            if existing and existing['status'] != 'active':
                return {'valid': False, 'reason': 'unknown'}
            user = existing or tx.insert_user({
                'id': str(uuid4()), 'idp_issuer': idp_issuer, 'idp_subject': idp_subject,
                'email': email, 'email_verified': False, 'display_name': display_name, 'status': 'active',
                'last_sign_in_at': now, 'created_at': now, 'created_by': 'claim', 'updated_at': now,
                'updated_by': 'claim', 'version': 1,
            })
            user_id = str(user['id'])
            tx.upsert_customer_membership(customer['id'], user_id, {
                'role': 'CustomerOwner', 'status': 'active', 'updated_at': now, 'updated_by': 'claim',
            })
            tx.upsert_workspace_membership(workspace['tenant_id'], user_id, {
                'roles': list(row['roles']), 'updated_at': now, 'updated_by': 'claim',
            })
            tx.update_customer(customer['id'], customer['version'], {
                'claim_status': 'claimed',
                'membership_policy_version': int(customer.get('membership_policy_version', 1)) + 1,
                'updated_at': now, 'updated_by': 'claim',
            })
            tx.update_key(row['key_id'], {
                'revoked_at': now, 'revoked_by': 'claim', 'revoke_reason': 'Bootstrap consumed',
                'claimed_at': now, 'subject_type': 'user', 'subject_user_id': user_id,
            })
            actor = {'actor': user_id, 'actor_type': 'customer'}
            grant = self._grant_fields({'roles': ['Viewer'], 'all_providers': True}, workspace)
            grant |= {'subject_type': 'user', 'subject_user_id': user_id}
            personal, secret = self._new_key_row(workspace, 'Owner access key', grant,
                                                 now + timedelta(days=DEFAULT_EXPIRY_DAYS), actor)
            tx.insert_key(personal)
            self._event(tx, actor, 'customer_claimed', workspace['tenant_id'], row['key_id'],
                        {'customer_id': customer['id'], 'user_id': user_id}, request_id)
            self._event(tx, actor, 'issued', workspace['tenant_id'], personal['key_id'],
                        {'name': personal['name'], 'subject_user_id': user_id}, request_id)
            self._publish([{'directory': True, 'event': 'directory_changed', 'tenant_id': workspace['tenant_id']},
                           {'key_id': row['key_id'], 'event': 'revoked'}], tx)
        return {'valid': True, 'customer_id': customer['id'], 'tenant_id': workspace['tenant_id'],
                'user': self._user_view(user), 'key': self.key_view(personal, workspace), 'secret': secret}

    def customer_context_from_key(self, presented, ip, caller):
        """Verify a standard key and return the grant for /customer/v1 routes; callers need a customer role."""
        grant = self.verify(presented, ip, caller)
        if not grant.get('valid'):
            raise IdentityError('Invalid workspace access key.', status=401)
        if grant.get('subject_type') != 'user' or not grant.get('customer_roles'):
            raise IdentityError(FORBIDDEN, status=403)
        return grant

    # ----- users --------------------------------------------------------------------------------------
    def list_customer_users(self, customer_id, grant):
        with self.store.transaction() as tx:
            customer_id, _ = self._customer_scope(tx, grant, customer_id, admin=False)
            items = []
            for membership in tx.list_customer_memberships(customer_id):
                user = tx.get_user(str(membership['user_id']))
                if user:
                    items.append({**self._user_view(user), 'customer_role': membership['role'],
                                  'membership_status': membership['status']})
        return {'customer_id': customer_id, 'items': items}

    def invite_customer_user(self, customer_id, payload, grant, request_id=None):
        role = text(payload.get('role') or 'CustomerAdmin', 'Role', 24)
        if role not in ('CustomerAdmin', 'CustomerAuditor'):
            raise IdentityError('Choose CustomerAdmin or CustomerAuditor.')
        idp_issuer = text(payload.get('idp_issuer'), 'Identity issuer', 512)
        idp_subject = text(payload.get('idp_subject'), 'Identity subject', 256)
        display_name = text(payload.get('display_name'), 'Display name', 120)
        email = text(payload.get('email') or None, 'Email', 320, required=False)
        now = self.now()
        with self.store.transaction() as tx:
            customer_id, _ = self._customer_scope(tx, grant, customer_id)
            recent = [e for e in tx.list_events({'customer_id': customer_id, 'tenant_ids': [], 'action': 'user_invited'},
                                                None, MAX_INVITES_PER_DAY + 1)
                      if e['occurred_at'] > now - timedelta(days=1)]
            if len(recent) >= MAX_INVITES_PER_DAY:
                raise IdentityError(f'You can invite up to {MAX_INVITES_PER_DAY} users per day. Try again tomorrow.',
                                    status=429)
            user = tx.get_user_by_idp(idp_issuer, idp_subject)
            if user and tx.get_customer_membership(customer_id, str(user['id'])):
                raise Conflict('This user already belongs to your organization.')
            user = user or tx.insert_user({
                'id': str(uuid4()), 'idp_issuer': idp_issuer, 'idp_subject': idp_subject,
                'email': email, 'email_verified': False, 'display_name': display_name, 'status': 'active',
                'last_sign_in_at': None, 'created_at': now, 'created_by': grant['subject_id'],
                'updated_at': now, 'updated_by': grant['subject_id'], 'version': 1,
            })
            tx.upsert_customer_membership(customer_id, str(user['id']), {
                'role': role, 'status': 'active', 'updated_at': now, 'updated_by': grant['subject_id'],
            })
            self._bump_customer_policy(tx, customer_id)
            self._event(tx, _actor(grant), 'user_invited', None, None,
                        {'customer_id': customer_id, 'user_id': str(user['id']), 'role': role}, request_id)
        return {**self._user_view(user), 'customer_role': role, 'membership_status': 'active'}

    def set_customer_user_status(self, customer_id, user_id, payload, status, grant, request_id=None):
        """Suspend revokes every key issued to the user in this customer; reactivate restores access only."""
        user_id = uuid_text(user_id, 'User')
        reason = text(payload.get('reason') or ('User suspended' if status == 'suspended' else 'User reactivated'),
                      'Reason', 200)
        messages = []
        with self.store.transaction() as tx:
            customer_id, _ = self._customer_scope(tx, grant, customer_id)
            if user_id == grant['subject_id']:
                raise IdentityError("You can't change your own access.", status=403)
            membership = tx.get_customer_membership(customer_id, user_id)
            if not membership:
                raise NotFound('User not found.')
            if membership['role'] == 'CustomerOwner':
                raise IdentityError('Transfer ownership before you suspend the owner.', status=403)
            if membership['status'] == status:
                raise Conflict(f'This user is already {status}.')
            tx.upsert_customer_membership(customer_id, user_id, {
                'role': membership['role'], 'status': status, 'updated_at': self.now(),
                'updated_by': grant['subject_id'],
            })
            actor = _actor(grant)
            if status == 'suspended':
                messages = self._revoke_subject_keys(tx, customer_id, actor, reason, request_id, user_id=user_id)
            self._bump_customer_policy(tx, customer_id)
            self._event(tx, actor, 'user_suspended' if status == 'suspended' else 'user_reactivated', None, None,
                        {'customer_id': customer_id, 'user_id': user_id, 'reason': reason,
                         'revoked_keys': len(messages)}, request_id)
            messages += [{'tenant_id': w['tenant_id'], 'event': 'membership_changed'}
                         for w in self._customer_workspaces(tx, customer_id)]
            self._publish(messages, tx)
        return self.list_customer_users(customer_id, grant)

    def transfer_ownership(self, customer_id, payload, grant, request_id=None):
        target = uuid_text(payload.get('user_id'), 'User')
        now = self.now()
        with self.store.transaction() as tx:
            customer_id, roles = self._customer_scope(tx, grant, customer_id)
            if 'CustomerOwner' not in roles:
                raise IdentityError('Only the owner can transfer ownership.', status=403)
            if target == grant['subject_id']:
                raise IdentityError('Choose another user to become the owner.')
            membership = tx.get_customer_membership(customer_id, target)
            user = tx.get_user(target)
            if not membership or membership['status'] != 'active' or not user or user['status'] != 'active':
                raise IdentityError('Choose an active user in your organization.')
            # Demote first: the database allows one active owner per customer.
            tx.upsert_customer_membership(customer_id, grant['subject_id'], {
                'role': 'CustomerAdmin', 'status': 'active', 'updated_at': now, 'updated_by': grant['subject_id']})
            tx.upsert_customer_membership(customer_id, target, {
                'role': 'CustomerOwner', 'status': 'active', 'updated_at': now, 'updated_by': grant['subject_id']})
            self._bump_customer_policy(tx, customer_id)
            self._event(tx, _actor(grant), 'ownership_transferred', None, None,
                        {'customer_id': customer_id, 'from_user_id': grant['subject_id'], 'to_user_id': target},
                        request_id)
            self._publish([{'tenant_id': w['tenant_id'], 'event': 'membership_changed'}
                           for w in self._customer_workspaces(tx, customer_id)], tx)
        return self.list_customer_users(customer_id, grant)

    # ----- workspace memberships ----------------------------------------------------------------------
    def list_workspace_members(self, tenant_id, grant):
        with self.store.transaction() as tx:
            workspace = self._customer_workspace(tx, grant, tenant_id, admin=False)
            items = []
            for row in tx.list_workspace_memberships(workspace['tenant_id']):
                user = tx.get_user(str(row['user_id']))
                if user:
                    items.append({'user_id': str(user['id']), 'display_name': user['display_name'],
                                  'roles': list(row['roles']), 'version': row['version']})
        return {'tenant_id': workspace['tenant_id'], 'items': items}

    def update_workspace_member(self, tenant_id, user_id, payload, grant, request_id=None):
        """Adds a member when version is 0 and no membership exists; otherwise updates with optimistic locking."""
        user_id = uuid_text(user_id, 'User')
        version = self._version(payload)
        roles = normalize_roles(payload.get('roles'))
        with self.store.transaction() as tx:
            workspace = self._customer_workspace(tx, grant, tenant_id, lock=True)
            tenant_id = workspace['tenant_id']
            self._roles_subset(roles, self._issuer_roles(tx, tenant_id, grant))
            membership = tx.get_customer_membership(workspace['customer_id'], user_id)
            if not membership or membership['status'] != 'active':
                raise IdentityError('Invite this user to your organization first.')
            current = tx.get_workspace_membership(tenant_id, user_id)
            if (current['version'] if current else 0) != version:
                raise StaleVersion()
            tx.upsert_workspace_membership(tenant_id, user_id, {
                'roles': roles, 'updated_at': self.now(), 'updated_by': grant['subject_id'],
            })
            self._bump_customer_policy(tx, workspace['customer_id'])
            self._event(tx, _actor(grant), 'workspace_membership_changed', tenant_id,
                        details={'user_id': user_id, 'roles': roles, 'added': current is None}, request_id=request_id)
            self._publish([{'tenant_id': tenant_id, 'event': 'membership_changed'}], tx)
        return self.list_workspace_members(tenant_id, grant)

    def remove_workspace_member(self, tenant_id, user_id, payload, grant, request_id=None):
        user_id = uuid_text(user_id, 'User')
        with self.store.transaction() as tx:
            workspace = self._customer_workspace(tx, grant, tenant_id, lock=True)
            tenant_id = workspace['tenant_id']
            if user_id == grant['subject_id']:
                raise IdentityError("You can't remove your own access.", status=403)
            current = tx.get_workspace_membership(tenant_id, user_id)
            if not current:
                raise NotFound('Member not found.')
            if current['version'] != self._version(payload):
                raise StaleVersion()
            tx.delete_workspace_membership(tenant_id, user_id)
            actor = _actor(grant)
            messages = self._revoke_subject_keys(tx, workspace['customer_id'], actor, 'Workspace access removed',
                                                 request_id, user_id=user_id, tenant_id=tenant_id)
            self._bump_customer_policy(tx, workspace['customer_id'])
            self._event(tx, actor, 'workspace_membership_removed', tenant_id,
                        details={'user_id': user_id, 'revoked_keys': len(messages)}, request_id=request_id)
            self._publish(messages + [{'tenant_id': tenant_id, 'event': 'membership_changed'}], tx)
        return self.list_workspace_members(tenant_id, grant)

    # ----- service accounts ---------------------------------------------------------------------------
    def _service_account_view(self, row):
        return {'service_account_id': str(row['id']), 'customer_id': str(row['customer_id']), 'name': row['name'],
                'description': row.get('description') or '', 'status': row['status'], 'version': row['version']}

    def list_service_accounts(self, customer_id, grant):
        with self.store.transaction() as tx:
            customer_id, _ = self._customer_scope(tx, grant, customer_id, admin=False)
            return {'items': [self._service_account_view(r) for r in tx.list_service_accounts(customer_id)]}

    def create_service_account(self, customer_id, payload, grant, request_id=None):
        name = text(payload.get('name'), 'Name', 80)
        description = text(payload.get('description') or None, 'Description', 500, required=False)
        now = self.now()
        with self.store.transaction() as tx:
            customer_id, _ = self._customer_scope(tx, grant, customer_id)
            if sum(r['status'] != 'deleted' for r in tx.list_service_accounts(customer_id)) >= MAX_SERVICE_ACCOUNTS:
                raise Conflict(f'Your organization can have at most {MAX_SERVICE_ACCOUNTS} service accounts.')
            row = {'id': str(uuid4()), 'customer_id': customer_id, 'name': name, 'description': description or '',
                   'status': 'active', 'created_at': now, 'created_by': grant['subject_id'],
                   'updated_at': now, 'updated_by': grant['subject_id'], 'version': 1}
            tx.insert_service_account(row)
            self._event(tx, _actor(grant), 'service_account_created', None, None,
                        {'customer_id': customer_id, 'service_account_id': row['id']}, request_id)
        return self._service_account_view(row)

    def update_service_account(self, account_id, payload, grant, request_id=None):
        """Rename, suspend, reactivate, or delete. Suspend and delete revoke the account's keys."""
        account_id = uuid_text(account_id, 'Service account')
        version = self._version(payload)
        fields = {}
        if payload.get('name') is not None:
            fields['name'] = text(payload['name'], 'Name', 80)
        if payload.get('description') is not None:
            fields['description'] = text(payload['description'] or None, 'Description', 500, required=False) or ''
        if payload.get('status') is not None:
            if payload['status'] not in ('active', 'suspended', 'deleted'):
                raise IdentityError('Choose active, suspended, or deleted.')
            fields['status'] = payload['status']
        if not fields:
            raise IdentityError('Include a change.')
        messages = []
        with self.store.transaction() as tx:
            customer_id, _ = self._customer_scope(tx, grant)
            account = tx.get_service_account(account_id)
            if not account or str(account['customer_id']) != customer_id or account['status'] == 'deleted':
                raise NotFound('Service account not found.')
            if account['version'] != version:
                raise StaleVersion()
            row = tx.update_service_account(account_id, version,
                                            dict(fields, updated_at=self.now(), updated_by=grant['subject_id']))
            if row is None:
                raise StaleVersion()
            actor = _actor(grant)
            if fields.get('status') in ('suspended', 'deleted'):
                messages = self._revoke_subject_keys(tx, customer_id, actor, f'Service account {fields["status"]}',
                                                     request_id, service_account_id=account_id)
            self._event(tx, actor, 'service_account_updated', None, None,
                        {'customer_id': customer_id, 'service_account_id': account_id, 'changes': sorted(fields),
                         'revoked_keys': len(messages)}, request_id)
            self._publish(messages, tx)
        return self._service_account_view(row)

    # ----- delegated keys -----------------------------------------------------------------------------
    def list_customer_keys(self, tenant_id, grant):
        with self.store.transaction() as tx:
            workspace = self._customer_workspace(tx, grant, tenant_id, admin=False)
            rows = [r for r in tx.list_keys(workspace['tenant_id']) if r.get('purpose') != 'bootstrap']
            return {'items': self._key_views(tx, rows)}

    def issue_customer_workspace_key(self, tenant_id, payload, grant, request_id=None):
        name = text(payload.get('name'), 'Key name', 80)
        service_account_id = uuid_text(payload.get('service_account_id'), 'Service account') \
            if payload.get('service_account_id') else None
        subject_user_id = uuid_text(payload.get('subject_user_id'), 'User') \
            if payload.get('subject_user_id') else (None if service_account_id else grant['subject_id'])
        if service_account_id and subject_user_id:
            raise IdentityError('Choose a user or a service account, not both.')
        with self.store.transaction() as tx:
            workspace = self._customer_workspace(tx, grant, tenant_id, lock=True)
            tenant_id = workspace['tenant_id']
            if service_account_id:
                account = tx.get_service_account(service_account_id)
                if not account or str(account['customer_id']) != workspace['customer_id'] or account['status'] != 'active':
                    raise NotFound('Service account not found.')
            else:
                membership = tx.get_customer_membership(workspace['customer_id'], subject_user_id)
                if not membership or membership['status'] != 'active' or \
                        not tx.get_workspace_membership(tenant_id, subject_user_id):
                    raise IdentityError('Assign workspace access before issuing a key for this user.')
            self._assert_key_issuance_allowed(tx, workspace)
            issued = self._grant_fields(payload, workspace)
            self._roles_subset(issued['roles'], self._issuer_roles(tx, tenant_id, grant))
            if subject_user_id:
                self._roles_subset(issued['roles'], tx.get_workspace_membership(tenant_id, subject_user_id)['roles'])
            expires = self._expiry(payload.get('expires_at'))
            if len(self._open_keys(tx, tenant_id)) >= MAX_ACTIVE_KEYS:
                raise Conflict(f'A workspace can have at most {MAX_ACTIVE_KEYS} active keys. Revoke a key first.')
            issued |= ({'subject_type': 'service_account', 'service_account_id': service_account_id}
                       if service_account_id else {'subject_type': 'user', 'subject_user_id': subject_user_id})
            row, secret = self._new_key_row(workspace, name, issued, expires, _actor(grant))
            tx.insert_key(row)
            self._event(tx, _actor(grant), 'issued', tenant_id, row['key_id'],
                        {'name': name, 'roles': row['roles'], 'subject_type': row['subject_type'],
                         'subject_id': service_account_id or subject_user_id,
                         'scope_restrictions': row['scope_restrictions']}, request_id)
            view = self.key_view(row, workspace)
        return {'key': view, 'secret': secret}

    def _customer_key(self, tx, key_id, grant):
        row = self._key_row(tx, key_id, lock=True)
        workspace = self._customer_workspace(tx, grant, row['tenant_id'])
        if row.get('subject_type') not in ('user', 'service_account'):
            raise IdentityError('Your platform operator manages this key.', status=403)
        return row, workspace

    def revoke_customer_key(self, key_id, payload, grant, request_id=None):
        with self.store.transaction() as tx:
            self._customer_key(tx, key_id, grant)
        reason = payload.get('reason') or 'Revoked by your organization administrator'
        return self.revoke_key(key_id, {'reason': reason}, _actor(grant), request_id)

    def rotate_customer_key(self, key_id, payload, grant, request_id=None):
        with self.store.transaction() as tx:
            row, workspace = self._customer_key(tx, key_id, grant)
            self._roles_subset(row['roles'], self._issuer_roles(tx, workspace['tenant_id'], grant))
        allowed = {k: payload[k] for k in ('overlap_hours', 'expires_at') if k in payload}
        return self.rotate_key(key_id, allowed, _actor(grant), request_id)

    # ----- audit and export ---------------------------------------------------------------------------
    def customer_audit(self, grant, before=None, limit=50, action=None):
        with self.store.transaction() as tx:
            customer_id, _ = self._customer_scope(tx, grant, admin=False)
        return self.audit({'customer_id': customer_id, 'action': action}, before, limit)

    def export_customer_access(self, grant):
        """CSV of memberships and key metadata. Never includes secrets or digests."""
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(['record', 'workspace_id', 'workspace_name', 'subject_type', 'subject_id', 'display_name',
                         'role_or_roles', 'status', 'key_id', 'key_name', 'expires_at', 'last_used_at'])
        with self.store.transaction() as tx:
            customer_id, _ = self._customer_scope(tx, grant, admin=False)
            names = {}
            for membership in tx.list_customer_memberships(customer_id):
                user = tx.get_user(str(membership['user_id']))
                names[str(membership['user_id'])] = user['display_name'] if user else ''
                writer.writerow(['customer_membership', '', '', 'user', str(membership['user_id']),
                                 names[str(membership['user_id'])], membership['role'], membership['status'],
                                 '', '', '', ''])
            for account in tx.list_service_accounts(customer_id):
                names[str(account['id'])] = account['name']
            for workspace in self._customer_workspaces(tx, customer_id):
                for row in tx.list_workspace_memberships(workspace['tenant_id']):
                    writer.writerow(['workspace_membership', workspace['tenant_id'], workspace['name'], 'user',
                                     str(row['user_id']), names.get(str(row['user_id']), ''), ' '.join(row['roles']),
                                     'active', '', '', '', ''])
                for view in self._key_views(tx, tx.list_keys(workspace['tenant_id'])):
                    if view['purpose'] == 'bootstrap':
                        continue
                    writer.writerow(['key', workspace['tenant_id'], workspace['name'], view['subject_type'],
                                     view['subject_id'] or '', names.get(view['subject_id'] or '', ''),
                                     ' '.join(view['roles']), view['status'], view['key_id'], view['name'],
                                     view['expires_at'] or '', view['last_used_at'] or ''])
        return out.getvalue()

    def _bump_customer_policy(self, tx, customer_id):
        customer = tx.get_customer(customer_id, lock=True)
        if not customer:
            return
        tx.update_customer(customer_id, customer['version'], {
            'membership_policy_version': int(customer.get('membership_policy_version', 1)) + 1,
            'updated_at': self.now(), 'updated_by': 'customer',
        })
