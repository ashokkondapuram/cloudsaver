import {serverConfig} from './config';

export function assertSafeStartup() {
  if (process.env.NEXT_PHASE === 'phase-production-build') return;
  const config = serverConfig();
  if (config.environment === 'production' && config.authMode === 'operator_key') {
    console.error('platform-portal: refusing to start. PLATFORM_PORTAL_AUTH=operator_key is not allowed when PLATFORM_ENVIRONMENT=production. Use Microsoft Entra sign-in.');
    process.exit(1);
  }
  if (!config.identityToken) console.warn('platform-portal: PLATFORM_PORTAL_TOKEN is not set; identity-service calls will be rejected.');
  if (config.authMode === 'operator_key' && !/^[0-9a-f]{64}$/.test(config.operatorKeyDigest)) {
    console.warn('platform-portal: PLATFORM_OPERATOR_KEY_SHA256 is missing or invalid; operator sign-in is disabled.');
  }
}
