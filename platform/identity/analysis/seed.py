"""Published analysis rule catalog seed (mirrors CloudSaver collectors)."""
RULE_SEED = (
    ('ORPHANED_DISK', 'azure', 'storage', 'microsoft.compute/disks', 'Unattached managed disk', 'cost'),
    ('UNASSOCIATED_PUBLIC_IP', 'azure', 'network', 'microsoft.network/publicipaddresses', 'Unassociated public IP', 'cost'),
    ('STOPPED_VM', 'azure', 'compute', 'microsoft.compute/virtualmachines', 'Stopped virtual machine', 'cost'),
    ('EMPTY_APP_SERVICE_PLAN', 'azure', 'application', 'microsoft.web/serverfarms', 'Empty App Service plan', 'cost'),
    ('ORPHANED_NIC', 'azure', 'network', 'microsoft.network/networkinterfaces', 'Unattached network interface', 'cost'),
    ('ORPHANED_NSG', 'azure', 'network', 'microsoft.network/networksecuritygroups', 'Unassociated network security group', 'cost'),
    ('IDLE_APP_GATEWAY', 'azure', 'network', 'microsoft.network/applicationgateways', 'Stopped or empty Application Gateway', 'cost'),
    ('AWS_UNATTACHED_EBS', 'aws', 'storage', 'ebs', 'Unattached EBS volume', 'cost'),
    ('AWS_UNASSOCIATED_EIP', 'aws', 'network', 'elastic-ip', 'Unassociated Elastic IP', 'cost'),
    ('AWS_IDLE_RDS', 'aws', 'database', 'rds', 'Stopped RDS instance', 'cost'),
    ('GCP_UNATTACHED_DISK', 'gcp', 'storage', 'disk', 'Unattached persistent disk', 'cost'),
    ('GCP_UNASSIGNED_ADDRESS', 'gcp', 'network', 'address', 'Unassigned static IP', 'cost'),
    ('GCP_IDLE_CLOUD_SQL', 'gcp', 'database', 'cloud-sql', 'Idle Cloud SQL instance', 'cost'),
    ('K8S_CPU_OVERSIZED', 'kubernetes', 'compute', 'pod', 'Oversized CPU requests', 'performance'),
    ('K8S_MEMORY_OVERSIZED', 'kubernetes', 'compute', 'pod', 'Oversized memory requests', 'performance'),
)
