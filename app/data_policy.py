"""Data-use contract, packaged in both independently deployed policy consumers."""
import copy
import re
from datetime import datetime
from uuid import UUID

PURPOSES = ('assessment','resource_assessment','followup','agent_planning')
DEFAULT_DATA_GOVERNANCE = dict(environment_id='',azure_tenant_id='',response_retention_days=7,
    allow_training=False,allow_cross_tenant_reuse=False,allow_external_action_data=False,processors=[])
PROCESSOR_FIELDS = {'workspace_id','target_id','azure_resource_id','endpoint_url','deployment_name','purposes','review_reference',
                    'review_expires_at','provider_controls_reviewed'}


def validate_data_governance(value):
    if not isinstance(value,dict) or set(value)!=set(DEFAULT_DATA_GOVERNANCE): raise ValueError('Provide the complete data-use policy.')
    for flag in ('allow_training','allow_cross_tenant_reuse','allow_external_action_data'):
        if value[flag] is not False: raise ValueError('Training, cross-tenant reuse and external action data transfer are prohibited.')
    if type(value['response_retention_days']) is not int or not 1<=value['response_retention_days']<=30: raise ValueError('Response retention must be 1–30 days.')
    if not isinstance(value['environment_id'],str) or (value['environment_id'] and not re.fullmatch(r'[a-z][a-z0-9-]{1,59}',value['environment_id'])): raise ValueError('Invalid environment identifier.')
    if value['azure_tenant_id']:
        if not isinstance(value['azure_tenant_id'],str) or str(UUID(value['azure_tenant_id']))!=value['azure_tenant_id']: raise ValueError('Use a canonical Azure tenant UUID.')
    elif value['azure_tenant_id']!='': raise ValueError('Invalid Azure tenant identifier.')
    rows=value['processors']
    if not isinstance(rows,list) or len(rows)>50: raise ValueError('At most 50 processing approvals are supported.')
    if rows and not (value['environment_id'] and value['azure_tenant_id']): raise ValueError('Register the owning environment and Azure tenant first.')
    seen=set()
    for row in rows:
        if not isinstance(row,dict) or set(row)!=PROCESSOR_FIELDS: raise ValueError('Invalid processing approval fields.')
        if not isinstance(row['workspace_id'],str) or str(UUID(row['workspace_id']))!=row['workspace_id']: raise ValueError('Invalid workspace UUID.')
        if not isinstance(row['target_id'],str) or not re.fullmatch(r'[a-z0-9-]{1,40}',row['target_id']): raise ValueError('Invalid target ID.')
        if not isinstance(row['azure_resource_id'],str) or not re.fullmatch(r'/subscriptions/[a-fA-F0-9-]{36}/resourceGroups/[A-Za-z0-9_.()-]{1,90}/providers/Microsoft.CognitiveServices/accounts/[A-Za-z0-9-]{1,64}',row['azure_resource_id']): raise ValueError('Register an exact Azure AI account resource ID.')
        if not isinstance(row['endpoint_url'],str) or not re.fullmatch(r'https://[a-z0-9][a-z0-9-]{1,62}\.(?:openai\.azure\.com|cognitiveservices\.azure\.com|services\.ai\.azure\.com)/?',row['endpoint_url']):raise ValueError('Register an exact Azure processing endpoint.')
        if not isinstance(row['deployment_name'],str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,160}',row['deployment_name']):raise ValueError('Register an exact approved deployment.')
        if not isinstance(row['purposes'],list) or not row['purposes'] or len(set(row['purposes']))!=len(row['purposes']) or not set(row['purposes'])<=set(PURPOSES): raise ValueError('Select explicit supported processing purposes.')
        if not isinstance(row['review_reference'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{2,119}',row['review_reference']): raise ValueError('A bounded internal review reference is required.')
        reviewed=datetime.fromisoformat(row['review_expires_at'].replace('Z','+00:00')) if isinstance(row['review_expires_at'],str) else None
        if not reviewed or reviewed.tzinfo is None: raise ValueError('Review expiry must include a timezone.')
        if row['provider_controls_reviewed'] is not True: raise ValueError('Record a completed review of provider retention, training and processing location.')
        key=(row['workspace_id'],row['target_id'])
        if key in seen: raise ValueError('Duplicate workspace/processor approval.')
        seen.add(key)
    return copy.deepcopy(value)
