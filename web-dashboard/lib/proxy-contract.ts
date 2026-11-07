/** Explicit browser exposure for integrations absent from the legacy route list.
 * Backend authorization remains authoritative; this admits no internal routes. */
const id='[a-fA-F0-9-]{36}';
export const INTEGRATION_ROUTES: ReadonlyArray<readonly [string,RegExp]> = [
 ['GET',/^v1\/rules\/catalog\/(?:azure-compute|by-pillar)$/],
 ['GET',/^v1\/kubernetes\/grafana\/connectors$/],
 ['POST',/^v1\/kubernetes\/grafana\/connectors(?:\/test)?$/],
 ['POST',new RegExp('^v1/kubernetes/grafana/connectors/'+id+'(?:/test)?$')],
 ['POST',/^v1\/kubernetes\/grafana\/rightsizing\/run$/],
 ['GET',new RegExp('^v1/kubernetes/grafana/rightsizing/jobs/'+id+'$')],
];
export function allowsIntegrationRoute(method: string,path: string) {
 return INTEGRATION_ROUTES.some(([verb,pattern])=>method===verb&&pattern.test(path));
}
