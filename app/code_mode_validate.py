"""Validate sandbox snippets before they reach the worker bridge."""
import re

_FORBIDDEN = re.compile(
    r'\b(import|export\s+(?:default|\*|{)|require\s*\(|eval\s*\(|Function\s*\(|fetch\s*\(|globalThis|process\.|Worker\s*\(|WebSocket\s*\()',
    re.I,
)

_SNIPPET = re.compile(
    r'^function\s+transform\s*\(\s*input\s*\)\s*\{[\s\S]+\}\s*$',
)


def validate_snippet(snippet: str, *, max_bytes: int = 16_384) -> None:
    raw = snippet if isinstance(snippet, str) else ''
    if not raw.strip():
        raise ValueError('Snippet is required.')
    encoded = raw.encode('utf-8')
    if len(encoded) > max_bytes:
        raise ValueError(f'Snippet exceeds {max_bytes} bytes.')
    if _FORBIDDEN.search(raw):
        raise ValueError('Snippet uses a forbidden construct for Code Mode.')
    if not _SNIPPET.match(raw.strip()):
        raise ValueError('Snippet must be a single function transform(input) { ... } declaration.')
