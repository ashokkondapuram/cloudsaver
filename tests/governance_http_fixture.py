"""Explicit loopback-test factories. Never imported by production entrypoints."""

import os, secrets
from uuid import uuid5, NAMESPACE_URL
from fastapi import HTTPException
from app.auth import UserClaims, Role
from app.config import Settings
from app.main import create_app
from services.gateway import create_app as gateway


def user(name):
    return str(uuid5(NAMESPACE_URL, "cloudsaver-http-governance-" + name))


class SyntheticIdentity:
    def verify_token(self, token):
        expected = os.environ.get("CLOUDSAVER_HTTP_TEST_TOKEN", "")
        prefix, _, name = token.partition(":")
        if (
            len(expected) < 32
            or not secrets.compare_digest(prefix, expected)
            or name
            not in (
                "admin",
                "owner",
                "security",
                "approver",
                "verifier",
                "business",
                "auditor",
            )
        ):
            raise HTTPException(401, "Invalid synthetic test session")
        return UserClaims(
            user_id=user(name),
            tenant_id=os.environ["CLOUDSAVER_HTTP_TEST_TENANT"],
            roles=[Role.TENANT_ADMIN if name == "admin" else Role.VIEWER],
        )


def core():
    return create_app(Settings.load(), identity_validator=SyntheticIdentity())


def edge():
    return gateway(Settings.load(), identity_validator=SyntheticIdentity())
