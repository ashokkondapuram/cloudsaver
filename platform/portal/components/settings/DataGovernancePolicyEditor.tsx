'use client';

export type ProcessorApproval={workspace_id:string;target_id:string;azure_resource_id:string;endpoint_url:string;deployment_name:string;purposes:string[];
  review_reference:string;review_expires_at:string;provider_controls_reviewed:boolean};
export type DataPolicy={environment_id:string;azure_tenant_id:string;response_retention_days:number;allow_training:false;allow_cross_tenant_reuse:false;allow_external_action_data:false;processors:ProcessorApproval[]};
export const defaultDataPolicy:DataPolicy={environment_id:'',azure_tenant_id:'',response_retention_days:7,allow_training:false,allow_cross_tenant_reuse:false,allow_external_action_data:false,processors:[]};
const purposes=['assessment','resource_assessment','followup','agent_planning'];

export function DataGovernancePolicyEditor({value,onChange}:{value:DataPolicy;onChange:(value:DataPolicy)=>void}){
  const change=(index:number,patch:Partial<ProcessorApproval>)=>onChange({...value,processors:value.processors.map((p,i)=>i===index?{...p,...patch}:p)});
  return <fieldset><legend>AI data governance</legend><p className="muted">Register the organization’s logical processing environment. A workspace consent checkbox or an agent task approval cannot override these data-use rules.</p>
    <label className="field-label">Owning environment ID<input value={value.environment_id} onChange={e=>onChange({...value,environment_id:e.target.value})} placeholder="prod-company"/></label>
    <label className="field-label">Owning Azure tenant UUID<input value={value.azure_tenant_id} onChange={e=>onChange({...value,azure_tenant_id:e.target.value})} placeholder="Azure tenant UUID"/></label>
    <label className="field-label">New model-content retention (days)<input type="number" min={1} max={30} value={value.response_retention_days} onChange={e=>onChange({...value,response_retention_days:Number(e.target.value)})}/></label>
    <p className="muted">Raw inventory, resource names, tags and credentials are excluded from model context. Client-data training, cross-tenant learning and generic HTTP action transfers are prohibited. Reviewed public/synthetic guidance remains separate from tenant observations.</p>
    <h3>Purpose-bound processing approvals</h3><p className="muted">Empty approvals block all model processing. Register exact endpoints and deployments only after the data owner reviews processing location, retention and prohibition of training use. This records an attestation; it does not certify the provider’s service-side behavior.</p>
    {value.processors.map((p,index)=><fieldset className="settings-fieldset" key={index}><legend>Processor approval {index+1}</legend>
      {([['workspace_id','Workspace UUID'],['target_id','Approved target ID'],['azure_resource_id','Azure AI account resource ID'],['endpoint_url','Approved processing endpoint URL'],['deployment_name','Approved deployment name'],['review_reference','Internal data-owner review reference']] as const).map(([key,label])=><label className="field-label" key={key}>{label}<input value={p[key]} onChange={e=>change(index,{[key]:e.target.value})}/></label>)}
      <label className="field-label">Review expiry (ISO 8601 with timezone)<input value={p.review_expires_at} onChange={e=>change(index,{review_expires_at:e.target.value})} placeholder="2026-12-01T00:00:00Z"/></label>
      <fieldset><legend>Approved processing purposes</legend>{purposes.map(purpose=><label className="checkbox-row" key={purpose}><input type="checkbox" checked={p.purposes.includes(purpose)} onChange={e=>change(index,{purposes:e.target.checked?[...p.purposes,purpose]:p.purposes.filter(x=>x!==purpose)})}/>{purpose.replaceAll('_',' ')}</label>)}</fieldset>
      <label className="checkbox-row"><input type="checkbox" checked={p.provider_controls_reviewed} onChange={e=>change(index,{provider_controls_reviewed:e.target.checked})}/>The referenced review covers no training use, approved provider retention and processing within the owning environment.</label>
      <button className="button secondary" type="button" onClick={()=>onChange({...value,processors:value.processors.filter((_,i)=>i!==index)})}>Remove approval</button>
    </fieldset>)}
    <button className="button secondary" type="button" disabled={value.processors.length>=50} onClick={()=>onChange({...value,processors:[...value.processors,{workspace_id:'',target_id:'',azure_resource_id:'',endpoint_url:'',deployment_name:'',purposes:[],review_reference:'',review_expires_at:'',provider_controls_reviewed:false}]})}>Register reviewed processor</button>
  </fieldset>;
}
