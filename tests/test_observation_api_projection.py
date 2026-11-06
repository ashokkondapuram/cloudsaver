from datetime import datetime, timezone

from app.resource_assessment import observation_list_extras, prepare_observation
from app.resource_timestamps import touch_last_analyzed, touch_azure_status_fetched


def test_observation_list_extras_runs_enrichment():
    now = datetime.now(timezone.utc)
    evidence = dict(
        dependencies_verified=True,
        backend_pool_count=1,
        typed_configuration=dict(backendAddressPools=[{}]),
    )
    touch_last_analyzed(evidence, now=now)
    touch_azure_status_fetched(evidence, now=now)
    observation = dict(
        cloud_provider='azure',
        resource_type='Microsoft.Network/loadBalancers',
        resource_id='/subscriptions/x/resourceGroups/rg/providers/Microsoft.Network/loadBalancers/lb1',
        evidence=evidence,
    )
    extras = observation_list_extras(observation)
    assert extras['analysis_readiness']['configuration'] == 'complete'
    assert extras['type_registry']['evidence_fields_pending'] == []
    assert extras['analysis_readiness']['telemetry_pending_rule_ids'] == ['AZURE_LB_EMPTY_OR_IDLE_BACKEND']
    assert extras['evidence_incomplete'] is True

    prepared = prepare_observation(observation)
    assert prepared['evidence']['analysis_readiness']['configuration'] == 'complete'
