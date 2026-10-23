import {randomUUID} from 'node:crypto';
import {serverConfig} from './config';
import type {OperatorProfile} from './session';

export const UPSTREAM_TIMEOUT_MS = 15_000;

export class IdentityUnavailableError extends Error {}

export function identityHeaders(credential: string, extra: Record<string, string> = {}) {
  const config = serverConfig();
  return {
    'X-Service-Token': config.identityToken,
    Authorization: `Bearer ${credential}`,
    'X-Request-ID': randomUUID(),
    Accept: 'application/json',
    ...extra,
  };
}

/** Calls identity-service GET /admin/v1/session. Returns null when the credential is rejected. */
export async function fetchOperatorProfile(credential: string): Promise<{profile: OperatorProfile | null; status: number; detail?: string}> {
  let response: Response;
  try {
    response = await fetch(`${serverConfig().identityUrl}/admin/v1/session`, {
      headers: identityHeaders(credential), cache: 'no-store', signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch {
    throw new IdentityUnavailableError('identity-service unreachable');
  }
  if (response.status >= 500) throw new IdentityUnavailableError(`identity-service returned ${response.status}`);
  const body = await response.json().catch(() => null) as Record<string, unknown> | null;
  if (!response.ok || !body) {
    return {profile: null, status: response.status, detail: typeof body?.detail === 'string' ? body.detail : undefined};
  }
  return {
    status: response.status,
    profile: {
      actor: String(body.actor ?? ''),
      display_name: String(body.display_name ?? body.actor ?? ''),
      roles: Array.isArray(body.roles) ? body.roles.map(String) : [],
      auth_mode: body.auth_mode === 'operator_key' ? 'operator_key' : 'entra',
      provider_scoped_keys: body.provider_scoped_keys === true,
      environment: String(body.environment ?? serverConfig().environment),
      key_prefix: body.key_prefix === 'cs_live_' ? 'cs_live_' : 'cs_test_',
      billing_enabled: body.billing_enabled === true,
      billing_provider: body.billing_provider === 'stripe' ? 'stripe' : 'manual',
    },
  };
}
