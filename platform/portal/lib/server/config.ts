export type AuthMode = 'entra' | 'operator_key';

const warned = new Set<string>();

/** Reads a PLATFORM_* variable, accepting the 1.0.x CLOUDSAVER_* names with a one-time notice. Never logs values. */
function readEnv(name: string, legacy: string[]): string {
  const env = process.env;
  if (env[name]) return env[name] as string;
  for (const old of legacy) {
    if (!env[old]) continue;
    if (!warned.has(old)) {
      warned.add(old);
      console.warn(`platform-portal: ${old} is deprecated and will be removed in platform 1.1.0. Use ${name} instead.`);
    }
    return env[old] as string;
  }
  return '';
}

export function serverConfig() {
  const env = process.env;
  const publicUrl = (env.PORTAL_PUBLIC_URL || 'http://127.0.0.1:3100').replace(/\/+$/, '');
  return {
    identityUrl: (env.IDENTITY_SERVICE_URL || 'http://identity-service:8005').replace(/\/+$/, ''),
    identityToken: readEnv('PLATFORM_PORTAL_TOKEN', ['CLOUDSAVER_IDENTITY_TOKEN_PORTAL', 'CLOUDSAVER_IDENTITY_TOKEN']),
    authMode: (readEnv('PLATFORM_PORTAL_AUTH', ['CLOUDSAVER_PORTAL_AUTH']) === 'operator_key' ? 'operator_key' : 'entra') as AuthMode,
    operatorKeyDigest: readEnv('PLATFORM_OPERATOR_KEY_SHA256', ['CLOUDSAVER_OPERATOR_KEY_SHA256']).trim().toLowerCase(),
    environment: (readEnv('PLATFORM_ENVIRONMENT', ['CLOUDSAVER_ENVIRONMENT']) || 'development').trim().toLowerCase(),
    publicUrl,
    publicOrigin: new URL(publicUrl).origin,
    entra: {
      tenantId: env.PORTAL_ENTRA_TENANT_ID || '',
      clientId: env.PORTAL_ENTRA_CLIENT_ID || '',
      clientSecret: env.PORTAL_ENTRA_CLIENT_SECRET || '',
      apiScope: env.PORTAL_ENTRA_API_SCOPE || 'api://cloudsaver-identity/.default',
      redirectUri: `${publicUrl}/api/auth/callback`,
    },
  };
}

export function isProduction() {
  return serverConfig().environment === 'production';
}
