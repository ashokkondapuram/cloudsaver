# Managed identity roles and trust

CloudSaver has one user-assigned managed identity. That identity has **no direct
permissions on customer resources**: it only proves who CloudSaver is. Each cloud
trusts it through federation, and read-only roles grant the scan permissions. The
scanners never write, delete or change anything, so no role below includes a write action.

Placeholders used below:

| Placeholder | Value |
| --- | --- |
| `<HOST_TENANT_ID>` | Entra tenant that owns the managed identity |
| `<MI_CLIENT_ID>` | Managed identity client ID (`AZURE_MANAGED_IDENTITY_CLIENT_ID`) |
| `<MI_OBJECT_ID>` | Managed identity object (principal) ID, the `sub` claim of its tokens |
| `<CLOUDSAVER_TENANT_ID>` | Workspace ID shown in Settings > Cloud accounts |

Token facts that every trust rule depends on:

- Issuer (`iss`): `https://login.microsoftonline.com/<HOST_TENANT_ID>/v2.0`
- Audience (`aud`): `api://AzureADTokenExchange`
- Subject (`sub`): `<MI_OBJECT_ID>`

## 1. The managed identity itself (CloudSaver's subscription)

| Scope | Role | Why |
| --- | --- | --- |
| CloudSaver container registry | `AcrPull` | Only if the hosting platform pulls images with this identity |
| Customer resources | None | Access always goes through the roles below |

Do not give this identity `Reader`, `Contributor` or any Microsoft Graph permission.
Attach it to the scanner-service, scan-worker and delivery-dispatcher containers.

## 2. Azure (customer tenants)

### Federated mode (`CLOUDSAVER_AZURE_ACCESS=federated`, default)

CloudSaver's tenant:

1. Create a **multi-tenant** app registration, for example "CloudSaver Reader". It
   needs no client secret, certificate or API permissions.
2. Add a federated identity credential to the app:
   - Issuer: `https://login.microsoftonline.com/<HOST_TENANT_ID>/v2.0`
   - Subject: `<MI_OBJECT_ID>`
   - Audience: `api://AzureADTokenExchange`
3. Set `CLOUDSAVER_AZURE_APP_CLIENT_ID` to the app's client ID.

Each customer tenant:

1. A Global or Privileged Role Administrator grants admin consent, which creates
   the app's service principal:
   `https://login.microsoftonline.com/<CUSTOMER_TENANT_ID>/adminconsent?client_id=<APP_CLIENT_ID>`
2. Assign a read role to that service principal on **each selected subscription**:
   - Simplest: built-in **Reader**.
   - Least privilege: the custom role below, which covers exactly the resource
     types the scan queries through Azure Resource Graph.

```json
{
  "Name": "CloudSaver Inventory Reader",
  "Description": "Read-only inventory for CloudSaver waste findings.",
  "Actions": [
    "Microsoft.Resources/subscriptions/read",
    "Microsoft.ResourceGraph/resources/read",
    "Microsoft.Compute/disks/read",
    "Microsoft.Compute/virtualMachines/read",
    "Microsoft.Network/publicIPAddresses/read",
    "Microsoft.Network/networkInterfaces/read",
    "Microsoft.Network/networkSecurityGroups/read",
    "Microsoft.Network/applicationGateways/read",
    "Microsoft.Web/serverfarms/read"
  ],
  "NotActions": [],
  "DataActions": [],
  "AssignableScopes": ["/subscriptions/<SUBSCRIPTION_ID>"]
}
```

```bash
az role definition create --role-definition cloudsaver-reader.json
az role assignment create --assignee <APP_CLIENT_ID> \
  --role "CloudSaver Inventory Reader" --scope /subscriptions/<SUBSCRIPTION_ID>
```

Resource Graph only returns resources the caller can read. A missing action hides
that resource type rather than failing the scan, so add the matching `*/read`
action when a new rule is added.

### Direct mode (`CLOUDSAVER_AZURE_ACCESS=direct`)

For subscriptions in CloudSaver's own tenant only, assign the same role to the
managed identity itself on each subscription. Skip the app registration.

## 3. AWS

### CloudSaver hub account (once)

1. Create an IAM OIDC identity provider:
   - Provider URL: `https://login.microsoftonline.com/<HOST_TENANT_ID>/v2.0`
   - Audience: `api://AzureADTokenExchange`
2. Create the hub role, for example `CloudSaverHub`, and set
   `CLOUDSAVER_AWS_HUB_ROLE_ARN` to its ARN. Keep the maximum session duration at
   1 hour.

Hub role trust policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::<HUB_ACCOUNT_ID>:oidc-provider/login.microsoftonline.com/<HOST_TENANT_ID>/v2.0"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "login.microsoftonline.com/<HOST_TENANT_ID>/v2.0:aud": "api://AzureADTokenExchange",
        "login.microsoftonline.com/<HOST_TENANT_ID>/v2.0:sub": "<MI_OBJECT_ID>"
      }
    }
  }]
}
```

Hub role permissions (it can only assume customer reader roles):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "sts:AssumeRole",
    "Resource": "arn:aws:iam::*:role/CloudSaverReader"
  }]
}
```

### Each customer account

Create a role, for example `CloudSaverReader`, and enter its ARN in Settings >
Cloud accounts.

Trust policy. The external ID is the customer's CloudSaver workspace ID. CloudSaver
always sends it, so the role can't be used for another workspace:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "AWS": "arn:aws:iam::<HUB_ACCOUNT_ID>:role/CloudSaverHub" },
    "Action": "sts:AssumeRole",
    "Condition": { "StringEquals": { "sts:ExternalId": "<CLOUDSAVER_TENANT_ID>" } }
  }]
}
```

Permissions policy. `sts:GetCallerIdentity` needs no grant. The region condition is
optional and should list the regions configured for the account:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["ec2:DescribeVolumes", "ec2:DescribeAddresses", "rds:DescribeDBInstances"],
    "Resource": "*",
    "Condition": { "StringEquals": { "aws:RequestedRegion": ["us-east-1"] } }
  }]
}
```

## 4. Google Cloud

### CloudSaver project (once)

1. Enable the IAM, Security Token Service and IAM Service Account Credentials APIs.
2. Create a workload identity pool and an OIDC provider that trusts only the
   managed identity. Set `CLOUDSAVER_GCP_WORKLOAD_PROVIDER` to the provider's full
   resource name.

```bash
gcloud iam workload-identity-pools create cloudsaver --location=global
gcloud iam workload-identity-pools providers create-oidc azure-mi \
  --location=global --workload-identity-pool=cloudsaver \
  --issuer-uri="https://login.microsoftonline.com/<HOST_TENANT_ID>/v2.0" \
  --allowed-audiences="api://AzureADTokenExchange" \
  --attribute-mapping="google.subject=assertion.sub" \
  --attribute-condition="assertion.sub == '<MI_OBJECT_ID>'"
```

### Each workspace (operator)

Create **one reader service account per workspace** in the CloudSaver project and
assign it in the operator console. A shared service account would let one
customer's project grant reach scans for every workspace.

Let the managed identity impersonate it:

```bash
gcloud iam service-accounts add-iam-policy-binding \
  <WORKSPACE_SA>@<CLOUDSAVER_PROJECT>.iam.gserviceaccount.com \
  --role=roles/iam.workloadIdentityUser \
  --member="principal://iam.googleapis.com/projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/cloudsaver/subject/<MI_OBJECT_ID>"
```

### Each customer project

Grant the workspace's service account read access. Simplest: `roles/compute.viewer`,
`roles/cloudsql.viewer` and `roles/monitoring.viewer`. Least privilege: this custom role.

```yaml
title: CloudSaver Inventory Reader
description: Read-only inventory for CloudSaver waste findings.
stage: GA
includedPermissions:
  - compute.disks.list
  - compute.addresses.list
  - cloudsql.instances.list
  - monitoring.timeSeries.list
```

```bash
gcloud iam roles create cloudSaverReader --project=<CUSTOMER_PROJECT> --file=cloudsaver-reader.yaml
gcloud projects add-iam-policy-binding <CUSTOMER_PROJECT> \
  --role=projects/<CUSTOMER_PROJECT>/roles/cloudSaverReader \
  --member="serviceAccount:<WORKSPACE_SA>@<CLOUDSAVER_PROJECT>.iam.gserviceaccount.com"
```

## 5. Kubernetes

The managed identity isn't used. Prometheus access stays an operator-bound bearer
token (`CLOUDSAVER_PROMETHEUS_TOKEN_*`) for a read-only endpoint.

## 6. Developer mode

With `CLOUDSAVER_CLOUD_IDENTITY=developer`, your own signed-in identity takes the
managed identity's place:
- **Azure:** your user needs the Azure read role from section 2 on the subscriptions.
- **AWS:** your SSO role needs `sts:AssumeRole` on the reader role, and that role's
  trust policy must list your SSO role as well as the hub role.
- **GCP:** your user needs `roles/iam.serviceAccountTokenCreator` on the workspace
  service account.

## Verify the token claims

If a trust rule rejects the token, compare it with the claims the managed identity
actually receives. Run this inside an Azure-hosted container and decode only the
payload. Don't log the token.

```bash
curl -s -H "X-IDENTITY-HEADER: $IDENTITY_HEADER" \
  "$IDENTITY_ENDPOINT?api-version=2019-08-01&resource=api://AzureADTokenExchange&client_id=<MI_CLIENT_ID>" \
  | python3 -c "import sys,json,base64;t=json.load(sys.stdin)['access_token'].split('.')[1];t+='='*(-len(t)%4);c=json.loads(base64.urlsafe_b64decode(t));print({k:c[k] for k in ('iss','aud','sub')})"
```
