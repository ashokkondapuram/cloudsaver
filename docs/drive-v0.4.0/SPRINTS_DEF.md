Historical Drive sprint specification. Current implementation status is in README.md and IMPLEMENTATION_STATUS.md.

﻿CloudSaver Sprints D–H: Enterprise Identity, Pricing Attribution, Terraform IaC, Entitlements & Outbox Hardening
Current Release: v0.3.0


This release implements the next 5 major roadmap pillars from ROADMAP.md:
Sprint D: Enterprise Identity, Microsoft Entra ID (Azure AD) OIDC & RBAC
* Module: app/auth.py, tested in tests/test_auth.py.
* Capabilities:
   * Token verification for Microsoft Entra ID v2.0 access and ID tokens.
   * Multi-tenant tenant boundary validation preventing cross-tenant access.
   * Role-Based Access Control (RBAC): TenantAdmin, Viewer, BillingAdmin.
   * Entra ID Admin Consent onboarding URL generator with state and nonce validation.
Sprint E: Real-Time Azure Retail Prices API & Cost Attribution
* Module: app/pricing.py, tested in tests/test_pricing.py.
* Capabilities:
   * Connects to the public Azure Retail Prices API (https://prices.azure.com/api/retail/prices).
   * Evidence-based rate calculation across unattached disks, unassociated public IPs, stopped VMs, and empty App Service plans.
   * Returns WasteCostAttribution with currency, confidence rating (HIGH, MEDIUM, ESTIMATED), potential waste, and realizable net savings after pre-deletion safety snapshot storage.
Sprint F: Declarative Terraform IaC Remediation
* Module: app/remediation_terraform.py, tested in tests/test_remediation_terraform.py.
* Capabilities:
   * Declarative Terraform HCL (.tf) generator alongside existing Bash scripts.
   * Automated azurerm_snapshot resource creation for pre-destruction data protection.
   * Native Terraform 1.5+ import { to = ... id = ... } blocks for drift-free adoption.
   * Operator runbook with planned deletion verification (terraform plan -destroy).
Sprint G: Stripe Checkout & Tier Entitlement Enforcement
* Module: app/entitlements.py, tested in tests/test_entitlements.py.
* Capabilities:
   * Tier feature matrix across STARTER (2 subscriptions, manual scans), GROWTH (10 subscriptions, daily scans, Terraform export, Slack alerts), and ENTERPRISE (unlimited, hourly scans, Key Vault, multi-channel alerts).
   * Quota enforcement middleware raising HTTP 402/403 with upgrade guidance.
   * Stripe Checkout Session creation for self-service plan upgrades.
Sprint H: Transactional Outbox & Distributed Worker Leasing
* Modules: database/outbox.py, workers/lease.py, tested in tests/test_outbox_lease.py.
* Capabilities:
   * Transactional Outbox pattern guaranteeing at-least-once alert delivery.
   * Configurable retry backoff with dead-letter queue isolation after 5 failed attempts.
   * Distributed task mutual exclusion lease with heartbeat renewals.
   * Job lifecycle state machine (QUEUED -> LEASE_ACQUIRED -> SCANNING_ARG -> ATTRIBUTING_PRICES -> PERSISTING -> OUTBOX_COMMITTED -> COMPLETED).
   * Cooperative cancellation tokens for aborting scans between ARG batches.
