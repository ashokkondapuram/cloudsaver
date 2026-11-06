"""Shared pagination helpers for collector HTTP and SDK reads.

Three continuation styles appear in this codebase:

1. **Query / body page tokens (GCP, many REST list APIs)** — use
   :func:`app.cloud_http.pages`, re-exported here as :func:`cloud_http_pages`.
   The reader performs GET (or an allowlisted POST); the next token is sent back
   on ``pageToken`` / ``nextPageToken`` (configurable).

2. **Azure ARM ``nextLink`` (full URL)** — :func:`iter_arm_next_link_values` yields
   each page's ``value`` list items and follows opaque ``nextLink`` URLs until
   exhausted. Used by :func:`app.collectors.azure_live.pages`.

3. **AWS boto3 ``NextToken``** — not wrapped here; see
   :func:`app.collectors.aws_live.pages`, which calls ``getattr(api, operation)(**kwargs)``
   in a loop, passes the previous ``NextToken`` on the request, and yields items from
   the response field (for example ``Reservations``). Keep token keys aligned with the
   service API (default ``NextToken`` / ``NextToken``).
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlsplit


def cloud_http_pages(reader, url, params=None, **kwargs):
    """Delegate to :func:`app.cloud_http.pages` (query-parameter continuation)."""
    from app.cloud_http import pages as _pages

    yield from _pages(reader, url, params, **kwargs)


def iter_arm_next_link_values(
    reader,
    url,
    params=None,
    *,
    validate_link: Callable[..., None] | None = None,
    max_pages: int = 200,
    values_key: str = 'value',
    next_link_key: str = 'nextLink',
) -> Iterator[Any]:
    """Yield ARM list items, following ``nextLink`` until absent."""
    seen: set[str] = set()
    scope = urlsplit(url).path.split('/providers/')[0].lower()
    for _ in range(max_pages):
        data = reader.get(url, params)
        values = data.get(values_key)
        if not isinstance(values, list):
            raise ValueError('Invalid Azure page')
        yield from values
        token = data.get(next_link_key)
        if not token:
            return
        if token in seen:
            raise ValueError('Invalid Azure continuation')
        if validate_link is not None:
            validate_link(token, scope_path_lower=scope)
        seen.add(token)
        url, params = token, None
    raise ValueError('Azure page bound exceeded')
