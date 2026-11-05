'use client';

import {sentence} from '../../lib/resources';

type FindingRow = {id: string; state: string; payload: {resource_name: string}};

const COLUMNS: {key: string; title: string; states: string[]}[] = [
  {key: 'triage', title: 'Triage', states: ['triaged', 'reopened', 'incident_escalated']},
  {key: 'approval', title: 'Plan & approval', states: ['proposed', 'approved', 'dismissal_review']},
  {key: 'execution', title: 'Implementation', states: ['implemented']},
  {key: 'outcome', title: 'Verification & closure', states: ['verified', 'closed', 'dismissed']},
];

type Props = {
  findings: FindingRow[];
  onOpen?: (id: string) => void;
};

/** Board-style treatment queue (BoardUI pattern) with table-equivalent cards per column. */
export function FindingWorkflowBoard({findings, onOpen}: Props) {
  return (
    <section className="panel plan-workflow-board" aria-label="Finding treatment workflow" data-atlas-rollout="governance-board">
      <div className="plan-workflow-board-head">
        <h2>Treatment workflow</h2>
        <p className="inline-help">Counts by saved governance state — not a separate workflow engine.</p>
      </div>
      <div className="plan-workflow-columns">
        {COLUMNS.map(column => {
          const rows = findings.filter(f => column.states.includes(f.state));
          return (
            <div className="plan-workflow-column" key={column.key}>
              <header>
                <h3>{column.title}</h3>
                <span className="plan-workflow-count">{rows.length}</span>
              </header>
              <ul>
                {rows.slice(0, 8).map(f => (
                  <li key={f.id}>
                    {onOpen ? (
                      <button type="button" className="plan-workflow-card" onClick={() => onOpen(f.id)}>
                        <strong>{f.payload.resource_name}</strong>
                        <small>{sentence(f.state)}</small>
                      </button>
                    ) : (
                      <div className="plan-workflow-card">
                        <strong>{f.payload.resource_name}</strong>
                        <small>{sentence(f.state)}</small>
                      </div>
                    )}
                  </li>
                ))}
                {!rows.length && <li className="plan-workflow-empty">None in this column</li>}
                {rows.length > 8 && <li className="plan-workflow-more">+{rows.length - 8} more in table view</li>}
              </ul>
            </div>
          );
        })}
      </div>
    </section>
  );
}
