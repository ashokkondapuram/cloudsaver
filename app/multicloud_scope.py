"""Identity validation for newly supported cloud families, without weakening legacy IDs."""
import re
from app.resource_catalog import family

def validate(row,tenant):
    f=family(row)
    if not f or row.get('rule_id') not in (*f[4],'MULTICLOUD_INVENTORY'):raise ValueError('Rule and resource family do not agree')
    provider=f[0];rid=row.get('resource_id','');scope=row.get('scope_id');region=row.get('region')
    if not isinstance(rid,str) or len(rid)>2048 or any(v in rid for v in ('..','%','?','#','\\')):raise ValueError('Invalid resource identity')
    if row.get('subscription_id')!=scope:raise ValueError('Inconsistent scope identity')
    if provider=='aws':
        if not any(a['account_id']==scope and a['region']==region for a in tenant.get('aws_accounts',[])):raise ValueError('AWS source outside workspace')
        match=re.fullmatch(r'arn:aws:([a-z0-9-]+):([a-z0-9-]*):([0-9]*):([A-Za-z0-9_.:/+=@-]+)',rid)
        expected={'aws:ec2:instance':('ec2','instance/'),'aws:ec2:volume':('ec2','volume/'),'aws:ec2:natgateway':('ec2','natgateway/'),
            'aws:elbv2:loadbalancer':('elasticloadbalancing','loadbalancer/'),'aws:rds:cluster':('rds','cluster:'),'aws:rds:db':('rds','db:'),
            'aws:dynamodb:table':('dynamodb','table/'),'aws:elasticache:replication-group':('elasticache','replicationgroup:'),
            'aws:lambda:function':('lambda','function:'),'aws:ecs:service':('ecs','service/'),'aws:sagemaker:endpoint':('sagemaker','endpoint/'),
            'aws:bedrock:provisioned-throughput':('bedrock','provisioned-model/'),'aws:s3:bucket':('s3','')}
        service,prefix=expected.get(row['resource_type'],('',''))
        if not match or match[1]!=service or not match[4].startswith(prefix):raise ValueError('AWS ARN does not match its declared family')
        if service=='s3':
            if match[2] or match[3] or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]',match[4]):raise ValueError('Invalid S3 bucket ARN')
        elif match[2]!=region or match[3]!=scope:raise ValueError('AWS ARN outside configured account/region')
    elif provider=='gcp':
        configured=next((p for p in tenant.get('gcp_projects',[]) if p['project_id']==scope),None)
        if not configured or region not in configured['regions']:raise ValueError('GCP source outside configured project/region')
        kind=row['resource_type'];service,collection={
            'compute.googleapis.com/Instance':('compute','instances'),'compute.googleapis.com/Disk':('compute','disks'),
            'compute.googleapis.com/ForwardingRule':('compute','forwardingRules'),'compute.googleapis.com/RouterNat':('compute','routers'),
            'alloydb.googleapis.com/Cluster':('alloydb','clusters'),'bigquery.googleapis.com/Reservation':('bigqueryreservation','reservations'),
            'run.googleapis.com/Service':('run','services'),'redis.googleapis.com/Instance':('redis','instances'),
            'aiplatform.googleapis.com/Endpoint':('aiplatform','endpoints'),'sqladmin.googleapis.com/Instance':('sqladmin','instances')}.get(kind,('',''))
        prefix='//'+service+'.googleapis.com/projects/'+scope+'/'
        if not rid.startswith(prefix):raise ValueError('GCP resource service/project mismatch')
        rest=rid[len(prefix):].split('/')
        if any(not re.fullmatch(r'[A-Za-z0-9_.:-]+',p) for p in rest) or collection not in rest:raise ValueError('Invalid canonical GCP resource path')
        if 'zones' in rest:
            location=rest[rest.index('zones')+1].rsplit('-',1)[0]
        else:
            location=rest[rest.index('locations')+1] if 'locations' in rest else rest[rest.index('regions')+1] if 'regions' in rest else region
        if location!=region:raise ValueError('GCP resource location mismatch')
    else:raise ValueError('Not an expanded cloud identity')
