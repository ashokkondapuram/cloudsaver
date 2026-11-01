"""Read-only operational metadata for drift inspection (ARM / EC2)."""
from __future__ import annotations

import re
from typing import Any


def azure_api_version(resource_id: str) -> str:
    provider_path = resource_id.split("/providers/", 1)[-1].lower() if "/providers/" in resource_id else ""
    if provider_path.startswith("microsoft.compute/virtualmachines"):
        return "2023-09-01"
    if provider_path.startswith("microsoft.compute/disks"):
        return "2023-04-02"
    if provider_path.startswith("microsoft.network/publicipaddresses"):
        return "2023-05-01"
    return "2021-04-01"


def fetch_azure_operational(signal: dict[str, Any], tenant: dict[str, Any]) -> dict[str, Any]:
    from app.cloud_http import JSONReader
    from app.cloud_identity import CredentialError, azure_credential
    from app.resource_access import runtime_settings

    resource_id = signal["canonical_resource_id"]
    subscription = signal.get("account_or_subscription_id") or ""
    if not subscription and resource_id.lower().startswith("/subscriptions/"):
        subscription = resource_id.split("/")[2]
    prefix = f"/subscriptions/{subscription}/".lower()
    if not resource_id.lower().startswith(prefix):
        raise ValueError("Azure resource is outside the signaled subscription")

    settings = runtime_settings(tenant)
    credential = azure_credential(tenant, settings=settings)
    reader = JSONReader(
        headers_factory=lambda _: {
            "Authorization": "Bearer "
            + credential.get_token("https://management.azure.com/.default").token
        }
    )
    try:
        body = reader.get(
            "https://management.azure.com" + resource_id,
            {"api-version": azure_api_version(resource_id)},
        )
    finally:
        reader.close()
        credential.close()

    properties = body.get("properties") or {}
    tags = properties.get("tags") or body.get("tags") or {}
    state: dict[str, Any] = dict(tags=tags, source="azure_arm_live")
    if "hardwareProfile" in properties:
        state["vm_size"] = (properties.get("hardwareProfile") or {}).get("vmSize")
    if "diskSizeGB" in properties:
        state["disk_size_gb"] = properties.get("diskSizeGB")
    sku = body.get("sku") or properties.get("sku")
    if isinstance(sku, dict) and sku.get("name"):
        state["sku"] = sku["name"]
    etag = body.get("etag") or properties.get("etag")
    if etag:
        state["etag"] = etag
    return state


def fetch_aws_operational(signal: dict[str, Any], tenant: dict[str, Any]) -> dict[str, Any]:
    from app.cloud_identity import CredentialError, aws_session

    arn = signal["canonical_resource_id"]
    match = re.fullmatch(
        r"arn:aws:ec2:([a-z0-9-]+):(\d{12}):(instance|volume)/([A-Za-z0-9-]+)",
        arn,
    )
    if not match:
        return dict(source="aws_live_unsupported_arn", State=signal.get("State"), tags=signal.get("tags") or {})

    region, account, kind, resource_name = match.groups()
    accounts = tenant.get("aws_accounts") or []
    binding = next((row for row in accounts if str(row.get("account_id")) == account), None)
    if not binding or not binding.get("role_arn"):
        raise CredentialError("AWS reader role is not configured for this account")

    source = dict(
        role_arn=binding["role_arn"],
        region=region,
        external_id=binding.get("external_id"),
    )
    session = aws_session(source, tenant=tenant)
    ec2 = session.client("ec2")
    if kind == "instance":
        response = ec2.describe_instances(InstanceIds=[resource_name])
        instance = response["Reservations"][0]["Instances"][0]
        return dict(
            State=(instance.get("State") or {}).get("Name"),
            instance_type=instance.get("InstanceType"),
            tags={tag["Key"]: tag["Value"] for tag in instance.get("Tags") or []},
            source="aws_ec2_live",
        )
    response = ec2.describe_volumes(VolumeIds=[resource_name])
    volume = response["Volumes"][0]
    return dict(
        State=volume.get("State"),
        disk_size_gb=volume.get("Size"),
        volume_type=volume.get("VolumeType"),
        tags={tag["Key"]: tag["Value"] for tag in volume.get("Tags") or []},
        source="aws_ebs_live",
    )
