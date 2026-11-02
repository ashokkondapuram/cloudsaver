"""Published analysis rule catalog seed (mirrors CloudSaver collectors)."""
RULE_SEED = (
    ('ORPHANED_NIC', 'azure', 'network', 'microsoft.network/networkinterfaces', 'Orphaned network interface', 'cost'),
    ('ORPHANED_NSG', 'azure', 'network', 'microsoft.network/networksecuritygroups', 'Unassociated network security group', 'cost'),
    ('AWS_UNATTACHED_EBS', 'aws', 'storage', 'ebs', 'Unattached EBS volume', 'cost'),
    ('AWS_UNASSOCIATED_EIP', 'aws', 'network', 'elastic-ip', 'Unassociated Elastic IP', 'cost'),
    ('AWS_IDLE_RDS', 'aws', 'database', 'rds', 'Stopped RDS instance', 'cost'),
    ('GCP_UNATTACHED_DISK', 'gcp', 'storage', 'disk', 'Unattached persistent disk', 'cost'),
    ('GCP_UNASSIGNED_ADDRESS', 'gcp', 'network', 'address', 'Unassigned static IP', 'cost'),
    ('GCP_IDLE_CLOUD_SQL', 'gcp', 'database', 'cloud-sql', 'Idle Cloud SQL instance', 'cost'),
)
from identity.analysis.contracts import DEFINITIONS
RULE_SEED += tuple((rid, 'azure', category, kind, name, 'cost') for rid, category, kind, name, _ in DEFINITIONS)
from identity.analysis.kubernetes import DEFINITIONS as KUBERNETES_RULES
RULE_SEED += tuple((rid, 'kubernetes', category, kind, name, pillar) for rid,category,kind,name,pillar in KUBERNETES_RULES)

from identity.analysis.multicloud import definitions
_existing={r[0] for r in RULE_SEED}
RULE_SEED += tuple(row[:6] for row in definitions() if row[0] not in _existing)
