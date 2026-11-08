"""0039 — re-run rule_id canonicalisation (corrective; 0034 could no-op under non-superuser RLS)."""
revision = "0039_rerun_canonical_rule_ids"
down_revision = "0038_code_mode_runs"
branch_labels = depends_on = None


def upgrade():
    # versions/ has no __init__.py (alembic loads each file by path, not as a package),
    # so load 0034's module by file path and reuse its (idempotent, now RLS-safe and
    # batched) upgrade() to correct any tenant whose original 0034 run no-op'd under
    # non-superuser FORCE RLS.
    import importlib.util
    from pathlib import Path

    target = Path(__file__).resolve().parent / "0034_canonical_rule_ids.py"
    spec = importlib.util.spec_from_file_location("_0034_canonical_rule_ids_rerun", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.upgrade()


def downgrade():
    # No-op: this migration only re-applies 0034's (idempotent) data fix.
    pass
