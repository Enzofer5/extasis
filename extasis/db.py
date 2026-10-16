"""Capa de acceso a datos: pool de conexiones MySQL + helpers parametrizados.

Todas las consultas usan parámetros (%s) => protección contra SQL Injection.
"""
from contextlib import contextmanager

import mysql.connector
from mysql.connector import pooling

_pool = None


def init_pool(app):
    global _pool
    cfg = app.config
    _pool = pooling.MySQLConnectionPool(
        pool_name="extasis_pool",
        pool_size=cfg["DB_POOL_SIZE"],
        pool_reset_session=True,
        host=cfg["DB_HOST"], port=cfg["DB_PORT"],
        user=cfg["DB_USER"], password=cfg["DB_PASSWORD"],
        database=cfg["DB_NAME"], charset="utf8mb4", collation="utf8mb4_unicode_ci",
        autocommit=True, time_zone="-03:00",
    )


def get_conn():
    return _pool.get_connection()


def query(sql, params=None, one=False):
    """SELECT => lista de dicts (o un dict si one=True)."""
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params or ())
        rows = cur.fetchall()
        cur.close()
        if one:
            return rows[0] if rows else None
        return rows
    finally:
        conn.close()


def scalar(sql, params=None, default=0):
    row = query(sql, params, one=True)
    if not row:
        return default
    val = list(row.values())[0]
    return default if val is None else val


def execute(sql, params=None):
    """INSERT/UPDATE/DELETE simple con autocommit. Devuelve lastrowid."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        last = cur.lastrowid
        cur.close()
        return last
    finally:
        conn.close()


class Tx:
    """Cursor transaccional con helpers."""

    def __init__(self, conn):
        self.conn = conn
        self.cur = conn.cursor(dictionary=True)

    def query(self, sql, params=None, one=False):
        self.cur.execute(sql, params or ())
        rows = self.cur.fetchall()
        if one:
            return rows[0] if rows else None
        return rows

    def scalar(self, sql, params=None, default=0):
        row = self.query(sql, params, one=True)
        if not row:
            return default
        val = list(row.values())[0]
        return default if val is None else val

    def execute(self, sql, params=None):
        self.cur.execute(sql, params or ())
        return self.cur.lastrowid

    @property
    def rowcount(self):
        return self.cur.rowcount


@contextmanager
def transaction():
    """Uso:
        with transaction() as tx:
            tx.execute(...)
    Commit automático, rollback ante cualquier excepción.
    """
    conn = get_conn()
    conn.autocommit = False
    tx = Tx(conn)
    try:
        conn.start_transaction(isolation_level="READ COMMITTED")
        yield tx
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            tx.cur.close()
        except Exception:
            pass
        conn.autocommit = True
        conn.close()


Error = mysql.connector.Error
IntegrityError = mysql.connector.IntegrityError
