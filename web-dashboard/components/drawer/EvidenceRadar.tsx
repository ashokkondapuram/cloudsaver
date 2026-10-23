'use client';
import {useId} from 'react';

type Pillar={pillar:string;status:'risk'|'observed'|'unknown';checks:{status:string}[]};
export function EvidenceRadar({pillars,onInspect}:{pillars:Pillar[];onInspect:(pillar:string)=>void}){
  const id=useId();
  const center={x:160,y:132},radius=77;
  const point=(index:number,distance:number)=>{
    const angle=-Math.PI/2+index*2*Math.PI/5;
    return {x:center.x+Math.cos(angle)*distance,y:center.y+Math.sin(angle)*distance};
  };
  const polygon=(distance:number)=>pillars.map((_,i)=>{const p=point(i,distance);return `${p.x},${p.y}`;}).join(' ');
  const counts=pillars.map(p=>({observed:p.checks.filter(c=>c.status!=='unknown').length,total:p.checks.length}));
  const values=counts.map((c,i)=>{const p=point(i,c.total?radius*c.observed/c.total:0);return `${p.x},${p.y}`;}).join(' ');
  return <section className="evidence-radar" aria-label="Five-pillar evidence map">
    <div className="radar-heading"><h3>Five pillars. One evidence map.</h3><span>Coverage, not a safety score</span></div>
    <svg className="radar-chart" viewBox="0 0 320 260" role="img" aria-labelledby={`${id}-title ${id}-description`}>
      <title id={`${id}-title`}>Observed evidence coverage across five architectural pillars</title>
      <desc id={`${id}-description`}>{pillars.map((p,i)=>`${p.pillar}: ${counts[i].observed} of ${counts[i].total} checks have evidence, status ${p.status}`).join('. ')}. Unknown checks are not passed checks. Observed risk counts as evidence.</desc>
      {[0.25,0.5,0.75,1].map(scale=><polygon key={scale} className="radar-grid" points={polygon(radius*scale)}/>)}
      {pillars.map((p,i)=>{const end=point(i,radius);return <line key={p.pillar} className="radar-grid" x1={center.x} y1={center.y} x2={end.x} y2={end.y}/>;})}
      <polygon className="radar-area" points={values}/><circle className="radar-center" cx={center.x} cy={center.y} r={2}/>
      {pillars.map((p,i)=>{
        const end=point(i,counts[i].total?radius*counts[i].observed/counts[i].total:0),label=point(i,100);
        const anchor=label.x<center.x-10?'end':label.x>center.x+10?'start':'middle';
        return <g key={p.pillar}><circle cx={end.x} cy={end.y} r={3.5} fill={p.status==='risk'?'var(--risk)':p.status==='observed'?'var(--known)':'var(--muted)'} stroke="var(--surface)" strokeWidth={1.5}/><text x={label.x} y={label.y} textAnchor={anchor}>{p.pillar.charAt(0).toUpperCase()+p.pillar.slice(1)}</text><text x={label.x} y={label.y+14} textAnchor={anchor} className="radar-count">{counts[i].observed}/{counts[i].total} observed</text></g>;
      })}
    </svg>
    <div className="radar-legend"><span><i className="observed"/>Observed</span><span><i className="risk"/>Risk observed</span><span><i/>Unknown</span></div>
    <div className="radar-pillar-links" role="group" aria-label="Inspect pillar evidence">{pillars.map(p=><button key={p.pillar} onClick={()=>onInspect(p.pillar)} aria-label={`Inspect ${p.pillar} checks`}>{p.pillar}</button>)}</div>
    <p>Each axis measures the share of checks with saved evidence, including observed risks. Full coverage does not establish safety, live state, or change approval.</p>
  </section>;
}
