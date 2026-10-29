#!/usr/bin/env python3
"""Generate a private Keycloak realm and CloudSaver connection config; no remote writes."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit
from uuid import UUID, uuid4


def generate(directory, public_url, tenant_id, license_record, cert, key):
    from app.keycloak import Binding
    tenant_id = str(UUID(tenant_id))
    parsed = urlsplit(public_url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError('Public URL must be an HTTPS origin')
    if set(license_record) != {'schema_version','enabled','expires_at','plan'} or type(license_record.get('schema_version')) is not int or license_record['schema_version'] != 1 or license_record.get('enabled') is not True:
        raise ValueError('Supply an explicitly enabled schema-version 1 license')
    expires = datetime.fromisoformat(license_record['expires_at'].replace('Z', '+00:00'))
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise ValueError('License must have a future timezone-aware expiry')
    from app.entitlements import normalize_plan
    if normalize_plan(license_record['plan']) is None:
        raise ValueError('License plan is required')
    directory = Path(directory).resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(directory, 0o700)
    imports = directory / 'import'
    imports.mkdir(mode=0o755)
    client_uuid, group_id = str(uuid4()), str(uuid4())
    realm_name = 'cloudsaver-' + tenant_id
    verifier_secret = secrets.token_urlsafe(48)
    binding = Binding(tenant_id=tenant_id, issuer=public_url.rstrip('/')+'/realms/'+realm_name,
                      audience='cloudsaver-api', client_id='cloudsaver-verifier', client_uuid=client_uuid,
                      secret_env='CLOUDSAVER_KEYCLOAK_SECRET_PRIMARY', group_id=group_id,
                      authorized_parties=['cloudsaver-console'])
    mapper = lambda name, kind, config: dict(name=name, protocol='openid-connect', protocolMapper=kind, config=config)
    license_json=json.dumps(license_record,separators=(',',':'))
    if len(license_json)>10000:
        raise ValueError('License exceeds the supported size')
    license_chunks=[f'{i//240:04d}:'+license_json[i:i+240] for i in range(0,len(license_json),240)]
    realm = dict(realm=realm_name, enabled=True, sslRequired='all', accessTokenLifespan=300,
                 registrationAllowed=False, resetPasswordAllowed=True,
                 roles={'client': {'cloudsaver-api': [{'name': role} for role in ('Viewer','BillingAdmin','TenantAdmin')]}},
                 groups=[dict(id=group_id, name='licensed-workspace', attributes={'cloudsaver_license_v1':license_chunks})],
                 clients=[dict(id=client_uuid, clientId='cloudsaver-api', enabled=True, bearerOnly=True),
                          dict(clientId='cloudsaver-verifier', enabled=True, publicClient=False, secret=verifier_secret,
                               serviceAccountsEnabled=True, standardFlowEnabled=False, directAccessGrantsEnabled=False),
                          dict(clientId='cloudsaver-console', enabled=True, publicClient=True,
                               standardFlowEnabled=True, directAccessGrantsEnabled=False,
                               redirectUris=['http://127.0.0.1:8765/callback'],
                               attributes={'pkce.code.challenge.method':'S256'},
                               protocolMappers=[
                                   mapper('workspace','oidc-hardcoded-claim-mapper',{'claim.name':'cloudsaver_tenant_id','claim.value':tenant_id,'jsonType.label':'String','access.token.claim':'true','id.token.claim':'false'}),
                                   mapper('api-audience','oidc-audience-mapper',{'included.client.audience':'cloudsaver-api','access.token.claim':'true','id.token.claim':'false'})])],
                 users=[dict(username='service-account-cloudsaver-verifier', enabled=True,
                             serviceAccountClientId='cloudsaver-verifier',
                             clientRoles={'realm-management':['view-users','query-users','view-clients','query-groups']})])
    def write(path, content, mode=0o600):
        fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, mode)
        with os.fdopen(fd, 'w') as handle:
            handle.write(content)
    # Import must be readable by the container UID; the parent remains owner-only.
    write(imports/'realm.json',json.dumps(realm,indent=2)+'\n',0o644)
    values = dict(KEYCLOAK_DB_PASSWORD=secrets.token_urlsafe(48),KEYCLOAK_ADMIN_PASSWORD=secrets.token_urlsafe(48),
                  KEYCLOAK_PUBLIC_URL=public_url.rstrip('/'),KEYCLOAK_IMPORT_DIR=str(imports),
                  KEYCLOAK_TLS_CERT=str(Path(cert).resolve()),KEYCLOAK_TLS_KEY=str(Path(key).resolve()))
    if any('\n' in v or "'" in v for v in values.values()):
        raise ValueError('Invalid configuration path')
    write(directory/'keycloak.env',''.join(f"{k}='{v}'\n" for k,v in values.items()))
    write(directory/'cloudsaver.env', "CLOUDSAVER_AUTH_MODE=keycloak\nCLOUDSAVER_DIRECTORY_MODE=registry\n"+
          "CLOUDSAVER_KEY_VERIFIER=local\nCLOUDSAVER_KEYCLOAK_BINDINGS='"+json.dumps([binding.model_dump()])+"'\n"+
          'CLOUDSAVER_KEYCLOAK_SECRET_PRIMARY='+verifier_secret+'\n')
    return binding


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('directory','public-url','tenant-id','license-file','tls-cert','tls-key'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    for path in (args.tls_cert,args.tls_key,args.license_file):
        if not Path(path).is_file():
            parser.error('TLS certificate, TLS key and license files must already exist')
    binding=generate(args.directory,args.public_url,args.tenant_id,json.loads(Path(args.license_file).read_text()),args.tls_cert,args.tls_key)
    print('Private configuration generated. Realm: '+binding.issuer)
    print('No deployment or authentication cutover has occurred.')

if __name__=='__main__':
    main()
