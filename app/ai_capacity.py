"""PTU/PAYG review math from complete token windows and explicit reviewed meters."""
from decimal import Decimal,localcontext
from app.telemetry_contract import evaluate_series,TimeSeriesEvidenceContract,moment
from app.commitment_arbitrage import parse_strict_monetary_decimal as money

def ptu_review(evidence,now,threshold=35):
    metrics=evidence.get('metrics') or {};pricing=evidence.get('pricing_evidence') or {};stamp=moment(pricing.get('observed_at'))
    if evidence.get('provisioned_mode') is not True or evidence.get('commitment_lock_conflict') is not False or pricing.get('currency')!='USD' or pricing.get('basis')!='reviewed_meter_rates' or not stamp or not 0<=(now-stamp).total_seconds()<86400:return None
    values={k:evaluate_series(metrics.get(k),TimeSeriesEvidenceContract(k,stat),now=now,require_resource_age=False) for k,stat in (('ptu_utilization','P95'),('input_tokens','SUM'),('output_tokens','SUM'))}
    if not all(v.is_sufficient for v in values.values()):return None
    input_rate,output_rate,provisioned=map(money,(pricing.get('input_per_million_usd'),pricing.get('output_per_million_usd'),pricing.get('monthly_provisioned_usd')))
    if provisioned<=0:return None
    with localcontext() as context:
        context.prec=50
        payg=(Decimal(str(values['input_tokens'].observed_value))*input_rate+Decimal(str(values['output_tokens'].observed_value))*output_rate)/Decimal(1000000)
        return values['ptu_utilization'].observed_value<threshold and payg<provisioned*Decimal('.60')
