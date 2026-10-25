import {useMemo} from 'react';
import {Coins,Layers3,ShieldCheck,Tags} from 'lucide-react';
import type {Finding} from '../../lib/types';
import {money,scopeOf,providerOf,opportunityTotals} from '../../lib/finops';
import {knownPrice,protectionSignals} from '../../lib/resource-insights';

export function ExplorerSummary({findings}:{findings:Finding[]}){
  const summary=useMemo(()=>{
    const priced=findings.filter(knownPrice);
    return {count:findings.length,priced:priced.length,retail:opportunityTotals(findings).known,
      protected:findings.filter(f=>protectionSignals(f).length>0).length,
      scopes:new Set(findings.map(f=>`${providerOf(f)}:${scopeOf(f)}`)).size};
  },[findings]);
  return <section className="explorer-summary" aria-label="Snapshot evidence summary">
    <article><span className="explorer-metric-icon"><Layers3 size={18}/></span><div><span>Observed findings</span><strong>{summary.count.toLocaleString()}</strong><small>{summary.scopes} accounts / scopes · current scope selection</small></div></article>
    <article><span className="explorer-metric-icon retail"><Coins size={18}/></span><div><span>Known retail portion</span><strong className={summary.priced?'':'unknown'}>{summary.priced?money(summary.retail):'Not estimated'}</strong><small>{summary.priced} of {summary.count} priced · USD / month</small></div></article>
    <article><span className="explorer-metric-icon protected"><ShieldCheck size={18}/></span><div><span>Protected intent</span><strong>{summary.protected.toLocaleString()}</strong><small>Saved recovery or retention signals</small></div></article>
    <article><span className="explorer-metric-icon unknown"><Tags size={18}/></span><div><span>Pricing evidence gaps</span><strong>{(summary.count-summary.priced).toLocaleString()}</strong><small>Unknown cost is excluded from the subtotal</small></div></article>
  </section>;
}
