"""Map cloud account/subscription/project IDs to workspace tenant UUIDs."""


def workspace_resolver_for_settings(settings):
    tenants = settings.tenants

    def resolve(provider: str, account: str) -> str | None:
        account_key = str(account).lower()
        for tenant in tenants:
            if provider == "azure":
                subs = {str(s).lower() for s in tenant.get("subscription_ids") or []}
                if account_key in subs:
                    return tenant["tenant_id"]
            if provider == "aws":
                accounts = {str(row.get("account_id")) for row in tenant.get("aws_accounts") or []}
                if account in accounts:
                    return tenant["tenant_id"]
            if provider == "gcp":
                projects = {str(row.get("project_id")).lower() for row in tenant.get("gcp_projects") or []}
                if account_key in projects:
                    return tenant["tenant_id"]
        return None

    return resolve
