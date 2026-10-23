import type {NextRequest} from 'next/server';
import {checkOrigin, json} from '../../../../lib/server/http';
import {clearSessionCookie, deleteSession} from '../../../../lib/server/session';

export const dynamic = 'force-dynamic';

export function POST(request: NextRequest) {
  const rejected = checkOrigin(request);
  if (rejected) return rejected;
  deleteSession(request);
  const response = json({signed_in: false});
  clearSessionCookie(response, request);
  return response;
}
