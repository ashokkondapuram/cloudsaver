import type {NextRequest} from 'next/server';
import {serverConfig} from '../../../../lib/server/config';
import {json} from '../../../../lib/server/http';
import {readSession} from '../../../../lib/server/session';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const config = serverConfig();
  let session;
  try {session=await readSession(request);} catch {return json({detail:'Session service unavailable'},503);}
  if (!session) return json({signed_in: false, auth_mode: config.authMode, environment: config.environment});
  return json({signed_in: true, ...session.profile, signed_in_at: new Date(session.signed_in_at).toISOString()});
}
