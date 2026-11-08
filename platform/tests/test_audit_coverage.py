"""Every mutating admin method must emit an audit event, or be explicitly exempted below."""
import inspect
import re
from pathlib import Path

from identity.analysis.admin import AnalysisOps
from identity.ai_policy import AIPolicyOps
from identity.billing.admin import BillingOps
from identity.customer.admin import CustomerOps

MUTATES = re.compile(r'\btx\.(insert|update|upsert|delete)_')
EMITS_EVENT = re.compile(r'self\._event\(')
ACTOR_TYPE_LITERAL = re.compile(r"'actor_type':\s*'([a-z_]+)'")
ROOT = Path(__file__).resolve().parents[1]


def mutating_methods_without_events(cls):
    missing = []
    for name, func in vars(cls).items():
        if name.startswith('_') or not inspect.isfunction(func):
            continue
        source = inspect.getsource(func)
        if MUTATES.search(source) and not EMITS_EVENT.search(source):
            missing.append(name)
    return missing


def test_every_mutating_admin_method_emits_an_audit_event():
    offenders = {cls.__name__: mutating_methods_without_events(cls)
                 for cls in (AnalysisOps, BillingOps, CustomerOps, AIPolicyOps)}
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, f'Mutating methods with no audit event: {offenders}'


def test_every_actor_type_literal_is_allowed_by_the_key_events_check():
    """BE-PLAT-01 regression: identity.key_events has CHECK (actor_type IN (...)); any actor_type literal
    used to write a key event that isn't in that list raises CheckViolation and rolls back the transaction
    (and, for a Stripe webhook, silently drops the dedupe row too)."""
    migration = (ROOT / 'identity_migrations' / 'versions' / 'i0007_client_access.py').read_text()
    match = re.search(r"actor_type IN \(([^)]+)\)", migration)
    assert match, 'Expected the key_events actor_type CHECK in i0007_client_access.py'
    allowed = {v.strip("'") for v in match.group(1).split(',')}
    literals = set()
    for path in (ROOT / 'identity').rglob('*.py'):
        literals |= set(ACTOR_TYPE_LITERAL.findall(path.read_text()))
    assert literals <= allowed, f'actor_type literals not in the key_events CHECK: {literals - allowed}'
