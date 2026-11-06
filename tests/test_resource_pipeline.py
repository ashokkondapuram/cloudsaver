from unittest.mock import patch

from app.collectors.resource_pipeline import enrich_inventory_pipeline


def test_pipeline_reruns_analysis_through_resource_loop():
    resource = dict(
        cloud_provider='azure',
        resource_id='/subscriptions/x/resourceGroups/rg/providers/Microsoft.Compute/disks/d1',
        resource_type='Microsoft.Compute/disks',
        resource_name='d1',
        resource_group='rg',
        subscription_id='x',
        evidence={},
    )
    calls = []

    def fake_analyze(resource, **kwargs):
        calls.append(dict(stage=len(calls), disk_state=(resource.get('evidence') or {}).get('disk_state')))
        resource.setdefault('evidence', {})['fetch_stages'] = {
            'costs': 'pending',
            'activity_log': 'pending',
            'retail': 'pending',
            'analysis': 'completed',
            'recommendations': 'completed',
        }
        resource['recommendations'] = [{'title': f'pass-{len(calls)}'}]
        return dict(evaluations=[], findings=[], recommendations=resource['recommendations'], assessment=None)

    with patch('app.collectors.resource_pipeline.analyze_resource', side_effect=fake_analyze):
        with patch('app.collectors.resource_pipeline.arm_detail_enabled', return_value=False):
            with patch('app.collectors.resource_pipeline.live_enabled', return_value=False):
                inventory, findings = enrich_inventory_pipeline(
                    reader=None,
                    inventory=[resource],
                    settings=object(),
                    progress=None,
                    arg_findings=[],
                    policies={},
                    observed_at='2026-11-05T12:00:00Z',
                )
    assert len(inventory) == 1
    assert findings == []
    assert len(calls) == 1
    assert resource['recommendations'][0]['title'] == f'pass-{len(calls)}'
