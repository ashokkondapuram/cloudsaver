"""Every HTTP route on the gateway and services, classified for provider-scoped workspace keys.

test_route_inventory fails when a route is missing, so new endpoints must be classified here.
Classes:
  public       no workspace authentication
  agnostic     allowed for any key with the required role
  scoped_read  results are filtered to the key's providers (ScopedStore)
  scan_write   acts on an existing scan; every provider in the scan must be allowed
  provider     fixed providers that must all be allowed (value is a tuple)
  body         providers named in the request body are checked by the handler
  full_scope   requires a key that covers every configured provider
"""

ROUTES = {
    ('GET','/api/v1/optimization/scans/{scan_id}'):'scoped_read',
    ('GET','/api/v1/optimization/scans/{scan_id}/topology/{root_key}'):'scoped_read',
    ('POST','/api/v1/optimization/simulate/{engine}'):'agnostic',
    ('GET','/api/v1/optimization/cases'):'scoped_read',
    ('POST','/api/v1/optimization/cases'):'scoped_read',
    ('GET','/api/v1/optimization/cases/{case_id}'):'scoped_read',
    ('PATCH','/api/v1/optimization/cases/{case_id}'):'scoped_read',
    ('POST','/api/v1/optimization/cases/{case_id}/verify'):'scoped_read',
    ('POST','/api/v1/optimization/receipts'):'agnostic',
    ('GET', '/api/v1/scans/{scan_id}/kubernetes'): 'scoped_read',
    ('POST', '/api/v1/scans/{scan_id}/kubernetes/patch-preview'): 'scan_write',
    ('GET', '/api/v1/rules/effective'): 'agnostic',
    ('POST', '/api/v1/rules/preview'): 'full_scope',
    ('PUT', '/api/v1/rules/overrides'): 'full_scope',
    ('GET', '/api/v1/services/{service}'): 'scoped_read',
    ('GET', '/api/v1/services/{service}/comparison'): 'scoped_read',
    ('GET', '/'): 'public',
    ('GET', '/healthz'): 'public',
    ('GET', '/readyz'): 'public',
    # Removed in 1.3.0; both return 410 until 1.4.0 because billing moved to the platform.
    ('POST', '/api/v1/billing/webhook'): 'public',
    ('POST', '/api/v1/billing/checkout'): 'public',
    ('POST', '/api/v1/onboarding/claim'): 'public',

    ('GET', '/api/v1/me'): 'agnostic',
    # Customer access administration; identity-service enforces customer roles on every call.
    ('GET', '/api/v1/customer/me'): 'agnostic',
    ('GET', '/api/v1/customer/users'): 'agnostic',
    ('POST', '/api/v1/customer/users/invite'): 'agnostic',
    ('POST', '/api/v1/customer/users/{user_id}/suspend'): 'agnostic',
    ('POST', '/api/v1/customer/users/{user_id}/reactivate'): 'agnostic',
    ('POST', '/api/v1/customer/ownership/transfer'): 'agnostic',
    ('GET', '/api/v1/customer/members'): 'agnostic',
    ('PUT', '/api/v1/customer/members/{user_id}'): 'agnostic',
    ('POST', '/api/v1/customer/members/{user_id}/remove'): 'agnostic',
    ('GET', '/api/v1/customer/service-accounts'): 'agnostic',
    ('POST', '/api/v1/customer/service-accounts'): 'agnostic',
    ('PATCH', '/api/v1/customer/service-accounts/{account_id}'): 'agnostic',
    ('GET', '/api/v1/customer/keys'): 'agnostic',
    ('POST', '/api/v1/customer/keys'): 'agnostic',
    ('POST', '/api/v1/customer/keys/{key_id}/revoke'): 'agnostic',
    ('POST', '/api/v1/customer/keys/{key_id}/rotate'): 'agnostic',
    ('GET', '/api/v1/customer/audit'): 'agnostic',
    ('GET', '/api/v1/customer/access-export'): 'agnostic',
    ('GET', '/api/v1/providers'): 'agnostic',
    ('GET', '/api/v1/auth/consent-url'): 'agnostic',
    ('GET', '/api/v1/billing/entitlements'): 'agnostic',
    ('GET', '/api/v1/billing/plans'): 'agnostic',
    ('GET', '/api/v1/billing/plan-requests'): 'agnostic',
    ('POST', '/api/v1/billing/plan-requests'): 'agnostic',
    ('GET', '/api/v1/settings'): 'agnostic',
    ('PUT', '/api/v1/settings'): 'agnostic',
    ('POST', '/api/v1/settings/access-test'): 'agnostic',
    ('GET', '/api/v1/gitops/targets'): 'agnostic',
    ('GET', '/api/v1/ai/targets'): 'agnostic',
    ('GET', '/api/v1/settings/ai'): 'full_scope',
    ('PUT', '/api/v1/settings/ai'): 'full_scope',
    ('POST', '/api/v1/settings/ai/test-connection'): 'full_scope',
    ('GET', '/api/v1/operations/reliability'): 'agnostic',
    ('POST', '/api/v1/policies/terraform/evaluate'): 'agnostic',

    ('GET', '/api/v1/scans'): 'scoped_read',
    ('GET', '/api/v1/scans/{scan_id}'): 'scoped_read',
    ('GET', '/api/v1/trends'): 'scoped_read',
    ('GET', '/api/v1/analytics'): 'scoped_read',
    ('GET', '/api/v1/scans/{scan_id}/analysis'): 'scoped_read',
    ('GET', '/api/v1/scans/{scan_id}/resources'): 'scoped_read',
    ('GET', '/api/v1/scans/{scan_id}/resources/export'): 'scoped_read',
    ('GET', '/api/v1/scans/{scan_id}/resources/{resource_key}'): 'scoped_read',
    ('GET', '/api/v1/scans/{scan_id}/resources/{key}'): 'scoped_read',
    ('GET', '/api/v1/resources/{resource_key}/history'): 'scoped_read',
    ('GET', '/api/v1/resources/{key}/history'): 'scoped_read',

    ('POST', '/api/v1/scans/{scan_id}/remediation'): 'scan_write',
    ('POST', '/api/v1/scans/{scan_id}/remediation-terraform'): 'scan_write',
    ('POST', '/api/v1/scans/{scan_id}/cancel'): 'scan_write',
    ('POST', '/api/v1/scans/{scan_id}/analysis/resource'): 'scan_write',
    ('POST', '/api/v1/scans/{scan_id}/ai-risk-evaluation'): 'scan_write',
    ('POST', '/api/v1/scans/{scan_id}/ai-batches'): 'scan_write',
    ('POST', '/api/v1/scans/{scan_id}/resources/{resource_key}/questions'): 'scan_write',
    ('POST', '/api/v1/scans/{scan_id}/resources/{key}/questions'): 'scan_write',
    ('POST', '/api/v1/gitops/preview'): 'scan_write',
    ('POST', '/api/v1/gitops/requests'): 'scan_write',
    ('POST', '/api/v1/notifications/{scan_id}'): 'scan_write',

    ('POST', '/api/v1/scans'): ('azure',),
    ('POST', '/api/v1/scan-jobs'): ('azure',),
    ('GET', '/api/v1/scan-jobs'): ('azure',),
    ('GET', '/api/v1/scan-jobs/{job_id}'): ('azure',),
    ('POST', '/api/v1/scans/multi-cloud'): 'body',

    # Not provider-filtered yet; restricted keys are refused instead of seeing other providers' data.
    ('GET', '/api/v1/ai/assessments'): 'full_scope',
    ('GET', '/api/v1/ai/assessments/{assessment_id}'): 'full_scope',
    ('GET', '/api/v1/ai/usage'): 'full_scope',
    ('GET', '/api/v1/ai-batches'): 'full_scope',
    ('GET', '/api/v1/ai-batches/{batch_id}'): 'full_scope',
    ('POST', '/api/v1/ai-batches/{batch_id}/cancel'): 'full_scope',
    ('GET', '/api/v1/resources/{resource_key}/decisions'): 'full_scope',
    ('GET', '/api/v1/resources/{key}/decisions'): 'full_scope',
    ('POST', '/api/v1/resources/{resource_key}/decisions'): 'full_scope',
    ('POST', '/api/v1/resources/{key}/decisions'): 'full_scope',
    ('GET', '/api/v1/finops/imports'): 'full_scope',
    ('POST', '/api/v1/finops/imports'): 'full_scope',
    ('GET', '/api/v1/finops/summary'): 'full_scope',
    ('GET', '/api/v1/gitops/requests'): 'full_scope',
    ('GET', '/api/v1/gitops/requests/{request_id}'): 'full_scope',
    ('GET', '/api/v1/operations/deliveries'): 'full_scope',
    ('GET', '/api/v1/operations/deliveries/{event_id}/audit'): 'full_scope',
    ('POST', '/api/v1/operations/deliveries/{event_id}/retry'): 'full_scope',
}


def classify(method, path):
    return ROUTES.get((method.upper(), path))
