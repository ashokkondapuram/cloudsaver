"""Reject identifying text before persistence; rewriting is not anonymization."""
import re
from urllib.parse import urlsplit

IDENTIFIERS = re.compile(r'(?i)(?:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|arn:[a-z0-9:-]+|'
    r'/subscriptions/|/resourcegroups/|projects/[^\s/]+/|[\w.+-]+@[\w.-]+\.[a-z]{2,}|'
    r'\b(?:\d{1,3}\.){3}\d{1,3}\b|\b[0-9a-f]{0,4}:[0-9a-f:]{2,}\b|'
    r'cs_(?:live|test)_[a-z0-9_]+|bearer\s+\S+|(?:password|api[_ -]?key|secret)\s*[:=]|'
    r'\b(?:[a-z0-9-]+\.)+(?:com|net|org|internal|local|io)\b|\b\d{12}\b)')
HOSTS = {'learn.microsoft.com', 'docs.aws.amazon.com', 'cloud.google.com', 'kubernetes.io'}


def screen(*texts):
    if any(not isinstance(value, str) or IDENTIFIERS.search(value) for value in texts):
        raise ValueError('Knowledge content contains possible identifying or secret data. No payload was stored.')


def source(kind, url):
    if kind not in ('synthetic', 'public_documentation'):
        raise ValueError('Only independent synthetic or approved public documentation sources are eligible.')
    if kind == 'synthetic':
        if url:
            raise ValueError('Synthetic scenarios must not reference client sources.')
        return None
    parsed = urlsplit(url or '')
    if (parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.port not in (None, 443)):
        raise ValueError('Choose an approved public documentation HTTPS source without query parameters.')
    return url
