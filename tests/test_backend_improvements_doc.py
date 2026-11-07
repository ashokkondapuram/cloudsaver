"""Sanity-check that BACKEND_IMPROVEMENTS.md references real modules."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs" / "BACKEND_IMPROVEMENTS.md").read_text()

DOC_EXTRA_PATHS = (
    "ebpf-flow-exporter",
    "workers/code-mode-bridge",
)

GRAFANA_DOC_MODULES = (
    "app/collectors/grafana_telemetry.py",
    "app/kubernetes_grafana_schemas.py",
    "workers/grafana_k8s_rightsizing.py",
    "app/grafana_k8s_store.py",
)

ENV_FLAGS = (
    "CLOUDSAVER_KUBERNETES_BINDINGS",
    "CLOUDSAVER_GRAFANA_",
    "CLOUDSAVER_OBSERVABILITY_SECRET_",
    "CLOUDSAVER_AI_ENABLED",
    "CLOUDSAVER_AGENT_ENABLED",
    "CLOUDSAVER_GITOPS_PUBLISH",
    "CLOUDSAVER_INTERACTIVE_JOBS",
    "CLOUDSAVER_DRIFT_SUBSCRIPTION_WIRING",
    "CLOUDSAVER_CODE_MODE_ENABLED",
    "PLATFORM_PROVIDER_SCOPED_KEYS",
)

REGRESSION_TESTS = re.findall(
    r"(?:tests|platform/tests)/[\w./\-]+\.py",
    re.search(r"\*\*Representative regression entry points:\*\* (.+)", DOC).group(1),
)


def test_backend_improvements_doc_exists():
    assert "CloudSaver backend improvements" in DOC
    assert "§5b" in DOC or "5b" in DOC


def test_grafana_backend_doc_modules_referenced():
    missing = [path for path in GRAFANA_DOC_MODULES if path not in DOC]
    assert not missing, missing


def test_doc_module_paths_exist():
    paths = set(re.findall(r"(?:app|platform|workers|database|agent-worker)/[a-z0-9_./\-]+", DOC))
    paths = {p.rstrip(").,") for p in paths if not any(ch in p for ch in "*")}
    paths.discard("app/code_mode_")
    missing = [p for p in sorted(paths) if not (ROOT / p).exists()]
    assert not missing, f"missing paths: {missing[:20]}"


def test_doc_extra_directories_exist():
    missing = [p for p in DOC_EXTRA_PATHS if not (ROOT / p).is_dir()]
    assert not missing, missing


def test_doc_regression_tests_exist():
    missing = [p for p in REGRESSION_TESTS if not (ROOT / p).is_file()]
    assert not missing, missing


def test_doc_env_flags_referenced_in_tree():
    missing = []
    for flag in ENV_FLAGS:
        cmd = ["rg", "-q", re.escape(flag), str(ROOT)]
        if subprocess.run(cmd, capture_output=True).returncode != 0:
            missing.append(flag)
    assert not missing, f"env flags not referenced in repo: {missing}"
