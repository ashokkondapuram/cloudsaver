"""Offline Terraform plan guardrails. No provider access or raw values in results."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import math
import re

MAX_BYTES = 2_000_000
ADDRESS = re.compile(r'^[A-Za-z_][A-Za-z0-9_.-]*(?:\[(?:[0-9]+|"(?:[^"\\]|\\.)*")\][A-Za-z0-9_.-]*)*$')
INDEX = re.compile(r'\[(?:[0-9]+|"(?:[^"\\]|\\.)*")\]')


class InvalidPlan(ValueError):
    pass


def load_json(raw):
    if len(raw) > MAX_BYTES:
        raise InvalidPlan('Input exceeds the 2 MB limit')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise InvalidPlan('Duplicate JSON keys are unsupported')
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(InvalidPlan('Non-finite JSON numbers are unsupported')))
    except (ValueError, RecursionError, UnicodeError):
        raise InvalidPlan('Invalid JSON input') from None
    stack = [(value, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if isinstance(item,float) and not math.isfinite(item):
            raise InvalidPlan('Non-finite JSON numbers are unsupported')
        if depth > 64 or nodes > 200000:
            raise InvalidPlan('Input complexity exceeds the policy limit')
        if isinstance(item, dict):
            stack.extend((v, depth+1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth+1) for v in item)
    return value


def money(value):
    try:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)) or len(str(value)) > 32:
            raise ValueError()
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > Decimal('1000000000'):
            raise ValueError()
        return amount
    except (InvalidOperation, ValueError):
        raise InvalidPlan('Cost values must be finite nonnegative amounts') from None


@dataclass(frozen=True)
class PlanPolicy:
    max_monthly_increase_usd: Decimal | None = None
    required_tags: tuple[str, ...] = ()
    allow_deletes: bool = False

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) - {'max_monthly_increase_usd','required_tags','allow_deletes'}:
            raise InvalidPlan('Unsupported policy configuration')
        tags = data.get('required_tags', [])
        if not isinstance(tags, list) or len(tags) > 20 or any(not isinstance(t,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',t) for t in tags) or len(set(tags)) != len(tags):
            raise InvalidPlan('Invalid required tag names')
        if type(data.get('allow_deletes', False)) is not bool:
            raise InvalidPlan('allow_deletes must be boolean')
        maximum = data.get('max_monthly_increase_usd')
        return cls(money(maximum) if maximum is not None else None, tuple(tags), data.get('allow_deletes',False))


# Only these association attributes can prove a relationship. Tags and depends_on cannot.
ASSOCIATIONS = {
    'azurerm_managed_disk': [('azurerm_virtual_machine_data_disk_attachment','managed_disk_id'),
                              ('azurerm_virtual_machine','storage_data_disk.managed_disk_id')],
    'azurerm_public_ip': [('azurerm_network_interface','ip_configuration.public_ip_address_id'),
                         ('azurerm_application_gateway','frontend_ip_configuration.public_ip_address_id'),
                         ('azurerm_lb','frontend_ip_configuration.public_ip_address_id'),
                         ('azurerm_nat_gateway_public_ip_association','public_ip_address_id')],
    'aws_ebs_volume': [('aws_volume_attachment','volume_id')],
    'aws_eip': [('aws_eip_association','allocation_id'),('aws_nat_gateway','allocation_id'),
                ('aws_network_interface','association.allocation_id')],
    'google_compute_disk': [('google_compute_attached_disk','disk'),('google_compute_instance','attached_disk.source')],
    'google_compute_region_disk': [('google_compute_attached_disk','disk'),('google_compute_instance','attached_disk.source')],
    'google_compute_address': [('google_compute_forwarding_rule','ip_address'),
                              ('google_compute_instance','network_interface.access_config.nat_ip')],
}


def _resources(module, prefix='', depth=0):
    if depth > 20 or not isinstance(module,dict):
        raise InvalidPlan('Invalid module configuration')
    for resource in module.get('resources', []):
        if not isinstance(resource,dict) or not isinstance(resource.get('address'),str):
            raise InvalidPlan('Invalid resource configuration')
        yield prefix + resource['address'], resource
    for name, call in module.get('module_calls', {}).items():
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', name) or not isinstance(call,dict) or 'module' not in call:
            raise InvalidPlan('Unexpanded modules require a complete Terraform plan')
        yield from _resources(call['module'], prefix + 'module.'+name+'.', depth+1)


def _references(expression):
    if isinstance(expression,dict):
        refs = expression.get('references', [])
        if isinstance(refs,list):
            yield from (r for r in refs if isinstance(r,str))
        for key, value in expression.items():
            if key != 'references':
                yield from _references(value)
    elif isinstance(expression,list):
        for value in expression:
            yield from _references(value)


def _values(value):
    if isinstance(value,str):
        yield value
    elif isinstance(value,dict):
        for item in value.values():
            yield from _values(item)
    elif isinstance(value,list):
        for item in value:
            yield from _values(item)


def _attribute(value,path):
    if not path:
        yield value
    elif isinstance(value,list):
        for item in value:
            yield from _attribute(item,path)
    elif isinstance(value,dict) and path[0] in value:
        yield from _attribute(value[path[0]],path[1:])


def evaluate_plan(plan, *, policy=None, infracost=None):
    policy = policy or PlanPolicy()
    if not isinstance(plan,dict) or plan.get('format_version') not in ('1.0','1.1','1.2'):
        raise InvalidPlan('Supported Terraform plan format_version is 1.0–1.2')
    changes = plan.get('resource_changes')
    configuration = plan.get('configuration', {}).get('root_module')
    if not isinstance(changes,list) or len(changes) > 10000 or not isinstance(configuration,dict):
        raise InvalidPlan('Complete resource_changes and configuration.root_module are required')
    config = dict(_resources(configuration))
    if len(config) > 10000:
        raise InvalidPlan('Too many configured resources')
    records, issues, seen = [], [], set()
    def issue(code, address, message):
        # Do not expose for_each keys or raw before/after/secret values.
        issues.append(dict(code=code, severity='error', address=INDEX.sub('[*]',address), message=message))
    for resource in changes:
        if not isinstance(resource,dict):
            raise InvalidPlan('Invalid resource change')
        address, kind = resource.get('address'), resource.get('type')
        if not isinstance(address,str) or len(address)>512 or not ADDRESS.fullmatch(address) or address in seen or not isinstance(kind,str):
            raise InvalidPlan('Invalid or duplicate resource address')
        seen.add(address)
        mode = resource.get('mode')
        change = resource.get('change', {})
        actions = change.get('actions')
        if mode not in ('managed','data') or actions not in (['no-op'],['read'],['create'],['update'],['delete'],['delete','create'],['create','delete']):
            raise InvalidPlan('Unsupported resource action or mode')
        after = change.get('after')
        if actions != ['delete'] and not isinstance(after,dict):
            raise InvalidPlan('Resource after values are required')
        if mode == 'managed':
            records.append((address,kind,actions,after or {}))
            if 'delete' in actions and not policy.allow_deletes:
                issue('DESTRUCTIVE_CHANGE',address,'Deletion or replacement requires a separate approved workflow.')
            if any(a in actions for a in ('create','update')) and policy.required_tags:
                tags = (after or {}).get('tags') or (after or {}).get('labels') or {}
                unknown = change.get('after_unknown', {})
                if not isinstance(tags,dict) or any(not isinstance(tags.get(t),str) or not tags[t].strip() for t in policy.required_tags) or (isinstance(unknown,dict) and (unknown.get('tags') or unknown.get('labels'))):
                    issue('REQUIRED_TAGS',address,'Required ownership tags/labels must be known and nonempty in this plan.')
    bindings = {kind: set() for kind in ASSOCIATIONS}
    concrete = {kind: set() for kind in ASSOCIATIONS}
    for other_address, other_kind, other_actions, other_after in records:
        if other_actions == ['delete'] or INDEX.search(other_address):
            continue
        other = config.get(other_address, {})
        prefix = other_address.rsplit(other_kind+'.',1)[0]
        for target_kind, associations in ASSOCIATIONS.items():
            for expected_kind, attribute in associations:
                if other_kind != expected_kind:
                    continue
                for expression in _attribute(other.get('expressions',{}),attribute.split('.')):
                    bindings[target_kind].update(prefix+r for r in _references(expression))
                for value in _attribute(other_after,attribute.split('.')):
                    concrete[target_kind].update(_values(value))
    for address, kind, actions, after in records:
        if 'create' not in actions or kind not in ASSOCIATIONS:
            continue
        if INDEX.search(address):
            issue('INSTANCE_REVIEW_REQUIRED',address,'Indexed resource relationships require independent instance-level review.')
            continue
        configured = config.get(address)
        if not configured or configured.get('type') != kind:
            issue('ASSOCIATION_UNKNOWN',address,'Resource configuration is unavailable; association cannot be established.')
            continue
        attached = kind == 'aws_eip' and isinstance(after.get('instance'),str) and bool(after['instance'])
        resource_id = after.get('id')
        attached = attached or bool({address+'.id',address+'.self_link',address+'.address'} & bindings[kind])
        attached = attached or (isinstance(resource_id,str) and resource_id in concrete[kind])
        if not attached:
            issue('ORPHAN_RESOURCE',address,'No supported planned attachment is proven. Review intentional reservations outside this check.')
    cost = dict(status='unknown', currency='USD', monthly_increase_usd=None, source='user_supplied_infracost', verified_billing=False)
    if infracost is not None:
        if not isinstance(infracost,dict) or infracost.get('version') != '0.2':
            raise InvalidPlan('Supported Infracost JSON version is 0.2')
        if infracost.get('currency') == 'USD':
            current, previous = infracost.get('totalMonthlyCost'), infracost.get('pastTotalMonthlyCost')
            priced, current_sum, incomplete = set(), Decimal('0'), False
            for project in infracost.get('projects',[]):
                for row in project.get('breakdown',{}).get('resources',[]):
                    if isinstance(row.get('name'),str) and row.get('monthlyCost') is not None:
                        if row['name'] in priced:
                            raise InvalidPlan('Duplicate Infracost resource address')
                        current_sum += money(row['monthlyCost'])
                        priced.add(row['name'])
                    else:
                        incomplete = True
            affected = {a for a,_,actions,_ in records if any(x in actions for x in ('create','update','delete'))}
            # Deleted resources need past pricing evidence; v0.7 deliberately treats it as unknown.
            if (current is not None and previous is not None and affected <= priced and not incomplete
                    and abs(money(current)-current_sum)<=Decimal('0.01')
                    and not any('delete' in a for _,_,a,_ in records)):
                delta = money(current)-money(previous)
                cost.update(status='estimated',monthly_increase_usd=float(delta))
                if policy.max_monthly_increase_usd is not None and delta > policy.max_monthly_increase_usd:
                    issue('COST_BUDGET_EXCEEDED','plan','Estimated monthly increase exceeds the operator budget.')
    if policy.max_monthly_increase_usd is not None and cost['status'] == 'unknown':
        issue('COST_EVIDENCE_REQUIRED','plan','The configured budget requires complete supported USD Infracost evidence.')
    from app.commitment_arbitrage import commitment_firewall
    issues.extend(commitment_firewall(plan))
    return dict(schema_version='1', decision='fail' if issues else 'pass', issues=issues,
                resources_checked=len(records), cost=cost,
                limits=['Static supported association checks only; external, dynamic and indirect relationships need review.',
                        'Input provenance, Terraform execution, billing accuracy and merge protection require operator CI configuration.'])
