import {SignIn} from '../../components/SignIn';
import {serverConfig} from '../../lib/server/config';

export default async function SignInPage({searchParams}: {searchParams: Promise<Record<string, string | string[] | undefined>>}) {
  const params = await searchParams;
  const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value) || '';
  const config = serverConfig();
  return <SignIn authMode={config.authMode} error={first(params.error)} signedOut={first(params.signed_out) === '1'} returnTo={first(params.return_to)}/>;
}
