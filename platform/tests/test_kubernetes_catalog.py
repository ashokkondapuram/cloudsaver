import json
from pathlib import Path
from identity.analysis.kubernetes import DEFINITIONS
from identity.analysis.seed import RULE_SEED


def test_kubernetes_catalog_matches_shared_contract():
    ids=set(json.loads((Path(__file__).resolve().parents[1]/'contracts/fixtures/kubernetes-rule-ids-v2.json').read_text()))
    legacy=set(json.loads((Path(__file__).resolve().parents[1]/'contracts/fixtures/kubernetes-rule-ids-v1.json').read_text()))
    assert legacy<ids
    assert ids=={r[0] for r in DEFINITIONS}
    assert ids<={r[0] for r in RULE_SEED}
