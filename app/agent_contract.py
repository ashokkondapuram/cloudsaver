"""Bounded connector programs. Model output is data; authority comes from saved approval."""
import hashlib
import json
import os
import re
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Connector(Strict):
    id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,59}$')
    tenant_id: str
    provider: Literal['azure', 'aws', 'gcp', 'kubernetes']
    scope_id: str = Field(min_length=1, max_length=128)
    kind: Literal['azure_arm', 'http_json']
    operations: list[str] = Field(min_length=1, max_length=8)
    endpoint: str | None = Field(default=None,max_length=2048)
    token_env: str | None = Field(default=None,max_length=100)

    @field_validator('tenant_id')
    @classmethod
    def tenant(cls, value): return str(UUID(value))


def connectors():
    raw = json.loads(os.getenv('CLOUDSAVER_AGENT_CONNECTORS', '[]'))
    if not isinstance(raw, list) or len(raw) > 100: raise ValueError('Invalid connector catalog')
    result = [Connector.model_validate(item) for item in raw]
    if len({c.id for c in result}) != len(result): raise ValueError('Duplicate connector IDs')
    for c in result:
        if c.kind == 'azure_arm':
            if c.provider != 'azure' or not set(c.operations) <= {'resource.inspect', 'tags.merge'} or c.endpoint or c.token_env:
                raise ValueError('Invalid Azure connector')
            UUID(c.scope_id)
        else:
            u = urlsplit(c.endpoint or '')
            if (c.operations != ['action.submit'] or u.scheme != 'https' or not u.hostname or u.username or u.password
                    or u.query or u.fragment or not re.fullmatch(r'CLOUDSAVER_AGENT_CONNECTOR_[A-Z0-9_]{1,60}', c.token_env or '')):
                raise ValueError('HTTP connectors require a fixed HTTPS endpoint and secret reference')
    return result


class Step(Strict):
    connector_id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,59}$')
    operation: Literal['resource.inspect', 'tags.merge', 'action.submit']
    arguments: dict = Field(default_factory=dict)
    purpose: str = Field(min_length=1, max_length=500)
    verification: str = Field(min_length=1, max_length=500)
    rollback: str = Field(min_length=1, max_length=500)


class Plan(Strict):
    summary: str = Field(min_length=1, max_length=1000)
    steps: list[Step] = Field(min_length=1, max_length=8)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()


def render_code(plan):
    # No free-form model string is inserted into executable source.
    lines = ["type AgentContext = { call(index: number): Promise<unknown> };",
             "export async function run(ctx: AgentContext): Promise<unknown[]> {", "  const results: unknown[] = [];"]
    lines += [f"  results.push(await ctx.call({i}));" for i in range(len(plan['steps']))]
    return '\n'.join(lines + ['  return results;', '}', ''])


def validate_plan(value, task, catalog):
    plan = Plan.model_validate(value).model_dump()
    selected = {c.id: c for c in catalog if c.id in task['payload']['connector_ids']}
    inspected = set()
    writes = 0
    for step in plan['steps']:
        c = selected.get(step['connector_id'])
        if not c or c.tenant_id != task['tenant_id'] or c.provider != task['provider'] or c.scope_id != task['scope_id']:
            raise ValueError('Connector is outside the task grant')
        if step['operation'] not in c.operations: raise ValueError('Operation is disabled')
        if c.kind=='http_json':raise ValueError('Data governance prohibits exporting task/resource data through generic HTTP actions.')
        from app.data_governance import safe_action_data
        safe_action_data(step['arguments'])
        args = step['arguments']
        if step['operation'] == 'resource.inspect':
            if args: raise ValueError('Inspection takes no model arguments')
            inspected.add(c.id)
        elif step['operation'] == 'tags.merge':
            tags = args.get('tags')
            if set(args) != {'tags'} or not isinstance(tags, dict) or not 1 <= len(tags) <= 10 or c.id not in inspected:
                raise ValueError('Tag changes require prior inspection and explicit tags')
            for key, val in tags.items():
                if (not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', key) or key.lower().startswith(('hidden', 'microsoft', 'azure'))
                        or not isinstance(val, str) or not 1 <= len(val) <= 256 or any(ord(ch) < 32 for ch in val)):
                    raise ValueError('Unsupported tag key/value')
            writes += 1
        else:
            if set(args) != {'body'} or not isinstance(args['body'], dict) or len(canonical(args).encode()) > 4000:
                raise ValueError('HTTP action requires a bounded explicit JSON body')
            writes += 1
    if writes > 1: raise ValueError('Split independent changes into separately approved tasks')
    if len(canonical(plan).encode()) > 16000: raise ValueError('Plan exceeds review limit')
    return plan


def binding(c):
    # Secret names, endpoint, operations and ownership are approval-bound; secret values are never returned.
    return c.model_dump()


def program_hash(task, plan, catalog):
    selected = {s['connector_id'] for s in plan['steps']}
    return digest(dict(schema=2,data_governance_contract=1, task_id=task['id'], tenant_id=task['tenant_id'], provider=task['provider'],
        scope_id=task['scope_id'], resource_id=task['resource_id'], plan=plan, code=render_code(plan),
        connectors=[binding(c) for c in sorted(catalog, key=lambda c: c.id) if c.id in selected]))
