import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import SecretStr

from app import keyvault as kv


TENANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
CLIENT = "33333333-3333-3333-3333-333333333333"
VAULT = "https://cloudsaver-tests.vault.azure.net"


def secret(tenant=TENANT, value="private-rotating-secret"):
    return json.dumps(dict(azure_tenant_id=tenant, client_id=CLIENT,
                           auth_type="client_secret", client_secret=value))


class FakeClient:
    def __init__(self, value=None):
        self.value = value if value is not None else secret()
        self.names = []
        self.closed = 0

    def get_secret(self, name, **kwargs):
        self.names.append(name)
        if isinstance(self.value, Exception):
            raise self.value
        return SimpleNamespace(value=self.value)

    def close(self):
        self.closed += 1


@pytest.fixture(autouse=True)
def clear_singleton(monkeypatch):
    kv.close_providers()
    for name in ("CLOUDSAVER_CREDENTIAL_PROVIDER", "AZURE_KEYVAULT_URL", "AZURE_KEYVAULT_AUTH",
                 "AZURE_KEYVAULT_MANAGED_IDENTITY_CLIENT_ID", "AZURE_KEYVAULT_CACHE_TTL_SECONDS",
                 "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    yield
    kv.close_providers()


def provider(client, **kwargs):
    return kv.KeyVaultCredentialProvider(VAULT, secret_client=client,
                                         credential_factory=lambda material: material, **kwargs)


def test_derived_tenant_secret_name_and_protected_cache():
    client = FakeClient()
    p = provider(client)
    material = p.credential(TENANT)
    assert client.names == ["tenant-11111111111111111111111111111111-cred"]
    assert isinstance(material.client_secret, SecretStr)
    assert "private-rotating-secret" not in repr(material)
    assert TENANT not in repr(material)
    assert "private-rotating-secret" not in repr(p._cache)


def test_expiry_refreshes_latest_secret_rotation():
    clock = [0.0]
    client = FakeClient(secret(value="first"))
    p = provider(client, ttl_seconds=5, clock=lambda: clock[0])
    assert p.credential(TENANT).client_secret.get_secret_value() == "first"
    client.value = secret(value="second")
    clock[0] = 4.9
    assert p.credential(TENANT).client_secret.get_secret_value() == "first"
    assert len(client.names) == 1
    clock[0] = 5.0
    assert p.credential(TENANT).client_secret.get_secret_value() == "second"
    assert len(client.names) == 2


def test_ttl_zero_disables_caching():
    client = FakeClient()
    p = provider(client, ttl_seconds=0)
    p.credential(TENANT)
    p.credential(TENANT)
    assert len(client.names) == 2
    assert not p._cache


def test_bounded_lru_cache_and_eviction():
    client = FakeClient()
    p = provider(client, max_entries=2)
    for number in (1, 2, 1, 3):
        tenant = str(UUID(int=number))
        client.value = secret(tenant=tenant)
        p.credential(tenant)
    assert len(client.names) == 3
    assert list(p._cache) == [str(UUID(int=1)), str(UUID(int=3))]
    client.value = secret(tenant=str(UUID(int=2)))
    p.credential(str(UUID(int=2)))
    assert len(client.names) == 4


@pytest.mark.parametrize("value", [secret(tenant=OTHER), "bad JSON PRIVATE", "{}", "[]",
    json.dumps(dict(azure_tenant_id=TENANT, client_id="not-a-uuid", auth_type="client_secret", client_secret="PRIVATE")),
    json.dumps(dict(azure_tenant_id=TENANT, client_id=CLIENT, auth_type="client_secret", client_secret="")),
    '{"azure_tenant_id":"' + TENANT + '","azure_tenant_id":"' + OTHER + '"}',
    json.dumps(dict(azure_tenant_id=TENANT, client_id=CLIENT, auth_type="certificate", certificate_pem="PRIVATE")),
])
def test_malformed_or_mismatched_secret_fails_without_sensitive_exception(value):
    p = provider(FakeClient(value))
    with pytest.raises(kv.CredentialError) as exc:
        p.credential(TENANT)
    assert "PRIVATE" not in str(exc.value)
    assert TENANT not in str(exc.value)
    assert not p._cache


def test_expired_cache_does_not_hide_vault_failure():
    clock = [0]
    client = FakeClient()
    p = provider(client, ttl_seconds=1, clock=lambda: clock[0])
    p.credential(TENANT)
    client.value = RuntimeError("PRIVATE upstream body")
    clock[0] = 1
    with pytest.raises(kv.CredentialError) as exc:
        p.credential(TENANT)
    assert "PRIVATE" not in str(exc.value)
    assert not p._cache


def test_keyvault_never_falls_back_to_valid_env(monkeypatch):
    monkeypatch.setenv("CLOUDSAVER_CREDENTIAL_PROVIDER", "keyvault")
    monkeypatch.setenv("AZURE_CLIENT_ID", CLIENT)
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "env-is-present")
    p = provider(FakeClient(RuntimeError("vault unavailable")))
    monkeypatch.setattr(kv, "_keyvault_provider", lambda: p)
    monkeypatch.setattr(kv, "_sdk_credential", lambda _: pytest.fail("env fallback used"))
    with pytest.raises(kv.CredentialError):
        kv.customer_credential(TENANT)


@pytest.mark.parametrize("url", ["", "http://cloudsaver.vault.azure.net", "https://vault.azure.net.evil.test",
    "https://cloudsaver.vault.azure.net.evil.test", "https://user:secret@cloudsaver.vault.azure.net",
    "https://cloudsaver.vault.azure.net:443", "https://cloudsaver.vault.azure.net/secrets/x",
    "https://cloudsaver.vault.azure.net?x=1", "https://127.0.0.1", "https://cloudsaver.vault.azure.cn"])
def test_explicit_https_public_vault_url_required(url):
    with pytest.raises(kv.CredentialError):
        kv.KeyVaultCredentialProvider(url)


@pytest.mark.parametrize("ttl", [-1, 901, "30", True])
def test_cache_ttl_bounds(ttl):
    with pytest.raises(kv.CredentialError):
        provider(FakeClient(), ttl_seconds=ttl)


def test_env_requires_valid_explicit_credentials(monkeypatch):
    with pytest.raises(kv.CredentialError):
        kv.customer_credential(TENANT)
    monkeypatch.setenv("AZURE_CLIENT_ID", CLIENT)
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "configured")
    captured = []
    monkeypatch.setattr(kv, "_sdk_credential", lambda m: captured.append(m) or "credential")
    assert kv.customer_credential(TENANT) == "credential"
    assert str(captured[0].azure_tenant_id) == TENANT


def test_unknown_provider_rejected(monkeypatch):
    monkeypatch.setenv("CLOUDSAVER_CREDENTIAL_PROVIDER", "automatic")
    with pytest.raises(kv.CredentialError):
        kv.customer_credential(TENANT)


def test_certificate_constructor_uses_memory_only(monkeypatch):
    import azure.identity
    data = dict(azure_tenant_id=TENANT, client_id=CLIENT, auth_type="certificate",
                certificate_pem="-----BEGIN CERTIFICATE-----\nCERT\n-----END CERTIFICATE-----",
                private_key_pem="-----BEGIN PRIVATE KEY-----\nKEY\n-----END PRIVATE KEY-----")
    material = kv.parse_material(json.dumps(data), TENANT)
    captured = {}
    monkeypatch.setattr(azure.identity, "CertificateCredential", lambda **kw: captured.update(kw) or "credential")
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: pytest.fail("certificate written to disk"))
    assert kv._sdk_credential(material) == "credential"
    assert b"BEGIN PRIVATE KEY" in captured["certificate_data"]
    assert b"BEGIN CERTIFICATE" in captured["certificate_data"]
    assert "certificate_path" not in captured
    assert captured["tenant_id"] == TENANT


def test_client_secret_constructor(monkeypatch):
    import azure.identity
    captured = {}
    monkeypatch.setattr(azure.identity, "ClientSecretCredential", lambda **kw: captured.update(kw) or "credential")
    assert kv._sdk_credential(kv.parse_material(secret(), TENANT)) == "credential"
    assert captured["client_secret"] == "private-rotating-secret"
    assert captured["tenant_id"] == TENANT


def test_client_laziness_managed_identity_and_ownership(monkeypatch):
    import azure.identity
    import azure.keyvault.secrets
    client = FakeClient()
    identity = FakeClient()
    calls = []
    monkeypatch.setattr(azure.identity, "ManagedIdentityCredential", lambda **kw: calls.append(kw) or identity)
    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", lambda **kw: pytest.fail("default identity fallback"))
    monkeypatch.setattr(azure.keyvault.secrets, "SecretClient", lambda **kw: client)
    p = kv.KeyVaultCredentialProvider(VAULT, managed_identity_client_id=CLIENT,
                                      credential_factory=lambda m: m)
    assert calls == []
    p.credential(TENANT)
    assert calls == [{"client_id": CLIENT}]
    p.close()
    p.close()
    assert client.closed == identity.closed == 1
    with pytest.raises(kv.CredentialError):
        p.credential(TENANT)


def test_default_credential_is_only_explicit_and_never_interactive(monkeypatch):
    import azure.identity
    import azure.keyvault.secrets
    calls = []
    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", lambda **kw: calls.append(kw) or FakeClient())
    monkeypatch.setattr(azure.keyvault.secrets, "SecretClient", lambda **kw: FakeClient())
    p = kv.KeyVaultCredentialProvider(VAULT, auth="default", credential_factory=lambda m: m)
    p.credential(TENANT)
    assert calls == [{"exclude_interactive_browser_credential": True, "exclude_broker_credential": True}]
    p.close()


def test_clear_and_injected_client_ownership():
    client = FakeClient()
    p = provider(client)
    p.credential(TENANT)
    p.clear()
    assert not p._cache
    p.credential(TENANT)
    p.close()
    assert client.closed == 0
    p = provider(client, own_client=True)
    p.close()
    assert client.closed == 1


def test_factory_failure_invalidates_material_and_is_sanitized():
    p = kv.KeyVaultCredentialProvider(VAULT, secret_client=FakeClient(),
        credential_factory=lambda _: (_ for _ in ()).throw(ValueError("PRIVATE cert bytes")))
    with pytest.raises(kv.CredentialError) as exc:
        p.credential(TENANT)
    assert "PRIVATE" not in str(exc.value)
    assert not p._cache


def test_concurrent_cache_reads_fetch_once():
    from concurrent.futures import ThreadPoolExecutor

    client = FakeClient()
    p = provider(client)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: p.credential(TENANT), range(32)))
    assert len(results) == 32
    assert len(client.names) == 1


def test_real_sdk_accepts_certificate_bytes_without_files_or_network(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    import azure.identity

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ephemeral-test")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
            .sign(key, hashes.SHA256()))
    material = kv.CredentialMaterial(
        azure_tenant_id=TENANT, client_id=CLIENT, auth_type="certificate",
        certificate_pem=SecretStr(cert.public_bytes(serialization.Encoding.PEM).decode()),
        private_key_pem=SecretStr(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()))
    monkeypatch.setattr("builtins.open", lambda *a, **kw: pytest.fail("certificate file access"))
    monkeypatch.setattr("socket.socket", lambda *a, **kw: pytest.fail("network access"))
    credential = kv._sdk_credential(material)
    assert isinstance(credential, azure.identity.CertificateCredential)
    credential.close()
