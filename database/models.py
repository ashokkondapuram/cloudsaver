"""Normalized PostgreSQL foundation; snapshot persistence remains in app.store.

tenant_id always means the customer Azure directory UUID. Async services can use
these SQLAlchemy 2 models through AsyncSession; no global engine is created.
Every transaction must set app.current_tenant_id with a transaction-local value.
"""
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, Integer, CheckConstraint, DateTime, ForeignKeyConstraint, Index, Numeric, String, Text, UniqueConstraint, false, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = 'organizations'
    __table_args__ = (
        UniqueConstraint('id', 'tenant_id', name='uq_organizations_id_tenant'),
        UniqueConstraint('stripe_customer_id', name='uq_organizations_stripe_customer'),
        CheckConstraint("plan_tier IN ('STARTER', 'GROWTH', 'ENTERPRISE')", name='ck_organizations_plan_tier'),
        Index('ix_organizations_tenant', 'tenant_id'),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    plan_tier: Mapped[str] = mapped_column(String(16), nullable=False, server_default='STARTER')
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_subscription_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stripe_subscription_created: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default='0')
    stripe_event_created: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default='0')
    stripe_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_last_invoice_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_invoice_event_created: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default='0')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Tenant(Base):
    __tablename__ = 'tenants'
    __table_args__ = (
        ForeignKeyConstraint(['organization_id', 'tenant_id'], ['organizations.id', 'organizations.tenant_id'],
                             name='fk_tenants_organization_owner', ondelete='RESTRICT'),
        Index('ix_tenants_organization', 'organization_id', 'tenant_id'),
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    connection_status: Mapped[str] = mapped_column(String(32), nullable=False, server_default='pending')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Subscription(Base):
    __tablename__ = 'subscriptions'
    __table_args__ = (
        ForeignKeyConstraint(['tenant_id'], ['tenants.tenant_id'], name='fk_subscriptions_tenant', ondelete='RESTRICT'),
        UniqueConstraint('tenant_id', 'subscription_id', name='uq_subscriptions_tenant_subscription'),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    subscription_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WasteFinding(Base):
    scan_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    __tablename__ = 'waste_findings'
    __table_args__ = (
        ForeignKeyConstraint(['scan_id', 'tenant_id'], ['scans.id', 'scans.tenant_id'], name='fk_waste_findings_scan_owner', ondelete='RESTRICT'),
        UniqueConstraint('scan_id', 'resource_id', 'rule_id', name='uq_waste_findings_scan_resource_rule'),
        ForeignKeyConstraint(['tenant_id', 'subscription_id'], ['subscriptions.tenant_id', 'subscriptions.subscription_id'],
                             name='fk_waste_findings_subscription_owner', ondelete='RESTRICT'),
        CheckConstraint("severity IN ('HIGH', 'MEDIUM', 'LOW', 'INFO')", name='ck_waste_findings_severity'),
        CheckConstraint('estimated_monthly_waste_usd IS NULL OR estimated_monthly_waste_usd >= 0', name='ck_waste_findings_nonnegative_cost'),
        Index('ix_waste_findings_owner_observed', 'tenant_id', 'observed_at'),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    subscription_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    resource_id: Mapped[str] = mapped_column(Text, nullable=False)
    resource_name: Mapped[str] = mapped_column(String(256), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(256), nullable=False)
    resource_group: Mapped[str] = mapped_column(String(256), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default='{}')
    estimated_monthly_waste_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StripeEvent(Base):
    __tablename__ = 'stripe_events'
    __table_args__ = (ForeignKeyConstraint(['organization_id', 'tenant_id'], ['organizations.id', 'organizations.tenant_id'], name='fk_stripe_events_organization_owner', ondelete='RESTRICT'),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    event_created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ScanJob(Base):
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    __tablename__ = 'scan_jobs'
    __table_args__ = (
        ForeignKeyConstraint(['tenant_id'], ['tenants.tenant_id'], name='fk_scan_jobs_tenant', ondelete='RESTRICT'),
        ForeignKeyConstraint(['scan_id','tenant_id'], ['scans.id','scans.tenant_id'], name='fk_scan_jobs_scan_owner', ondelete='RESTRICT'),
        CheckConstraint("status IN ('queued','running','completed','failed')", name='ck_scan_jobs_status'),
        CheckConstraint("notification_status IN ('not_requested','sent','failed')", name='ck_scan_jobs_notification'),
        CheckConstraint('attempts >= 0', name='ck_scan_jobs_attempts'),
        Index('ix_scan_jobs_tenant_created', 'tenant_id', 'created_at'),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default='queued')
    scan_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')
    notification_status: Mapped[str] = mapped_column(String(24), nullable=False, server_default='not_requested')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Scan(Base):
    __tablename__ = 'scans'
    __table_args__ = (
        UniqueConstraint('id', 'tenant_id', name='uq_scans_id_tenant'),
        Index('scans_owner', 'tenant_id', 'timestamp'),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class CloudFinding(Base):
    __tablename__ = 'cloud_findings'
    __table_args__ = (
        ForeignKeyConstraint(['scan_id', 'tenant_id'], ['scans.id', 'scans.tenant_id'], name='fk_cloud_findings_scan_owner', ondelete='RESTRICT'),
        UniqueConstraint('scan_id', 'cloud_provider', 'resource_id', 'rule_id', name='uq_cloud_findings_identity'),
        CheckConstraint("cloud_provider IN ('aws','gcp','kubernetes')", name='cloud_findings_cloud_provider_check'),
        Index('ix_cloud_findings_owner_observed', 'tenant_id', 'observed_at'),
    )
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    scan_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    cloud_provider: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(256), nullable=False)
    resource_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
