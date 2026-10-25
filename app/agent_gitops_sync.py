"""Approval-bound IaC review artifacts. A draft PR is not proof of deployed parity."""
from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import UUID

from app.agent_contract import digest, program_hash, validate_plan
from app.cloud_scope import validate_finding_scope
from app.gitops import GitHubApp, GitOpsFailure
from app.telemetry_contract import moment
from app.v150_store import WorkflowStore, WorkflowConflict


TERRAFORM_RESOURCE_MAP = {
    'microsoft.compute/disks':'azurerm_managed_disk',
    'microsoft.network/publicipaddresses':'azurerm_public_ip','microsoft.network/networkinterfaces':'azurerm_network_interface',
    'microsoft.network/networksecuritygroups':'azurerm_network_security_group','microsoft.network/applicationgateways':'azurerm_application_gateway',
    'microsoft.web/serverfarms':'azurerm_service_plan','microsoft.storage/storageaccounts':'azurerm_storage_account',
    'aws:ec2:volume':'aws_ebs_volume','aws:ec2:instance':'aws_instance','aws:rds:dbinstance':'aws_db_instance',
    'aws:ec2:eip':'aws_eip','aws:ec2:natgateway':'aws_nat_gateway','aws:elasticloadbalancing:loadbalancer':'aws_lb',
    'aws:dynamodb:table':'aws_dynamodb_table','aws:lambda:function':'aws_lambda_function','aws:s3:bucket':'aws_s3_bucket',
    'compute.googleapis.com/disk':'google_compute_disk','compute.googleapis.com/instance':'google_compute_instance',
    'compute.googleapis.com/address':'google_compute_address','sqladmin.googleapis.com/instance':'google_sql_database_instance',
    'run.googleapis.com/service':'google_cloud_run_v2_service','kubernetes.io/deployment':'kubernetes_deployment_v1',
    'kubernetes.io/statefulset':'kubernetes_stateful_set_v1','kubernetes.io/daemonset':'kubernetes_daemon_set_v1'}


def generate_synchronized_terraform_patch(scan_record, resource_id, action_spec, tenant):
    if scan_record.get('status')!='completed' or scan_record.get('data_origin')=='legacy_synthetic':
        raise ValueError('A completed live resource observation is required')
    found=next((r for r in [*scan_record.get('inventory',[]),*scan_record.get('findings',[])] if r.get('resource_id')==resource_id),None)
    if found is None: raise ValueError('Resource is not in the owned scan')
    validate_finding_scope(found,tenant)
    kind=TERRAFORM_RESOURCE_MAP.get(found['resource_type'].lower())
    if not kind: raise ValueError('This resource type has no reviewed Terraform mapping')
    if action_spec.get('patch_mode')!='tags_sync':
        raise ValueError('Only approved tag/label/annotation synchronization is executable; SKU/deletion changes require a separate reviewed adapter')
    attributes=action_spec['attributes']
    if not isinstance(attributes,dict) or len(attributes)!=1 or next(iter(attributes)) not in ('tags','labels','annotations'):
        raise ValueError('A single exact approved metadata merge is required')
    field=next(iter(attributes));values=attributes[field]
    if not isinstance(values,dict) or not values: raise ValueError('Metadata patch is empty')
    label='review_'+hashlib.sha256(resource_id.encode()).hexdigest()[:16]
    # A fragment is deliberately stored outside live Terraform roots. Complete
    # provider configuration and the repository's existing metadata expression
    # must be reviewed in CI; replacing unknown tags would create data loss.
    attributes=({'metadata':[{'annotations':values}]} if field=='annotations' else
                {'settings':[{'user_labels':values}]} if kind=='google_sql_database_instance' else {field:values})
    fragment={'resource':{kind:{label:attributes}}}
    return dict(resource_type=kind,resource_address=kind+'.'+label,
                hcl=json.dumps(fragment,indent=2,sort_keys=True)+'\n',format='terraform-json-review-fragment',
                metadata_merge=values,requires_repository_integration=True,
                warning='Merge these exact approved metadata changes into the existing resource configuration. Preserve other metadata. This is not a verified Terraform plan or an apply authorization.')


def journal_evidence(content):
    # Keep replay fences and linkage, not a second ungoverned copy of resource
    # metadata. The exact approved artifact remains in the governed task/review.
    fields=('agent_task_id','plan_hash','step_evidence_digest','target_id','repository',
            'parity_verified','state','fingerprint','result','automatic_retry')
    return {k:content[k] for k in fields if k in content}


def build_synchronized_agent_gitops_bundle(task, tenant, scan, config, catalog, *, publish=False, store=None, client=None):
    if task['tenant_id']!=tenant['tenant_id'] or task['scan_id']!=scan['scan_id']:
        raise ValueError('Task and scan ownership do not match')
    payload=task['payload'];plan=validate_plan(payload.get('plan'),task,catalog)
    expected=program_hash(task,plan,catalog)
    if payload.get('plan_hash')!=expected: raise ValueError('Task plan or connector grant changed')
    sync_steps=[(i,s) for i,s in enumerate(plan['steps']) if s['operation']=='gitops.terraform.sync']
    if len(sync_steps)!=1: raise ValueError('The reviewed task does not contain one paired GitOps step')
    index,step=sync_steps[0]
    connector=next(c for c in catalog if c.id==step['connector_id'])
    target=config.target(tenant['tenant_id'],connector.target_id)
    artifact=generate_synchronized_terraform_patch(scan,task['resource_id'],step['arguments'],tenant)
    evidence=[]
    if publish:
        approval=payload.get('approval') or {}
        expiry=moment(approval.get('expires_at'))
        if not expiry or expiry<=datetime.now(timezone.utc) or approval.get('plan_hash')!=expected:
            raise ValueError('A current saved human approval is required')
        if task['state']!='running' or payload['steps'][index]['state']!='started':
            raise ValueError('GitOps publishing requires its single-use worker step permit')
        for previous in payload['steps'][:index]:
            result=previous.get('result') or {}
            value=result.get('evidence_digest')
            if previous['state']!='succeeded' or not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{64}',value) or set(value)=={'f'}:
                raise ValueError('Successful recorded inspection/action evidence is required')
            evidence.append(value)
        if not config.enabled: raise ValueError('GitHub publishing is disabled')
    policy=dict(decision='review_required',projection_only=True,automatic_apply=False,
                reasons=['Repository CI must produce and verify the real Terraform plan; the approved runtime metadata merge is the only modeled mutation.'])
    content=dict(agent_task_id=task['id'],plan_hash=expected,step_evidence_digest=digest(evidence) if evidence else None,
                 target_id=target['target_id'],repository=target['repository'],artifact=artifact,policy=policy,
                 parity_verified=False,state='awaiting_repository_review' if publish else 'preview')
    fingerprint=digest(content)
    content['fingerprint']=fingerprint
    if not publish: return content
    workflows=WorkflowStore(store)
    key=digest([task['id'],expected,target])
    run=workflows.begin(tenant['tenant_id'],'agent_gitops_syncs',key,journal_evidence(content),once=True)
    review_id=str(UUID(fingerprint[:32]));branch='cloudsaver/agent-'+fingerprint[:24]
    package=dict(review_id=review_id,scan_id=task['scan_id'],target_id=target['target_id'],repository=target['repository'],
        branch=branch,fingerprint=fingerprint,title='Review approved agent metadata synchronization',
        body=f'Agent task `{task["id"]}`. Approved plan `{expected}`. Evidence `{content["step_evidence_digest"]}`.\n\n'
             'Review fragment only: integrate with existing IaC and verify CI before merge. Runtime/IaC parity is not yet verified.\n\n'
             f'<!-- cloudsaver-review:{review_id} -->',
        files={f'cloudsaver/agent-reviews/{task["id"]}/metadata.tf.json':artifact['hcl'],
               f'cloudsaver/agent-reviews/{task["id"]}/evidence.json':json.dumps(content,indent=2,sort_keys=True)})
    try:
        result=(client or GitHubApp(config.app_id)).publish(target,package)
        if result.get('state')!='open':raise GitOpsFailure('Repository review is no longer open')
    except Exception:
        content.update(state='needs_reconciliation',automatic_retry=False)
        workflows.finish(tenant['tenant_id'],'agent_gitops_syncs',run,'needs_reconciliation',journal_evidence(content))
        raise GitOpsFailure('Paired repository outcome is uncertain; reconcile it without replaying cloud actions') from None
    content.update(result=result,state='awaiting_repository_review')
    workflows.finish(tenant['tenant_id'],'agent_gitops_syncs',run,'open',journal_evidence(content))
    return content
