"""Surgical HCL attribute patching inside AST line ranges."""

from __future__ import annotations

import re


def patch_attribute_in_block(
    source: str,
    *,
    start_line: int,
    end_line: int,
    attribute: str,
    new_value: str,
) -> str:
    if start_line < 1 or end_line < start_line:
        raise ValueError("Invalid line range")
    lines = source.splitlines(keepends=True)
    if end_line > len(lines):
        raise ValueError("Line range exceeds file length")
    block = "".join(lines[start_line - 1 : end_line])
    pattern = re.compile(
        rf"(\s*{re.escape(attribute)}\s*=\s*)(\"[^\"]*\"|'[^']*'|\S+)",
        re.MULTILINE,
    )
    if not pattern.search(block):
        raise ValueError(f"Attribute {attribute} not found in AST block")
    patched_block = pattern.sub(rf"\1{new_value}", block, count=1)
    return "".join(lines[: start_line - 1]) + patched_block + "".join(lines[end_line:])


def block_matches_indexed_snapshot(live_block: str, indexed_block: str) -> bool:
    return live_block.strip() == indexed_block.strip()
