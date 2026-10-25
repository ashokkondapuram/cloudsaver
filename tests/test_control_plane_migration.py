import importlib.util
import pathlib
import sys
import types

PATH = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0026_control_plane.py"


def _load():
    spec = importlib.util.spec_from_file_location("m0026", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(fn):
    sql = []
    alembic = types.ModuleType("alembic")
    alembic.op = types.SimpleNamespace(execute=sql.append, get_bind=lambda: types.SimpleNamespace(execute=lambda _: types.SimpleNamespace(scalar=lambda: False)))
    saved = sys.modules.get("alembic")
    sys.modules["alembic"] = alembic
    try:
        fn()
    finally:
        if saved is None:
            sys.modules.pop("alembic", None)
        else:
            sys.modules["alembic"] = saved
    return sql


def test_revision_chain():
    m = _load()
    assert m.revision == "0026_control_plane" and m.down_revision == "0025_observability_connectors"


def test_every_table_has_forced_rls_policy_and_tenant_column():
    m = _load()
    sql = "\n".join(_run(m.upgrade))
    for table, (ddl, grants) in m.TABLES.items():
        assert "tenant_id uuid NOT NULL" in ddl
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in sql
        assert f"CREATE POLICY tenant_isolation ON {table}" in sql
        assert f"REVOKE ALL ON {table} FROM PUBLIC" in sql
        assert "DELETE" not in grants


def test_evidence_tables_are_append_only():
    m = _load()
    sql = "\n".join(_run(m.upgrade))
    for table in m.TABLES:
        if table != "cp_plan_versions":
            assert f"UPDATE ON {table}" not in sql and m.TABLES[table][1] == "SELECT,INSERT"
    assert "GRANT UPDATE (state, updated_at) ON cp_plan_versions" in sql


def test_downgrade_drops_all_tables():
    m = _load()
    sql = _run(m.downgrade)
    assert sum(statement.startswith("DROP TABLE") for statement in sql) == len(m.TABLES)
    assert any("ACCESS EXCLUSIVE" in statement for statement in sql)
