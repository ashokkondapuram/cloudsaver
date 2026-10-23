import {json} from '../../../lib/server/http';

export const dynamic = 'force-dynamic';

export function GET() {
  return json({status: 'healthy', service: 'platform-portal'});
}
