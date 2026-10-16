"""Registro de auditoría de acciones."""
from flask import g, has_request_context, request

from .. import db


def auditar(accion, modulo, registro_id=None, tx=None):
    uid = g.user["id"] if has_request_context() and g.get("user") else None
    ip = request.remote_addr if has_request_context() else None
    sql = "INSERT INTO auditoria (usuario_id, accion, modulo, registro_id, ip) VALUES (%s,%s,%s,%s,%s)"
    params = (uid, accion[:255], modulo, str(registro_id) if registro_id is not None else None, ip)
    if tx is not None:
        tx.execute(sql, params)
    else:
        db.execute(sql, params)
