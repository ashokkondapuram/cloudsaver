import type {Finding} from './types';
import {observedTags} from './finops';

export const categories=[['storage','Storage'],['compute','Compute'],['database','Databases'],['network','Network'],['application','Applications'],['other','Other']] as const;
export type Category=typeof categories[number][0];
export type Intent=''|'protected'|'review';
export type Pricing=''|'known'|'unknown';
export function categoryOf(finding:Pick<Finding,'resource_type'>):Category{
  const kind=finding.resource_type.toLowerCase();
  if(['disk','volume','storage'].some(s=>kind.includes(s)))return 'storage';
  if(['rds','sql','database','alloydb','aurora'].some(s=>kind.includes(s)))return 'database';
  if(['serverfarm','appservice','containerapp','lambda','cloudrun'].some(s=>kind.includes(s)))return 'application';
  if(['network','address','elastic-ip','gateway','publicip'].some(s=>kind.includes(s)))return 'network';
  if(['virtualmachine','instance','container','pod','cpu','memory','workload'].some(s=>kind.includes(s)))return 'compute';
  return 'other';
}
export function protectionSignals(finding:Finding):string[]{
  // A display/filter over saved observations. The server remains authoritative for exports.
  const normalize=(value:string)=>value.toLowerCase().replace(/[^a-z0-9]/g,'');
  const tags=Object.fromEntries(Object.entries(observedTags(finding)).map(([k,v])=>[normalize(k),normalize(v)]));
  const signals:string[]=[];
  if(['donottouch','donotdelete','retain','legalhold'].some(k=>['true','yes','1','enabled'].includes(tags[k])))signals.push('Retention intent');
  if(['role','disasterrecovery','purpose'].some(k=>['drstandby','disasterrecoverystandby','activestandby','coldspare','witness','donottouch'].includes(tags[k])))signals.push('Recovery / witness role');
  if(finding.evidence?.deletion_protection===true)signals.push('Deletion protection');
  return signals;
}
export function knownPrice(finding:Finding){const value=finding.estimated_monthly_waste_usd;return typeof value==='number'&&Number.isFinite(value)&&value>=0;}
export function sizingOf(finding:Finding){
  const evidence=finding.evidence||{};
  if(typeof evidence.size_gb==='number'&&Number.isFinite(evidence.size_gb)&&evidence.size_gb>=0)return `${evidence.size_gb.toLocaleString()} GB provisioned`;
  if(typeof evidence.minimum_request==='number'&&Number.isFinite(evidence.minimum_request)&&evidence.minimum_request>=0){
    if(evidence.unit==='cores')return `${evidence.minimum_request.toLocaleString()} cores requested`;
    if(evidence.unit==='bytes')return `${(evidence.minimum_request/1024**2).toLocaleString(undefined,{maximumFractionDigits:1})} MiB requested`;
  }
  return 'Sizing not observed';
}
export function matchesTag(finding:Finding,expression:string){
  const raw=expression.trim();
  if(!raw)return true;
  const tags=observedTags(finding);
  if(raw.startsWith('has:'))return Object.hasOwn(tags,raw.slice(4).trim());
  const equals=raw.indexOf('=');
  if(equals>=0)return tags[raw.slice(0,equals).trim()]===raw.slice(equals+1).trim();
  return Object.keys(tags).some(key=>key.toLowerCase().includes(raw.toLowerCase()));
}
export function matchesQuery(text:string,query:string){return query.toLowerCase().split(/\s+/).filter(Boolean).every(term=>text.toLowerCase().includes(term));}
