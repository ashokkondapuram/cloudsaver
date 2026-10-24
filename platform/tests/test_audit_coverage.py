"""Every mutating admin method must emit an audit event, or be explicitly exempted below."""
import inspect
import re

from identity.analysis.admin import AnalysisOps
from identity.ai_policy import AIPolicyOps
from identity.billing.admin import BillingOps
from identity.customer.admin import CustomerOps

MUTATES = re.compile(r'\btx\.(insert|update|upsert|delete)_')
EMITS_EVENT = re.compile(r'self\._event\(')


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
