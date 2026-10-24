"""Evidence-wired planning, with exact decimals and no purchase or change authority."""
from datetime import timedelta
from decimal import Decimal,localcontext
import math
from app.causal_topology_simulator import evaluate_slo_bounded_rightsizing
from app.commitment_arbitrage import parse_strict_monetary_decimal as money,decimal_text
from app.telemetry_contract import moment

def hourly_profile(value):
    if not isinstance(value,dict) or value.get('unit')!='USD/hour' or value.get('currency')!='USD':raise ValueError('Supply a USD/hour profile; heterogeneous usage units cannot be added.')
    start,end=moment(value.get('window_start')),moment(value.get('window_end'))
    if not start or not end or end-start!=timedelta(days=30) or start.minute or start.second or start.microsecond:raise ValueError('Use a complete aligned 30-day hourly window.')
    points=value.get('points')
    if not isinstance(points,list) or len(points)!=720:raise ValueError('All 720 hours are required; missing usage is never zero-filled.')
    result={}
    for point in points:
        at=moment(point.get('at'))
        if not at or not start<at<=end or (at-start).total_seconds()%3600 or at in result:raise ValueError('Duplicate or unaligned usage hour.')
        result[at]=money(point.get('value'))
    return start,end,[result[t] for t in sorted(result)]

def compute_clean_before_commit_plan(hourly_usage_series,resource_assessments,commitment_terms):
    start,end,raw=hourly_profile(hourly_usage_series);groups={};gaps=[]
    if not isinstance(resource_assessments,list) or len(resource_assessments)>1000:raise ValueError('Bound the assessment portfolio to 1000 resources.')
    for a in resource_assessments:
        if a.get('outcome') not in ('condition_detected','condition_not_detected'):
            gaps.append('RESOURCE_REVIEW_INCOMPLETE');continue
        if a.get('outcome')!='condition_detected' or a.get('disposition')!='requires_review':continue
        if a.get('cost_basis')=='allocation_only':continue
        if a.get('commitment_lock_conflict') is not False:
            gaps.append('COMMITMENT_DISPOSITION_UNVERIFIED');continue
        profile=a.get('hourly_waste_profile')
        if not profile:gaps.append('HOURLY_WASTE_PROFILE_MISSING');continue
        pstart,pend,values=hourly_profile(profile)
        if (pstart,pend)!=(start,end):raise ValueError('Cleanup and usage windows must match exactly.')
        key=(a.get('provider'),a.get('scope_id'),a.get('opportunity_group_id') or a.get('resource_key'))
        if not all(key):raise ValueError('Bind cleanup profiles to an owned resource/group, provider and scope.')
        prior=groups.get(key);groups[key]=values if prior is None else [max(x,y) for x,y in zip(prior,values)]
    if not isinstance(commitment_terms,list) or not 1<=len(commitment_terms)<=20:raise ValueError('Supply bounded reviewed one/three-year scenarios.')
    with localcontext() as context:
        context.prec=50
        waste=[sum((v[i] for v in groups.values()),Decimal(0)) for i in range(720)]
        if any(w>v for w,v in zip(waste,raw)):raise ValueError('Waste exceeds the corresponding observed hour.')
        cleaned=[v-w for v,w in zip(raw,waste)]
        q=lambda values:sorted(values)[math.ceil(len(values)*.15)-1]
        naive,floor=q(raw),q(cleaned);annual_cleanup=sum(waste)/Decimal(720)*Decimal(8760)
        options=[]
        for t in commitment_terms:
            if set(t)!={'term_years','discount_percent','existing_commitment_hr','review_reference'} or type(t['term_years']) is not int or t['term_years'] not in (1,3):raise ValueError('Terms require an exact one/three-year scenario and review reference.')
            import re
            if not isinstance(t['review_reference'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{2,119}',t['review_reference']):raise ValueError('Invalid term review reference.')
            discount=money(t['discount_percent'])/100;existing=money(t['existing_commitment_hr'])
            if not 0<discount<1:raise ValueError('Discount must be strictly between zero and 100 percent.')
            additional=max(Decimal(0),floor-existing)
            options.append(dict(term_years=t['term_years'],recommended_additional_commitment_hr=decimal_text(additional) if not gaps else None,
                naive_commitment_waste_avoided_usd=decimal_text(max(Decimal(0),naive-floor)*(1-discount)*8760) if not gaps else None,
                modeled_clean_plus_commit_annual_savings_usd=decimal_text(annual_cleanup+additional*discount*8760) if not gaps else None,
                verified_physical_cleanup_savings_usd=None,review_reference=t['review_reference']))
    return dict(status='insufficient_evidence' if gaps else 'scenario_only',unit='USD/hour',currency='USD',percentile='nearest_rank_P15',
        cleaned_commitment_floor_hr=decimal_text(floor) if not gaps else None,opportunity_group_count=len(groups),evidence_gaps=sorted(set(gaps)),
        options=options,purchase_authorized=False,automatic_execution=False,
        warning='Historical cleanup profiles and term discounts are scenario inputs. Cleanup is not completed or financially verified; future demand, coverage and contract eligibility need independent review.')

def simulate_topology_blast_radius(resource_id,action,dependency_edges,*,resources,observed_at=None,now=None):
    from datetime import datetime,timezone
    from app.analysis_rules import series
    now=now or datetime.now(timezone.utc)
    if action not in ('retirement','consolidation'):raise ValueError('Unsupported topology action')
    if len(resources)>2000 or len(dependency_edges)>10000:raise ValueError('Topology review bound exceeded')
    nodes={r['resource_id']:r for r in resources}
    if len(nodes)!=len(resources) or resource_id not in nodes:raise ValueError('Select an owned unique topology root.')
    edges={key:[] for key in nodes};gaps=[]
    stamp=moment(observed_at)
    if not stamp or not 0<=(now-stamp).total_seconds()<86400:gaps.append('STALE_TOPOLOGY')
    for edge in dependency_edges:
        a,b=edge.get('from_resource_id'),edge.get('to_resource_id')
        if a not in nodes or b not in nodes:raise ValueError('Topology edge references an unobserved resource')
        if edge.get('verification_state')!='verified':gaps.append('UNVERIFIED_DEPENDENCY')
        edges[a].append(b)
    visited=set();pending=[resource_id]
    while pending:
        key=pending.pop()
        if key in visited:continue
        visited.add(key);r=nodes[key];e=r.get('evidence') or {}
        if e.get('dependencies_verified') is not True:gaps.append('DEPENDENCY_COMPLETENESS_UNVERIFIED')
        if r.get('reconciliation_status')=='source_conflict':gaps.append('SOURCE_CONFLICT')
        from app.assessment import protection
        if protection(r):gaps.append('PROTECTED_RESOURCE')
        for name in ('requests','healthy_targets'):
            values=series((e.get('metrics') or {}).get(name),now)
            if not values:gaps.append('COMPLETE_'+name.upper()+'_WINDOW_REQUIRED')
            elif values['maximum']>0:gaps.append('ACTIVE_'+name.upper())
        pending+=edges[key]
    return dict(status='blocked' if gaps else 'review_eligible',reviewed_resources=sorted(visited),evidence_gaps=sorted(set(gaps)),
        automatic_execution=False,change_approved=False,warning='Zero observed traffic and verified graph coverage support review, not deletion authority or guaranteed blast radius.')
