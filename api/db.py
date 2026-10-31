"""PostgreSQL access: one shared connection pool, plus two ways to borrow a connection."""

from contextlib import contextmanager

import psycopg2.pool
from psycopg2.extras import RealDictCursor

from . import config

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            1,
            10,
            host=config.DB_HOST,
            port=config.DB_PORT,
            dbname=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            cursor_factory=RealDictCursor,  # rows come back as dicts
        )
    return _pool


def get_conn():
    """FastAPI dependency: a connection for one request.

    Endpoints that write call conn.commit() themselves, so the data is saved *before* the
    response goes out. Anything left uncommitted is rolled back when the connection is returned.
    """
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        conn.rollback()
        pool.putconn(conn)


@contextmanager
def short_transaction():
    """A separate connection that commits immediately.

    Used for audit entries and failed-verification records, which must be saved even when
    the request itself ends in an error response.
    """
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)
