"""Recover an incomplete PostgreSQL first boot without replacing stored data."""
from pathlib import Path

from psycopg import Connection, sql


def ensure_database_bootstrap(connection: Connection, password: str | None) -> None:
    """Run inside the schema owner's migration transaction, before grants.

    PostgreSQL's entrypoint only initializes an empty data directory. A failed
    init script can leave a healthy server whose runtime role was never created.
    Existing credentials and role attributes must never be silently changed.
    """
    connection.execute("SELECT pg_advisory_xact_lock(hashtext('cloudsaver.database.bootstrap'))")
    role = connection.execute(
        "SELECT rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolreplication "
        "FROM pg_roles WHERE rolname = 'cloudsaver_app'"
    ).fetchone()
    created = role is None
    if created:
        if not password:
            raise RuntimeError(
                'Database role cloudsaver_app is missing. Supply CLOUDSAVER_DB_PASSWORD '
                'to the schema-owner migration job to initialize it without deleting data.'
            )
        # DDL cannot bind a password parameter. psycopg quotes the literal; using
        # its cursor also keeps the credential out of SQLAlchemy SQL error logs.
        connection.execute(sql.SQL(
            'CREATE ROLE cloudsaver_app LOGIN NOSUPERUSER NOBYPASSRLS '
            'NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}'
        ).format(sql.Literal(password)))
    elif not role[0] or any(role[1:]):
        raise RuntimeError(
            'cloudsaver_app must be a LOGIN role without SUPERUSER, BYPASSRLS, '
            'CREATEDB, CREATEROLE or REPLICATION. Have the database administrator '
            'review its attributes; migration startup will not change them.'
        )

    scans = connection.execute("SELECT to_regclass('public.scans')").fetchone()[0]
    if created or scans is None:
        # The legacy scan store predates Alembic. Its idempotent schema retains
        # records, enforces tenant RLS and grants only the runtime permissions.
        connection.execute(Path(__file__).with_name('001_schema.sql').read_text())
