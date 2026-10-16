from .. import db


def listar(tipo=None, solo_activas=True):
    sql = "SELECT * FROM ubicaciones WHERE 1=1"
    params = []
    if tipo:
        sql += " AND tipo=%s"
        params.append(tipo)
    if solo_activas:
        sql += " AND activo=1"
    sql += " ORDER BY tipo='LOCAL', id"
    return db.query(sql, params)


def locales(solo_activas=True):
    return listar("LOCAL", solo_activas)


def depositos(solo_activas=True):
    return listar("DEPOSITO", solo_activas)


def get(ubicacion_id):
    return db.query("SELECT * FROM ubicaciones WHERE id=%s", (ubicacion_id,), one=True)


def deposito_central():
    return db.query("SELECT * FROM ubicaciones WHERE tipo='DEPOSITO' AND activo=1 ORDER BY id LIMIT 1", one=True)
