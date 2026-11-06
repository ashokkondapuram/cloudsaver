from app.evidence_autofill import autofill_evidence


def test_autofill_dependencies_and_utilization_rollup():
    resource = dict(
        resource_type='Microsoft.Compute/virtualMachines',
        evidence=dict(
            dependency_inventory_complete=True,
            metric_summaries=dict(
                cpu_percent=dict(
                    sufficient=True,
                    p95=12.5,
                    coverage_ratio=0.96,
                )
            ),
            metrics=dict(
                cpu_percent=dict(
                    window_start='2026-10-06T00:00:00Z',
                    window_end='2026-11-05T00:00:00Z',
                    points=[dict(at='2026-11-04T00:00:00Z', value=1.0)],
                )
            ),
        ),
    )
    autofill_evidence(resource)
    ev = resource['evidence']
    assert ev['dependencies_verified'] is True
    assert ev['p95_usage'] == 12.5
    assert ev['window_start']


def test_configuration_readiness_complete_after_autofill():
    from app.collectors.azure_configuration_evidence import enrich_configuration_evidence

    resource = dict(
        cloud_provider='azure',
        resource_type='Microsoft.Network/loadBalancers',
        resource_id='/subscriptions/x/resourceGroups/rg/providers/Microsoft.Network/loadBalancers/lb1',
        evidence=dict(
            dependencies_verified=True,
            backend_pool_count=2,
            typed_configuration=dict(backendAddressPools=[{}, {}]),
        ),
    )
    enrich_configuration_evidence(resource)
    readiness = resource['evidence']['analysis_readiness']
    assert readiness['configuration'] == 'complete'
