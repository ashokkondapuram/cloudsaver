"""Bounded, process-local PostgreSQL pools for the platform database."""
import os
from contextlib import contextmanager
from threading import RLock

from sqlalchemy import create_engine

from identity.config import integer

_engines = {}
_guard = RLock()


def engine(url, pid):
    with _guard:
        cached = _engines.get((url, pid))
        if cached is None:
            import psycopg
            cached = create_engine(
                'postgresql+psycopg://',
                creator=lambda: psycopg.connect(url, connect_timeout=5),
                pool_pre_ping=True,
                pool_size=integer('DB_POOL_SIZE', 4, 1, 20),
                max_overflow=integer('DB_MAX_OVERFLOW', 4, 0, 20),
                pool_timeout=integer('DB_POOL_TIMEOUT', 5, 1, 30),
                pool_recycle=integer('DB_POOL_RECYCLE', 1800, 60, 3600),
                hide_parameters=True,
            )
            _engines[(url, pid)] = cached
        return cached


@contextmanager
def connect(url, **options):
    """One transaction on a pooled connection: commit on success, roll back on any error."""
    proxy = engine(url, os.getpid()).raw_connection()
    db = proxy.driver_connection
    previous_factory = db.row_factory
    if 'row_factory' in options:
        db.row_factory = options['row_factory']
    try:
        yield db
        db.commit()
    except BaseException:
        try:
            db.rollback()
        except Exception:
            proxy.invalidate()
        raise
    finally:
        try:
            if not db.closed:
                db.row_factory = previous_factory
                db.execute('RESET ALL')
                db.commit()
        except Exception:
            proxy.invalidate()
        proxy.close()


def dispose():
    with _guard:
        for (_, pid), item in list(_engines.items()):
            item.dispose(close=pid == os.getpid())
        _engines.clear()
