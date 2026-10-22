"""Generate an import-only Terraform review package without guessed resource settings."""
import hashlib
import json
from uuid import UUID

from app.remediation import RESOURCE_ID

SUPPORTED = {'ORPHANED_DISK': ('microsoft.compute', 'disks', 'azurerm_managed_disk'),
             'UNASSOCIATED_PUBLIC_IP': ('microsoft.network', 'publicipaddresses', 'azurerm_public_ip')}


def generate_terraform_hcl(scan_record, selected_resource_ids, tenant_id, authorized_subscription_ids):
    if scan_record.get('mode') != 'azure' or scan_record.get('status') != 'completed':
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
            raise ValueError('Only selected live disk/IP findings support Terraform export')
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
