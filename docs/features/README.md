# CloudSaver feature guides

Each guide explains one feature end to end: where you find it in the dashboard, what you can do, how the backend produces the data, the API endpoints, permissions, configuration, guardrails and tests. Start with the [main README](../../README.md) for installation and architecture.

## Analyze

| Guide | Dashboard location | What it covers |
| --- | --- | --- |
| [Overview](overview.md) | `/` | Review queue, scan trends, foundations checklist and the hourly commitment ceiling |
| [Resources](resources.md) | `/resources` | One record per resource: filters, merged five-pillar evidence, billing columns, the resource details drawer, decisions, CSV export and the printable report |
| [Workload assessments](workload-assessments.md) | `/workloads` | Application and environment roll-ups of resource evidence and ownership mapping |
| [Services](services.md) | `/services/[service]` | Service-specific analysis matrices for disks, compute, databases and other families |
| [Kubernetes](kubernetes.md) | `/kubernetes` | Cluster telemetry provenance, allocation slack, node billing and gated consolidation models |
| [AI assessments](ai-assessments.md) | `/resources`, `/settings` | Batch AI reviews, follow-up questions, approved AI targets and AI data governance |

## Optimize and account

| Guide | Dashboard location | What it covers |
| --- | --- | --- |
| [Optimization evidence](optimization-evidence.md) | `/optimization` | Optimization and retail evidence models tied to the selected scan |
| [Cost allocation and billing](cost-allocation-and-billing.md) | `/allocation` | Cost grouping, tag evidence, FOCUS billing imports and billed, effective and retail costs |
| [Savings and investigations](savings-and-investigations.md) | `/outcomes` | Savings cases, anomaly investigations and outcome evidence |
| [Risk and compliance](risk-and-compliance.md) | `/governance` | Governance findings, exceptions, audit packages and human-approved change plans |

## Act

| Guide | Dashboard location | What it covers |
| --- | --- | --- |
| [Agent worker](agent-worker.md) | `/agents` | Connector plans, human approval, single-use permits and bounded execution evidence |
| [Automation and GitOps](automation-and-gitops.md) | `/automation` | Reviewed CLI and Terraform exports, GitOps pull requests and Terraform plan checks |
| [Activity and delivery](activity-and-delivery.md) | `/activity` | Scan and AI history, delivery evidence, notifications and retries |

## Administer

| Guide | Dashboard location | What it covers |
| --- | --- | --- |
| [Settings](settings.md) | `/settings` | Cloud scopes and plan, analysis rules, AI and data governance, access and API keys |
| [Onboarding and access](onboarding-and-access.md) | `/claim`, sign-in | Workspace keys, Entra tokens, roles, scoped keys and sessions |
| [Scanning and analysis rules](scanning-and-analysis-rules.md) | Toolbar scans, `/settings` | Azure, AWS, Google Cloud and Kubernetes scans, the rule catalog, pricing and scheduled scans |
| [Platform portal](platform-portal.md) | Separate operator app | Identity, customers, workspaces, plans, policies and knowledge publications |

## Roadmap

| Guide | What it covers |
| --- | --- |
| [V2 scaffolds](v2-scaffolds.md) | Modules that exist but aren't production-wired yet, and what each needs to ship |
