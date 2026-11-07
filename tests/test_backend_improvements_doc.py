"""Sanity-check that BACKEND_IMPROVEMENTS.md references real modules."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs" / "BACKEND_IMPROVEMENTS.md").read_text()


def test_backend_improvements_doc_exists():
    assert "CloudSaver backend improvements" in DOC
    assert "§5b" in DOC or "5b" in DOC


def test_doc_module_paths_exist():
    paths = set(re.findall(r"(?:app|platform|workers|database|agent-worker)/[a-z0-9_./\-]+", DOC))
    paths = {p.rstrip(").,") for p in paths if not any(ch in p for ch in "*")}
    paths.discard("app/code_mode_")
    missing = [p for p in sorted(paths) if not (ROOT / p).exists()]
    assert not missing, f"missing paths: {missing[:20]}"
