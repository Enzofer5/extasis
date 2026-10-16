from .. import db


def get(clave, default=None):
    row = db.query("SELECT valor FROM configuracion WHERE clave=%s", (clave,), one=True)
    return row["valor"] if row else default


def get_int(clave, default=0):
    try:
        return int(get(clave, default))
    except (TypeError, ValueError):
        return default


def get_bool(clave):
    return str(get(clave, "0")) == "1"


def todas():
    return db.query("SELECT clave, valor, descripcion FROM configuracion ORDER BY clave")


def set_valor(clave, valor):
    db.execute(
        "INSERT INTO configuracion (clave, valor) VALUES (%s,%s) ON DUPLICATE KEY UPDATE valor=VALUES(valor)",
        (clave, str(valor)),
    )
