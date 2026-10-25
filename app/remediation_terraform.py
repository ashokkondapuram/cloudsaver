"""Generate an import-only Terraform review package without guessed resource settings."""
import hashlib
import json
from uuid import UUID

from app.remediation import RESOURCE_ID

SUPPORTED = {
    'ORPHANED_DISK': ('microsoft.compute', 'disks', 'azurerm_managed_disk'),
    'UNASSOCIATED_PUBLIC_IP': ('microsoft.network', 'publicipaddresses', 'azurerm_public_ip'),
    'ORPHANED_NIC': ('microsoft.network', 'networkinterfaces', 'azurerm_network_interface'),
    'ORPHANED_NSG': ('microsoft.network', 'networksecuritygroups', 'azurerm_network_security_group'),
    'IDLE_APP_GATEWAY': ('microsoft.network', 'applicationgateways', 'azurerm_application_gateway'),
}


def generate_terraform_hcl(scan_record, selected_resource_ids, tenant_id, authorized_subscription_ids):
    if scan_record.get('mode') != 'azure' or scan_record.get('status') != 'completed' or scan_record.get('data_origin') == 'legacy_synthetic':
        raise ValueError('Terraform export requires a completed live Azure scan')
    if not 1 <= len(selected_resource_ids) <= 50 or len({s.lower() for s in selected_resource_ids}) != len(selected_resource_ids):
        raise ValueError('Select 1–50 unique resource IDs')
    tenant_id = str(UUID(tenant_id))
    authorized = {str(UUID(s)) for s in authorized_subscription_ids}
    findings = {f['resource_id'].lower(): f for f in scan_record['findings']}
    selections = []
    for rid in selected_resource_ids:
        match = RESOURCE_ID.fullmatch(rid)
        finding = findings.get(rid.lower())
        if not match or not finding or finding['rule_id'] not in SUPPORTED:
            raise ValueError('Only selected supported findings support Terraform export')
        # Use the same strictly validated ARM identity grammar as Bash remediation.
        parts = rid.split('/')
        sub = str(UUID(parts[2]))
        provider, kind = parts[6].lower(), parts[7].lower()
        expected_provider, expected_type, tf_type = SUPPORTED[finding['rule_id']]
        if sub not in authorized or str(UUID(finding['subscription_id'])) != sub or (provider, kind) != (expected_provider, expected_type):
            raise ValueError('Resource identity is inconsistent with the authorized finding')
        label = 'review_' + hashlib.sha256(rid.lower().encode()).hexdigest()[:16]
        selections.append((rid, sub, tf_type, label))
    lines = ['# CloudSaver Terraform import review. No deletion or snapshot creation is generated.',
             '# Use a NEW isolated working directory and read-only Azure credentials.',
             '# terraform init',
             '# terraform plan -generate-config-out=reviewed-resources.tf -out=import-review.tfplan',
             '# Review generated settings and plan. This file is not a deletion approval.',
             '# Verify independent backups and retention before designing any separate remediation.',
             'terraform {', '  required_version = ">= 1.5.0"', '  required_providers {',
             '    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }', '  }', '}', '']
    for sub in sorted({x[1] for x in selections}):
        alias = 'sub_' + sub.replace('-', '')
        lines.extend(['provider "azurerm" {', f'  alias = {json.dumps(alias)}',
                      f'  tenant_id = {json.dumps(tenant_id)}', f'  subscription_id = {json.dumps(sub)}',
                      '  resource_provider_registrations = "none"', '  features {}', '}', ''])
    for rid, sub, tf_type, label in selections:
        lines.extend(['import {', f'  provider = azurerm.sub_{sub.replace("-", "")}',
                      f'  to = {tf_type}.{label}', f'  id = {json.dumps(rid)}', '}', ''])
    return '\n'.join(lines)


def generate_cloud_terraform_hcl(scan_record, selected_resource_ids, workspace):
    """Import-only exports for an owned live scan; one provider per review file."""
    from app.cloud_scope import validate_finding_scope
    if scan_record.get('mode') not in ('azure', 'multi-cloud') or scan_record.get('status') != 'completed' or scan_record.get('data_origin') == 'legacy_synthetic':
        raise ValueError('Terraform export requires a completed live scan')
    if not 1 <= len(selected_resource_ids) <= 50 or len(set(selected_resource_ids)) != len(selected_resource_ids):
        raise ValueError('Select 1–50 unique resource IDs')
    by_id = {f['resource_id']: f for f in scan_record['findings']}
    selected = []
    for rid in selected_resource_ids:
        item = by_id.get(rid)
        if item is None:
            raise ValueError('Selected resource does not belong to this scan')
        validate_finding_scope(item, workspace)
        selected.append(item)
    providers = {f.get('cloud_provider', 'azure') for f in selected}
    if len(providers) != 1:
        raise ValueError('Select one cloud provider per Terraform review file')
    provider = providers.pop()
    if provider == 'azure':
        return generate_terraform_hcl(dict(scan_record, mode='azure'), selected_resource_ids,
                                      workspace['tenant_id'], workspace['subscription_ids'])
    if provider not in ('aws', 'gcp'):
        raise ValueError('Kubernetes rightsizing requires workload review; Terraform import is unsupported')
    name, version = ('aws', '~> 5.0') if provider == 'aws' else ('google', '~> 6.0')
    lines = ['# CloudSaver import-only review: no deletion, apply or configuration is generated.',
             '# Use a NEW isolated directory with read-only credentials.',
             '# terraform init', '# terraform plan -generate-config-out=reviewed-resources.tf -out=import-review.tfplan',
             '# Independently review generated configuration, dependencies, backups and the plan.',
             'terraform {', '  required_version = ">= 1.5.0"', '  required_providers {',
             f'    {name} = {{ source = "hashicorp/{name}", version = {json.dumps(version)} }}', '  }', '}', '']
    aliases, imports = {}, []
    aws_types = {'AWS_UNATTACHED_EBS': ('aws:ec2:volume', 'aws_ebs_volume'),
                 'AWS_UNASSOCIATED_EIP': ('aws:ec2:elastic-ip', 'aws_eip'),
                 'AWS_IDLE_RDS': ('aws:rds:db', 'aws_db_instance')}
    for item in selected:
        rid, scope, region = item['resource_id'], item['scope_id'], item.get('region')
        key = scope, region
        alias = 'scope_' + hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16]
        aliases[key] = alias
        if provider == 'aws':
            mapping = aws_types.get(item['rule_id'])
            if not mapping or item['resource_type'] != mapping[0]:
                raise ValueError('Unsupported or inconsistent AWS Terraform finding')
            tf_type, import_id = mapping[1], item['resource_name']
            # Never trust a separately supplied resource_name as an import identity.
            suffix = rid.rsplit('/', 1)[-1] if item['rule_id'] != 'AWS_IDLE_RDS' else rid.rsplit(':', 1)[-1]
            if import_id != suffix:
                raise ValueError('AWS import identity does not match the selected resource')
        else:
            path = rid.split('.googleapis.com/', 1)[1]
            if item['rule_id'] == 'GCP_UNATTACHED_DISK' and item['resource_type'] == 'compute.googleapis.com/Disk' and '/disks/' in path:
                tf_type = 'google_compute_region_disk' if '/regions/' in path else 'google_compute_disk'
            elif item['rule_id'] == 'GCP_UNASSIGNED_ADDRESS' and item['resource_type'] == 'compute.googleapis.com/Address' and '/regions/' in path and '/addresses/' in path:
                tf_type = 'google_compute_address'
            elif item['rule_id'] == 'GCP_IDLE_CLOUD_SQL' and item['resource_type'] == 'sqladmin.googleapis.com/Instance' and '/instances/' in path:
                tf_type = 'google_sql_database_instance'
            else:
                raise ValueError('Unsupported or inconsistent GCP Terraform finding')
            import_id = path
        label = 'review_' + hashlib.sha256((rid + '|' + item['rule_id']).encode()).hexdigest()[:16]
        imports.append((tf_type, label, alias, import_id))
    for (scope, region), alias in sorted(aliases.items(), key=lambda x: x[1]):
        lines.extend([f'provider "{name}" {{', f'  alias = {json.dumps(alias)}'])
        if provider == 'aws':
            lines.extend([f'  region = {json.dumps(region)}', f'  allowed_account_ids = [{json.dumps(scope)}]'])
        else:
            lines.append(f'  project = {json.dumps(scope)}')
            if region:
                lines.append(f'  region = {json.dumps(region)}')
        lines.extend(['}', ''])
    for tf_type, label, alias, import_id in imports:
        lines.extend(['import {', f'  provider = {name}.{alias}', f'  to = {tf_type}.{label}',
                      f'  id = {json.dumps(import_id)}', '}', ''])
    return '\n'.join(lines)
