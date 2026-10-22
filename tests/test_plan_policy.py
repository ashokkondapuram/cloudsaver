"""Policy decisions and CLI behavior against Terraform-shaped plan artifacts."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.plan_policy import InvalidPlan, PlanPolicy, evaluate_plan, load_json


def resource(address,kind,*,actions=None,values=None,expressions=None):
    return (dict(address=address,type=kind,mode='managed',change=dict(actions=actions or ['create'],after={} if values is None else values)),
            dict(address=address,type=kind,expressions=expressions or {}))


def plan(*resources):
    return dict(format_version='1.2',resource_changes=[r[0] for r in resources],
                configuration={'root_module':{'resources':[r[1] for r in resources]}})


def codes(result):
    return {i['code'] for i in result['issues']}


def test_orphan_volume_fails_but_real_attachment_reference_passes():
    volume = resource('aws_ebs_volume.data','aws_ebs_volume')
    assert codes(evaluate_plan(plan(volume))) == {'ORPHAN_RESOURCE'}
    attachment = resource('aws_volume_attachment.data','aws_volume_attachment',
        expressions={'volume_id':{'references':['aws_ebs_volume.data.id','aws_ebs_volume.data']}})
    assert evaluate_plan(plan(volume,attachment))['decision'] == 'pass'
    # A reference in tags or to the volume's name does not establish attachment.
    for expressions in [{'tags':{'references':['aws_ebs_volume.data.id']}},
                        {'volume_id':{'references':['aws_ebs_volume.data.name']}}]:
        bad = resource('aws_volume_attachment.data','aws_volume_attachment',expressions=expressions)
        assert 'ORPHAN_RESOURCE' in codes(evaluate_plan(plan(volume,bad)))


def test_azure_nested_nic_association_and_concrete_ids():
    ip = resource('azurerm_public_ip.edge','azurerm_public_ip',values={'id':'/known/publicIP'})
    nic = resource('azurerm_network_interface.edge','azurerm_network_interface',expressions={
        'ip_configuration':[{'public_ip_address_id':{'references':['azurerm_public_ip.edge.id']}}]})
    assert evaluate_plan(plan(ip,nic))['decision'] == 'pass'
    nic = resource('azurerm_network_interface.edge','azurerm_network_interface',actions=['no-op'],
                   values={'ip_configuration':[{'public_ip_address_id':'/known/publicIP'}]})
    assert evaluate_plan(plan(ip,nic))['decision'] == 'pass'
    nic[0]['change']['actions'] = ['delete']
    nic[0]['change']['after'] = None
    assert codes(evaluate_plan(plan(ip,nic))) == {'DESTRUCTIVE_CHANGE','ORPHAN_RESOURCE'}


def test_module_local_relationships_and_indexed_instances_are_conservative():
    volume,attachment = resource('aws_ebs_volume.data','aws_ebs_volume'),resource('aws_volume_attachment.data','aws_volume_attachment',expressions={'volume_id':{'references':['aws_ebs_volume.data.id']}})
    nested = plan(volume,attachment)
    for change in nested['resource_changes']:
        change['address'] = 'module.storage.'+change['address']
    nested['configuration']['root_module']={'module_calls':{'storage':{'module':{'resources':[volume[1],attachment[1]]}}}}
    assert evaluate_plan(nested)['decision'] == 'pass'
    nested['resource_changes'][0]['address']='module.storage.aws_ebs_volume.data["sensitive-key"]'
    result=evaluate_plan(nested)
    assert 'INSTANCE_REVIEW_REQUIRED' in codes(result)
    assert 'sensitive-key' not in json.dumps(result)


def test_deletes_replacements_and_required_tags():
    item=resource('aws_instance.api','aws_instance',actions=['delete','create'],values={'tags':{'Owner':'ops'}})
    policy=PlanPolicy(required_tags=('Owner','CostCenter'))
    assert codes(evaluate_plan(plan(item),policy=policy)) == {'DESTRUCTIVE_CHANGE','REQUIRED_TAGS'}
    item[0]['change']['after']['tags']['CostCenter']='product'
    assert evaluate_plan(plan(item),policy=PlanPolicy(required_tags=('Owner',),allow_deletes=True))['decision']=='pass'
    item[0]['change']['after_unknown']={'tags':True}
    assert 'REQUIRED_TAGS' in codes(evaluate_plan(plan(item),policy=policy))


def cost(current='100',previous='50',*,name='aws_instance.api',currency='USD'):
    return dict(version='0.2',currency=currency,totalMonthlyCost=current,pastTotalMonthlyCost=previous,
                projects=[{'breakdown':{'resources':[{'name':name,'monthlyCost':current}]}}])


def test_infracost_budget_and_missing_evidence_fail_closed():
    document=plan(resource('aws_instance.api','aws_instance'))
    policy=PlanPolicy(max_monthly_increase_usd=Decimal('40'))
    result=evaluate_plan(document,policy=policy,infracost=cost())
    assert result['cost']['monthly_increase_usd']==50 and codes(result)=={'COST_BUDGET_EXCEEDED'}
    for incomplete in [None,cost(currency='EUR'),cost(name='unrelated.resource')]:
        result=evaluate_plan(document,policy=policy,infracost=incomplete)
        assert result['cost']['status']=='unknown' and codes(result)=={'COST_EVIDENCE_REQUIRED'}
    inconsistent=cost();inconsistent['totalMonthlyCost']='1'
    assert 'COST_EVIDENCE_REQUIRED' in codes(evaluate_plan(document,policy=policy,infracost=inconsistent))
    assert evaluate_plan(document,infracost=cost('50','100'))['cost']['monthly_increase_usd']==-50
    assert evaluate_plan(document)['cost']['monthly_increase_usd'] is None


@pytest.mark.parametrize('raw',[b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":1e400}',b'['*80+b'0'+b']'*80,b'x'*2000001])
def test_bounded_strict_json(raw):
    with pytest.raises(InvalidPlan):
        load_json(raw)


@pytest.mark.parametrize('bad',[{}, {'format_version':'2.0'}, {'format_version':'1.2','resource_changes':[]},
    {'format_version':'1.2','resource_changes':[{'address':'bad','type':'a','mode':'managed','change':{'actions':['mystery']}}],'configuration':{'root_module':{}}}])
def test_incomplete_plans_never_pass(bad):
    with pytest.raises(InvalidPlan):
        evaluate_plan(bad)


def test_raw_values_and_sensitive_plan_fields_are_not_echoed():
    document=plan(resource('aws_instance.api','aws_instance',values={'password':'never-echo-me'},actions=['delete','create']))
    document['variables']={'secret':{'value':'never-echo-me'}}
    result=evaluate_plan(document)
    assert 'never-echo-me' not in json.dumps(result)


def test_cli_exit_codes_and_sanitized_output(tmp_path):
    script=Path(__file__).resolve().parents[1]/'scripts/check_terraform_plan.py'
    path=tmp_path/'plan.json'
    for document,status in [(plan(resource('aws_instance.api','aws_instance')),0),
                            (plan(resource('aws_ebs_volume.data','aws_ebs_volume')),1),({},2)]:
        path.write_text(json.dumps(document))
        result=subprocess.run([sys.executable,str(script),str(path)],text=True,capture_output=True)
        assert result.returncode==status
        assert json.loads(result.stdout)['decision'] in ('pass','fail','invalid')
        assert not result.stderr
