"""Bounded, process-local PostgreSQL pools; tenant context stays transaction-local."""
import os
from contextlib import contextmanager
from threading import RLock

from sqlalchemy import create_engine


def integer(name, default, low, high):
    value = int(os.getenv(name, str(default)))
    if not low <= value <= high:
        raise ValueError(f'{name} is outside its supported range')
    return value


def engine(url, pid):
    with _guard:
        cached = _engines.get((url, pid))
        if cached is not None:
            return cached
        return _create_engine(url, pid)


def _create_engine(url, pid):
    import psycopg
    result = create_engine(
        'postgresql+psycopg://',
        creator=lambda: psycopg.connect(url, connect_timeout=5),
        pool_pre_ping=True,
        pool_size=integer('CLOUDSAVER_DB_POOL_SIZE', 2, 1, 20),
        max_overflow=integer('CLOUDSAVER_DB_MAX_OVERFLOW', 3, 0, 20),
        pool_timeout=integer('CLOUDSAVER_DB_POOL_TIMEOUT', 5, 1, 30),
        pool_recycle=integer('CLOUDSAVER_DB_POOL_RECYCLE', 1800, 60, 3600),
        hide_parameters=True,
    )
    _engines[(url, pid)] = result
    return result


@contextmanager
def connect(url, **options):
    # A forked Celery child obtains its own engine, never its parent's sockets.
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
        # Reset any accidentally session-scoped state as well as SET LOCAL.
        try:
            if not db.closed:
                db.row_factory = previous_factory
                db.execute('RESET ALL')
                db.commit()
        except Exception:
            proxy.invalidate()
        proxy.close()


def dispose():
    # Engine objects are also retained by SQLAlchemy's checked-out connections;
    # dispose does not interrupt active transactions during graceful shutdown.
    with _guard:
        for (_, pid), item in list(_engines.items()):
            item.dispose(close=pid == os.getpid())
        _engines.clear()


_engines = {}
_guard = RLock()
