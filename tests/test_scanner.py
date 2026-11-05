import pytest

from app.collectors import azure_resource_graph as arg
from app.scanner import ScanError, _findings, execute_pages, RULES
from tests.fixtures.synthetic_findings import demo_findings


SUB = "00000000-0000-0000-0000-000000000001"


def row(name="disk", sub=SUB):
    return {"id": f"/subscriptions/{sub}/resourceGroups/test/providers/Microsoft.Compute/disks/{name}",
            "subscriptionId": sub, "name": name, "resourceGroup": "test",
            "type": "microsoft.compute/disks"}


def rest_page(rows, token=None, truncated=False):
    payload = {"data": rows, "resultTruncated": truncated}
    if token:
        payload["$skipToken"] = token
    return payload


class PostHarness:
    def __init__(self, *pages):
        self.pages = iter(pages)
        self.bodies = []

    def __call__(self, _credential, body):
        self.bodies.append(body)
        result = next(self.pages)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def patch_post(monkeypatch):
    def _install(*pages):
        harness = PostHarness(*pages)
        monkeypatch.setattr(arg, "_post_page", harness)
        return harness

    return _install


def test_all_pages_and_duplicate_resources(patch_post):
    harness = patch_post(
        rest_page([row("one")], "next", truncated=True),
        rest_page([row("one"), row("two")]),
    )
    assert len(execute_pages(object(), "Resources | project id", [SUB])) == 2
    assert harness.bodies[0]["options"]["$top"] == 1000
    assert harness.bodies[0]["options"]["allowPartialScopes"] is False
    assert harness.bodies[1]["options"]["$skipToken"] == "next"


def test_repeated_token_fails_instead_of_looping(patch_post):
    patch_post(
        rest_page([row()], "next", truncated=True),
        rest_page([row()], "next", truncated=True),
    )
    with pytest.raises(ScanError, match="repeated"):
        execute_pages(object(), "Resources", [SUB])


def test_truncated_without_token_fails(patch_post):
    patch_post(rest_page([row()], truncated=True))
    with pytest.raises(ScanError, match="truncated"):
        execute_pages(object(), "Resources", [SUB])


@pytest.mark.parametrize(
    "bad",
    [
        {"data": {}},
        {"data": {"rows": []}},
        {"data": [None]},
        {"data": [row(sub="00000000-0000-0000-0000-000000000002")]},
    ],
)
def test_malformed_and_unauthorized_rows_fail(patch_post, bad):
    patch_post(bad)
    with pytest.raises(ScanError):
        execute_pages(object(), "Resources", [SUB])


def test_inconsistent_resource_id_fails(patch_post):
    item = row()
    item["id"] = "/subscriptions/other/resourceGroups/test/providers/Microsoft.Compute/disks/disk"
    patch_post(rest_page([item]))
    with pytest.raises(ScanError, match="inconsistent"):
        execute_pages(object(), "Resources", [SUB])


def test_query_failure_does_not_return_partial_findings(patch_post):
    patch_post(rest_page([row()]), RuntimeError("upstream failure"))
    with pytest.raises(RuntimeError, match="upstream failure"):
        _findings(object(), [SUB])


def test_live_findings_never_invent_savings(patch_post):
    pages = [rest_page([row(str(i))]) for i in range(len(RULES))]
    patch_post(*pages)
    findings = _findings(object(), [SUB])
    assert len(findings) == len(RULES)
    assert all(f["estimated_monthly_waste_usd"] is None for f in findings)
    assert {f["severity"] for f in findings} == {"HIGH", "MEDIUM", "LOW"}
    assert "review signal" in findings[2]["details"]


def test_demo_is_explicitly_illustrative():
    findings = demo_findings()
    assert len(findings) == 8
    assert all(f["details"].startswith("TEST FIXTURE:") for f in findings)
    assert sum(f["estimated_monthly_waste_usd"] for f in findings) == pytest.approx(507.90)


def test_arg_retains_observed_tags_and_size_without_inventing_security_or_backups(patch_post):
    item = dict(row(), tags={'Role':'DR-Standby'}, sizeGB=128)
    pages = [rest_page([item])] + [rest_page([]) for _ in RULES[1:]]
    harness = patch_post(*pages)
    finding = _findings(object(), [SUB])[0]
    assert finding['evidence'] == {'source':'Azure Resource Graph','tags':{'Role':'DR-Standby'},'size_gb':128}
    assert 'tags' in harness.bodies[0]['query']
    from app.assessment import assess
    assert assess(finding)['disposition'] == 'protected'


def test_arg_collects_only_explicit_encryption_app_density_and_zone_controls(patch_post):
    disk = dict(row(),encryptionType='EncryptionAtRestWithCustomerKey')
    app = dict(row('app'),type='microsoft.web/serverfarms',hostedAppCount=0,zoneRedundant=False)
    pages = [rest_page([disk]),rest_page([]),rest_page([]),rest_page([app]),rest_page([]),rest_page([]),rest_page([])]
    harness = patch_post(*pages)
    findings=_findings(object(),[SUB])
    assert findings[0]['evidence']['encrypted'] is True
    assert findings[1]['evidence']['hosted_app_count']==0
    assert findings[1]['evidence']['multi_az'] is False
    assert 'encryptionType' in harness.bodies[0]['query']
    assert 'hostedAppCount' in harness.bodies[3]['query']
    from app.assessment import assess
    result=assess(findings[1])
    assert {'APPLICATION_DENSITY','FAILOVER_TOPOLOGY'} <= set(result['risk_check_codes'])
