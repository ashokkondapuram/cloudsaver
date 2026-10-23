from types import SimpleNamespace

import pytest

from app.scanner import ScanError, _findings, execute_pages, RULES
from tests.fixtures.synthetic_findings import demo_findings


SUB = "00000000-0000-0000-0000-000000000001"


def row(name="disk", sub=SUB):
    return {"id": f"/subscriptions/{sub}/resourceGroups/test/providers/Microsoft.Compute/disks/{name}",
            "subscriptionId": sub, "name": name, "resourceGroup": "test",
            "type": "microsoft.compute/disks"}


def page(rows, token=None, truncated="false"):
    return SimpleNamespace(data=rows, skip_token=token, result_truncated=truncated)


class Client:
    def __init__(self, *pages):
        self.pages = iter(pages)
        self.requests = []

    def resources(self, request, **kwargs):
        self.requests.append(request)
        result = next(self.pages)
        if isinstance(result, Exception):
            raise result
        return result


def test_all_pages_and_duplicate_resources():
    client = Client(page([row("one")], "next", "true"),
                    page([row("one"), row("two")]))
    assert len(execute_pages(client, "Resources | project id", [SUB])) == 2
    assert client.requests[0].options.top == 1000
    assert client.requests[0].options.allow_partial_scopes is False
    assert client.requests[1].options.skip_token == "next"


def test_repeated_token_fails_instead_of_looping():
    client = Client(page([row()], "next", "true"), page([row()], "next", "true"))
    with pytest.raises(ScanError, match="repeated"):
        execute_pages(client, "Resources", [SUB])


def test_truncated_without_token_fails():
    with pytest.raises(ScanError, match="truncated"):
        execute_pages(Client(page([row()], truncated="true")), "Resources", [SUB])


@pytest.mark.parametrize("bad", [{}, {"rows": []}, [None], [row(sub="00000000-0000-0000-0000-000000000002")]])
def test_malformed_and_unauthorized_rows_fail(bad):
    with pytest.raises(ScanError):
        execute_pages(Client(page(bad)), "Resources", [SUB])


def test_inconsistent_resource_id_fails():
    item = row()
    item["id"] = "/subscriptions/other/resourceGroups/test/providers/Microsoft.Compute/disks/disk"
    with pytest.raises(ScanError, match="inconsistent"):
        execute_pages(Client(page([item])), "Resources", [SUB])


def test_query_failure_does_not_return_partial_findings():
    with pytest.raises(RuntimeError, match="upstream failure"):
        _findings(Client(page([row()]), RuntimeError("upstream failure")), [SUB])


def test_live_findings_never_invent_savings():
    findings = _findings(Client(*(page([row(str(i))]) for i in range(len(RULES)))), [SUB])
    assert len(findings) == len(RULES)
    assert all(f["estimated_monthly_waste_usd"] is None for f in findings)
    assert {f["severity"] for f in findings} == {"HIGH", "MEDIUM", "LOW"}
    assert "review signal" in findings[2]["details"]


def test_demo_is_explicitly_illustrative():
    findings = demo_findings()
    assert len(findings) == 8
    assert all(f["details"].startswith("TEST FIXTURE:") for f in findings)
    assert sum(f["estimated_monthly_waste_usd"] for f in findings) == pytest.approx(507.90)


def test_arg_retains_observed_tags_and_size_without_inventing_security_or_backups():
    item = dict(row(), tags={'Role':'DR-Standby'}, sizeGB=128)
    client = Client(page([item]), *(page([]) for _ in RULES[1:]))
    finding = _findings(client,[SUB])[0]
    assert finding['evidence'] == {'source':'Azure Resource Graph','tags':{'Role':'DR-Standby'},'size_gb':128}
    assert 'tags' in client.requests[0].query
    from app.assessment import assess
    assert assess(finding)['disposition'] == 'protected'
