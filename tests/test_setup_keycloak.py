import json
from datetime import datetime,timedelta,timezone

import pytest

from app.entitlements import TIER_LIMITS,PlanTier
from scripts.setup_keycloak import generate


def test_private_realm_and_connection_generation(tmp_path):
    record=dict(schema_version=1,enabled=True,expires_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),
                plan=dict(code='STARTER',entitlements=TIER_LIMITS[PlanTier.STARTER].model_dump()))
    directory=tmp_path/'private'
    binding=generate(directory,'https://identity.example','11111111-1111-4111-8111-111111111111',record,'cert.pem','key.pem')
    assert directory.stat().st_mode&0o777==0o700
    assert (directory/'keycloak.env').stat().st_mode&0o777==0o600
    assert (directory/'cloudsaver.env').stat().st_mode&0o777==0o600
    realm=json.loads((directory/'import/realm.json').read_text())
    chunks=realm['groups'][0]['attributes']['cloudsaver_license_v1']
    assert max(map(len,chunks))<=245
    assert json.loads(''.join(c[5:] for c in sorted(chunks)))==record
    assert realm['clients'][0]['id']==binding.client_uuid
    assert realm['clients'][1]['serviceAccountsEnabled']
    assert not realm['clients'][1]['directAccessGrantsEnabled']
    assert 'realm-admin' not in realm['users'][0]['clientRoles']['realm-management']
    with pytest.raises(FileExistsError):generate(directory,'https://identity.example',binding.tenant_id,record,'cert','key')
