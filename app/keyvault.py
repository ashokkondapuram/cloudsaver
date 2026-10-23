"""Explicit, fail-closed customer credential sources.

Vault secret names are derived only from the server-owned tenant identity. No
network clients are created until a live scan requests credentials. Secret
material is held in a bounded process-local cache, never written to disk.
"""
from __future__ import annotations

from collections import OrderedDict
import json
import os
import re
import threading
import time
from typing import Callable, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class CredentialError(RuntimeError):
    """Sanitized configuration or credential-provider failure."""


class CredentialMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    azure_tenant_id: UUID = Field(repr=False)
    client_id: UUID = Field(repr=False)
    auth_type: Literal["client_secret", "certificate"]
    client_secret: SecretStr | None = None
    certificate_pem: SecretStr | None = None
    private_key_pem: SecretStr | None = None

    @model_validator(mode="after")
    def validate_material(self):
        if self.auth_type == "client_secret":
            if (self.client_secret is None or not self.client_secret.get_secret_value().strip()
                    or self.certificate_pem is not None or self.private_key_pem is not None):
                raise ValueError("Invalid client-secret credential material.")
        else:
            if (self.client_secret is not None or self.certificate_pem is None
                    or self.private_key_pem is None):
                raise ValueError("Invalid certificate credential material.")
            cert = self.certificate_pem.get_secret_value()
            key = self.private_key_pem.get_secret_value()
            if ("-----BEGIN CERTIFICATE-----" not in cert
                    or not any(f"-----BEGIN {kind}PRIVATE KEY-----" in key
                               for kind in ("", "RSA "))):
                raise ValueError("Invalid PEM credential material.")
        return self


def _uuid(value) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise CredentialError("Credential identity configuration is invalid.") from None


def validate_vault_url(url: str) -> str:
    """Only public Azure Key Vault HTTPS endpoints; reject alternate hosts/paths."""
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.username or parts.password or parts.port
                or parts.query or parts.fragment or parts.path not in ("", "/")
                or not re.fullmatch(r"[a-z][a-z0-9-]{1,22}[a-z0-9]\.vault\.azure\.net",
                                    parts.hostname or "")):
            raise ValueError
        return f"https://{parts.hostname}"
    except (ValueError, TypeError, AttributeError):
        raise CredentialError("An explicit public Azure HTTPS Key Vault URL is required.") from None


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate secret field.")
        result[key] = value
    return result


def parse_material(value: str, tenant_id: str) -> CredentialMaterial:
    try:
        if not isinstance(value, str) or not value or len(value) > 65536:
            raise ValueError
        material = CredentialMaterial.model_validate(json.loads(value, object_pairs_hook=_unique_keys))
        if str(material.azure_tenant_id) != tenant_id:
            raise ValueError
        return material
    except Exception:
        # Do not attach validation errors or their potentially sensitive inputs.
        raise CredentialError("The customer credential secret is invalid or does not match its tenant.") from None


def _sdk_credential(material: CredentialMaterial):
    """Create a separately owned credential; the caller closes it after the scan."""
    from azure.identity import CertificateCredential, ClientSecretCredential

    common = dict(tenant_id=str(material.azure_tenant_id), client_id=str(material.client_id),
                  retry_total=3, connection_timeout=10, read_timeout=45, logging_enable=False)
    if material.auth_type == "client_secret":
        return ClientSecretCredential(client_secret=material.client_secret.get_secret_value(), **common)
    certificate_data = (material.private_key_pem.get_secret_value().strip() + "\n"
                        + material.certificate_pem.get_secret_value().strip() + "\n").encode("utf-8")
    return CertificateCredential(certificate_data=certificate_data, **common)


class KeyVaultCredentialProvider:
    """Thread-safe latest-version reads with TTL and LRU eviction.

    Injected clients remain caller-owned unless ``own_client=True``. Lazy Azure
    clients and their managed identity credentials are always provider-owned.
    A fetch error never returns stale cached material and never falls back to env.
    """

    def __init__(self, vault_url: str, *, ttl_seconds: int = 300, max_entries: int = 128,
                 auth: str = "managed_identity", managed_identity_client_id: str | None = None,
                 secret_client=None, own_client: bool = False,
                 clock: Callable[[], float] = time.monotonic,
                 credential_factory: Callable = _sdk_credential):
        self.vault_url = validate_vault_url(vault_url)
        if type(ttl_seconds) is not int or not 0 <= ttl_seconds <= 900:
            raise CredentialError("Key Vault cache TTL must be an integer from 0 to 900 seconds.")
        if type(max_entries) is not int or not 1 <= max_entries <= 128:
            raise CredentialError("Key Vault cache size must be between 1 and 128 tenants.")
        if auth not in ("managed_identity", "default"):
            raise CredentialError("Key Vault authentication must be managed_identity or explicit default.")
        self.auth = auth
        self.managed_identity_client_id = (_uuid(managed_identity_client_id)
                                           if managed_identity_client_id else None)
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._client = secret_client
        self._owns_client = own_client
        self._identity = None
        self._clock = clock
        self._credential_factory = credential_factory
        self._cache: OrderedDict[str, tuple[float, CredentialMaterial]] = OrderedDict()
        self._lock = threading.RLock()
        self._closed = False

    def _ensure_client(self):
        if self._closed:
            raise CredentialError("The credential provider has been closed.")
        if self._client is None:
            from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
            from azure.keyvault.secrets import SecretClient

            identity = None
            try:
                if self.auth == "default":
                    identity = DefaultAzureCredential(exclude_interactive_browser_credential=True,
                                                       exclude_broker_credential=True)
                else:
                    options = ({"client_id": self.managed_identity_client_id}
                               if self.managed_identity_client_id else {})
                    identity = ManagedIdentityCredential(**options)
                client = SecretClient(vault_url=self.vault_url, credential=identity,
                                      retry_total=3, connection_timeout=10, read_timeout=30,
                                      logging_enable=False)
            except Exception:
                if identity is not None:
                    identity.close()
                raise CredentialError("The credential provider could not initialize.") from None
            self._identity = identity
            self._client = client
            self._owns_client = True
        return self._client

    def credential(self, tenant_id: str):
        tenant_id = _uuid(tenant_id)
        with self._lock:
            if self._closed:
                raise CredentialError("The credential provider has been closed.")
            now = self._clock()
            entry = self._cache.pop(tenant_id, None)
            if entry is not None and entry[0] > now:
                material = entry[1]
                self._cache[tenant_id] = entry
            else:
                try:
                    # No version argument means the latest secret version on refresh.
                    value = self._ensure_client().get_secret(
                        "tenant-" + UUID(tenant_id).hex + "-cred", logging_enable=False).value
                    material = parse_material(value, tenant_id)
                except Exception:
                    raise CredentialError("The customer credential could not be loaded from Key Vault.") from None
                if self.ttl_seconds:
                    self._cache[tenant_id] = (self._clock() + self.ttl_seconds, material)
                    while len(self._cache) > self.max_entries:
                        self._cache.popitem(last=False)
            try:
                return self._credential_factory(material)
            except Exception:
                # Invalidate bad cached PEM or otherwise unusable credentials.
                self._cache.pop(tenant_id, None)
                raise CredentialError("The customer credential could not be initialized.") from None

    def clear(self):
        with self._lock:
            self._cache.clear()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._cache.clear()
            self._closed = True
            # Always release identity even if closing the HTTP client fails.
            try:
                if self._client is not None and self._owns_client:
                    self._client.close()
            finally:
                if self._identity is not None:
                    self._identity.close()
                self._client = self._identity = None


_provider_lock = threading.RLock()
_provider: KeyVaultCredentialProvider | None = None
_provider_config: tuple | None = None


def _keyvault_provider() -> KeyVaultCredentialProvider:
    global _provider, _provider_config
    vault_url = validate_vault_url(os.getenv("AZURE_KEYVAULT_URL", ""))
    auth = os.getenv("AZURE_KEYVAULT_AUTH", "managed_identity")
    managed_id = os.getenv("AZURE_KEYVAULT_MANAGED_IDENTITY_CLIENT_ID") or None
    try:
        ttl = int(os.getenv("AZURE_KEYVAULT_CACHE_TTL_SECONDS", "300"))
    except ValueError:
        raise CredentialError("Key Vault cache TTL must be an integer from 0 to 900 seconds.") from None
    config = (vault_url, auth, managed_id, ttl)
    with _provider_lock:
        if _provider is None or config != _provider_config:
            replacement = KeyVaultCredentialProvider(vault_url, ttl_seconds=ttl, auth=auth,
                                                     managed_identity_client_id=managed_id)
            if _provider is not None:
                _provider.close()
            _provider, _provider_config = replacement, config
        return _provider


def customer_credential(tenant_id: str):
    """Select one explicit provider. Key Vault failures never use env credentials."""
    tenant_id = _uuid(tenant_id)
    provider = os.getenv("CLOUDSAVER_CREDENTIAL_PROVIDER", "env")
    if provider == "keyvault":
        # Keep singleton replacement/close from racing a secret fetch.
        with _provider_lock:
            return _keyvault_provider().credential(tenant_id)
    if provider != "env":
        raise CredentialError("CLOUDSAVER_CREDENTIAL_PROVIDER must be env or keyvault.")
    try:
        material = CredentialMaterial(azure_tenant_id=tenant_id,
                                      client_id=_uuid(os.getenv("AZURE_CLIENT_ID", "")),
                                      auth_type="client_secret",
                                      client_secret=SecretStr(os.getenv("AZURE_CLIENT_SECRET", "")))
        return _sdk_credential(material)
    except Exception:
        raise CredentialError("Environment Azure credentials are missing or invalid.") from None


def clear_provider_cache():
    with _provider_lock:
        if _provider is not None:
            _provider.clear()


def close_providers():
    global _provider, _provider_config
    with _provider_lock:
        try:
            if _provider is not None:
                _provider.close()
        finally:
            _provider = _provider_config = None
