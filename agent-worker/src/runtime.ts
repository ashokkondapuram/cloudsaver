import {stripTypeScriptTypes} from 'node:module';
import {checkAssignment} from './contracts.ts';
import type {Assignment, Connector, Outcome, Step, Task} from './contracts.ts';

type Gateway = (path: string, body: unknown) => Promise<unknown>;
type Execute = (task: Task, connector: Connector, step: Step, index: number) => Promise<Outcome>;

export async function runCode(assignment: Assignment, local: Connector[], gateway: Gateway, execute: Execute): Promise<void> {
  checkAssignment(assignment,local);
  const {task,lease_token} = assignment; const plan = task.payload.plan; let cursor = 0;
  const identity = {tenant_id:task.tenant_id,lease_token,plan_hash:task.payload.plan_hash};
  const prefix = '/internal/v1/agent/tasks/'+task.id;
  // Only the deterministic compiler's byte-for-byte program is imported. This is not a general code sandbox.
  const module = await import('data:text/javascript;base64,'+Buffer.from(stripTypeScriptTypes(assignment.code!)).toString('base64')) as {run:(ctx:{call:(index:number)=>Promise<Outcome>})=>Promise<unknown>};
  await module.run(Object.freeze({call: async (index: number) => {
    if (index !== cursor || index >= plan.steps.length) throw new Error('Out-of-order connector call');
    const permit = await gateway(prefix+`/steps/${index}/start`,identity) as {permitted?:boolean;index?:number;plan_hash?:string;outcome?:Outcome};
    if (!permit.permitted || permit.index!==index || permit.plan_hash!==task.payload.plan_hash) throw new Error('Gateway did not issue this step permit');
    const step = plan.steps[index]; const connector = local.find(c=>c.id===step.connector_id)!;
    let outcome: Outcome;
    try {
      if(step.operation==='gitops.terraform.sync'){
        if(!permit.outcome||!['succeeded','failed','uncertain'].includes(permit.outcome.status))throw new Error('Missing server-side repository outcome');
        outcome=permit.outcome;
      }else outcome = await execute(task,connector,step,index);
    } catch {outcome={status:'uncertain',code:'CONNECTOR_OUTCOME_UNCERTAIN'};}
    await gateway(prefix+`/steps/${index}/complete`,{...identity,outcome});
    cursor++;
    if (outcome.status!=='succeeded') throw new Error('Execution stopped for reconciliation');
    return outcome;
  }}));
}
