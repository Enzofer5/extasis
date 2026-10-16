"""Tarjetas de crédito y créditos personales (ej. MC Cred) con sus planes de cuotas e interés."""
from .. import db

# Qué tipo de entidad corresponde a cada método de pago
TIPO_POR_METODO = {"CREDITO": "TARJETA", "CREDPERS": "CREDITO_PERSONAL"}
TIPOS = {"TARJETA": "Tarjeta de crédito", "CREDITO_PERSONAL": "Crédito personal"}


def entidades(solo_activas=False):
    w = "WHERE e.activo=1" if solo_activas else ""
    filas = db.query(f"SELECT e.* FROM entidades_financieras e {w} ORDER BY e.tipo, e.nombre")
    wp = "AND activo=1" if solo_activas else ""
    for e in filas:
        e["planes"] = db.query(f"SELECT * FROM planes_cuotas WHERE entidad_id=%s {wp} ORDER BY cuotas", (e["id"],))
    return filas


def opciones_pos():
    """{'CREDITO': [{id, nombre, planes:[{id,cuotas,interes}]}], 'CREDPERS': [...]} sólo activos y con planes."""
    res = {"CREDITO": [], "CREDPERS": []}
    for e in entidades(solo_activas=True):
        if not e["planes"]:
            continue
        metodo = "CREDITO" if e["tipo"] == "TARJETA" else "CREDPERS"
        res[metodo].append({"id": e["id"], "nombre": e["nombre"],
                            "planes": [{"id": p["id"], "cuotas": p["cuotas"], "interes": float(p["interes_pct"])}
                                       for p in e["planes"]]})
    return res


def get_plan(plan_id, tx=None):
    sql = """SELECT p.*, e.nombre AS entidad, e.tipo, e.activo AS entidad_activa
             FROM planes_cuotas p JOIN entidades_financieras e ON e.id=p.entidad_id WHERE p.id=%s"""
    if tx is not None:
        return tx.query(sql, (plan_id,), one=True)
    return db.query(sql, (plan_id,), one=True)


def hay_planes(tipo):
    return bool(db.scalar("""SELECT COUNT(*) FROM planes_cuotas p JOIN entidades_financieras e ON e.id=p.entidad_id
                             WHERE e.tipo=%s AND e.activo=1 AND p.activo=1""", (tipo,)))
