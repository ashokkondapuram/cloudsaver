"""Exact planning math. A scenario never authorizes purchasing a commitment."""
from decimal import Decimal, localcontext
import re

MONEY=re.compile(r'(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,4})?\Z')


def parse_strict_monetary_decimal(value):
    if type(value) not in (str,int,Decimal) or not MONEY.fullmatch(str(value)):
        raise ValueError('Use a nonnegative decimal string with at most four fractional digits; floats, booleans and scientific notation are not accepted.')
    return Decimal(str(value))


def decimal_text(value):
    return format(value,'f')


def calculate_clean_commitment_baseline(raw_spend_p10_hr,open_rightsizing_and_waste_hr,existing_commitments_hr):
    raw,waste,existing=map(parse_strict_monetary_decimal,(raw_spend_p10_hr,open_rightsizing_and_waste_hr,existing_commitments_hr))
    with localcontext() as context:
        context.prec=50
        cleaned=max(Decimal(0),raw-waste)
        additional=max(Decimal(0),cleaned-existing)
    return dict(status='scenario_only',currency='USD',unit='USD/hour',raw_spend_p10_hr=decimal_text(raw),
        open_rightsizing_and_waste_hr=decimal_text(waste),existing_commitments_hr=decimal_text(existing),
        clean_steady_state_hr=decimal_text(cleaned),recommended_new_commitment_hr=decimal_text(additional),
        purchase_authorized=False,warning='Planning ceiling only. Inputs must use the same scope, period and amortization basis; verify hourly coverage, commitment utilization and future demand before purchase.')


def hourly_p10(samples):
    """Nearest-rank P10; timestamps and continuity must be verified by the calling collector."""
    import math
    if not isinstance(samples,list) or not 720<=len(samples)<=2160:
        raise ValueError('Supply 30–90 days of hourly observations.')
    values=sorted(parse_strict_monetary_decimal(v) for v in samples)
    return decimal_text(values[math.ceil(.1*len(values))-1])


def commitment_firewall(plan,*,open_waste=None,clean_baseline=None):
    """Known commitments and AI provisioned capacity need an independently reviewed clean baseline."""
    from app.plan_policy import INDEX
    findings=[]
    for resource in plan.get('resource_changes',[]):
        kind=resource.get('type','');change=resource.get('change') or {};actions=change.get('actions',[])
        if resource.get('mode')!='managed' or not any(a in actions for a in ('create','update')):continue
        after=change.get('after') or {}
        unknown=change.get('after_unknown') or {}
        sku=after.get('sku')
        commitment=(kind.startswith('aws_savingsplans_') or kind in ('google_compute_region_commitment','azurerm_reservation','aws_ec2_capacity_reservation')
            or kind=='azurerm_cognitive_deployment' and (sku is None or bool(unknown.get('sku')) or 'provisioned' in str(sku).lower()))
        if not commitment:continue
        # Body-supplied context cannot constitute an operator approval of a plan hash.
        findings.append(dict(code='CLEAN_BASELINE_APPROVAL_REQUIRED',severity='error',address=INDEX.sub('[*]',resource['address']),
            message='Commitment/provisioned capacity change requires an independently reviewed clean usage baseline and commitment authorization.'))
    return findings
