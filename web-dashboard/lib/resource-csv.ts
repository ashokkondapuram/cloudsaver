import type {ResourceRow} from './resources';

/** Export exactly the authorized rows displayed by the explorer, preserving unknowns. */
export function resourceCsv(rows: ResourceRow[]): string {
  const pillars = ['cost', 'reliability', 'performance', 'security', 'operations'] as const;
  const fields = ['provider', 'scope_id', 'resource_name', 'resource_type', 'resource_group', 'resource_id', 'service_category',
    'rule_ids', 'review_priority', 'disposition', ...pillars, 'billed_cost_usd', 'effective_cost_usd', 'retail_estimate_usd',
    'lifecycle_delta', 'ai_status', 'ai_risk', 'ai_summary', 'decision', 'decision_at', 'evidence_digest'];
  const cell = (value: unknown) => {
    let text = String(value ?? '');
    if (/^[\s]*[=+@\-]|^[\t\r\n]/.test(text)) text = "'" + text;
    return '"' + text.replaceAll('"', '""') + '"';
  };
  return '\ufeff' + [fields.join(','), ...rows.map(row => {
    const values: Record<string, unknown> = {...row, ...row.pillars, rule_ids: row.rule_ids.join(';'),
      ai_status: row.ai.status, ai_risk: row.ai.risk_level, ai_summary: row.ai.summary,
      decision: row.decision?.decision, decision_at: row.decision?.created_at};
    return fields.map(field => cell(values[field])).join(',');
  })].join('\r\n') + '\r\n';
}
