"""Offline candidate screening. Redaction never authorizes client-derived shared knowledge."""
import re

IDENTIFIERS=(
    r'(?i)/subscriptions/[^\s,;]+',r'(?i)arn:[^\s,;]+',
    r'(?i)\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b',r'\b[0-9]{12}\b',
    r'(?i)[\w.+-]+@[\w.-]+\.[a-z]{2,}',r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b',
    r'(?i)\b(?:[a-z0-9-]+\.)+(?:internal|local|corp|com|net|org|io)\b',
    r'(?i)\b(?:bearer\s+\S+|cs_(?:live|test)_[a-z0-9_]+)',
)


def scrub_and_validate_knowledge_candidate(text,*,origin='tenant_observation',tenant_tokens=()):
    if origin not in ('synthetic','public_documentation'):
        raise ValueError('Client-derived observations are not eligible for shared knowledge, including after redaction.')
    if not isinstance(text,str) or not 1<=len(text)<=8000 or len(tenant_tokens)>100:
        raise ValueError('Use a bounded, independently authored candidate.')
    if any(not isinstance(token,str) or not 4<=len(token)<=256 for token in tenant_tokens):
        raise ValueError('Known identifying tokens require explicit bounded strings.')
    redactions=0
    for pattern in IDENTIFIERS:
        text,count=re.subn(pattern,'[REDACTED]',text);redactions+=count
    if any(token.casefold() in text.casefold() for token in tenant_tokens):
        raise ValueError('Possible tenant-specific content remains; no candidate is eligible for publication.')
    if re.search(r'(?i)(?:password|api[_ -]?key|secret)\s*[:=]|\b[0-9a-f]{0,4}:[0-9a-f:]{2,}\b',text):
        raise ValueError('Potential secret or unhandled identifier requires independent rewriting.')
    return dict(scrubbed_text=text,redactions=redactions,origin=origin,dual_review_required=True,publication_eligible=False,
        message='Offline screening only. The separate knowledge service must still reject identifying text and require independent KnowledgeReviewer and PrivacyReviewer approvals.')


def calibrate_confidence_band(assessment):
    from app.knowledge import confidence
    return confidence(assessment)


def validate_ai_advisory_citations(raw,context,*,resource_level=True):
    # Reuse the active schema, citation, deterministic-risk and protected-action gates.
    from app.ai_advisory import parse_advice,parse_resource_advice
    return parse_resource_advice(raw,context) if resource_level else parse_advice(raw,context)
