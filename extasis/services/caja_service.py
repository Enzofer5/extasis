"""Cajas por local: apertura, movimientos, arqueo y cierre.

Movimientos de INGRESO: VENTA, PAGO_CLIENTE, INGRESO
Movimientos de EGRESO : RETIRO, GASTO, DEVOLUCION
Efectivo esperado = monto inicial + ingresos en efectivo - egresos en efectivo.
"""
from decimal import Decimal

from .. import db
from ..models import catalogos
from . import NegocioError

TIPOS_INGRESO = ("VENTA", "PAGO_CLIENTE", "INGRESO")
TIPOS_EGRESO = ("RETIRO", "GASTO", "DEVOLUCION")


def caja_abierta(ubicacion_id, tx=None):
    sql = """SELECT c.*, u.nombre AS usuario_apertura, ub.nombre AS ubicacion
             FROM cajas c JOIN usuarios u ON u.id=c.usuario_apertura_id
             JOIN ubicaciones ub ON ub.id=c.ubicacion_id
             WHERE c.ubicacion_id=%s AND c.estado='ABIERTA'"""
    if tx is not None:
        return tx.query(sql + " FOR UPDATE", (ubicacion_id,), one=True)
    return db.query(sql, (ubicacion_id,), one=True)


def abrir(ubicacion_id, usuario_id, monto_inicial, observaciones=None):
    if monto_inicial < 0:
        raise NegocioError("El monto inicial no puede ser negativo.")
    with db.transaction() as tx:
        ub = tx.query("SELECT tipo FROM ubicaciones WHERE id=%s AND activo=1", (ubicacion_id,), one=True)
        if not ub or ub["tipo"] != "LOCAL":
            raise NegocioError("Sólo los locales activos pueden abrir caja.")
        if caja_abierta(ubicacion_id, tx):
            raise NegocioError("Ya hay una caja abierta en este local.")
        return tx.execute(
            "INSERT INTO cajas (ubicacion_id, usuario_apertura_id, monto_inicial, observaciones) VALUES (%s,%s,%s,%s)",
            (ubicacion_id, usuario_id, monto_inicial, observaciones))


def registrar(tx, caja_id, tipo, concepto, monto, metodo_pago_id, usuario_id, venta_id=None):
    tx.execute(
        """INSERT INTO movimientos_caja (caja_id, tipo, concepto, monto, metodo_pago_id, usuario_id, venta_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (caja_id, tipo, concepto[:200], monto, metodo_pago_id, usuario_id, venta_id))


def resumen(caja_id):
    caja = db.query("""SELECT c.*, ub.nombre AS ubicacion, ub.direccion,
                              ua.nombre AS usuario_apertura, uc.nombre AS usuario_cierre
                       FROM cajas c JOIN ubicaciones ub ON ub.id=c.ubicacion_id
                       JOIN usuarios ua ON ua.id=c.usuario_apertura_id
                       LEFT JOIN usuarios uc ON uc.id=c.usuario_cierre_id
                       WHERE c.id=%s""", (caja_id,), one=True)
    if not caja:
        return None
    efectivo_id = catalogos.id_metodo("EFECTIVO")
    por_tipo_rows = db.query(
        """SELECT tipo, metodo_pago_id, SUM(monto) AS total, COUNT(*) AS n
           FROM movimientos_caja WHERE caja_id=%s GROUP BY tipo, metodo_pago_id""", (caja_id,))
    metodos = {m["id"]: m for m in db.query("SELECT * FROM metodos_pago")}

    def suma(tipos, solo_efectivo=None):
        tot = Decimal(0)
        for r in por_tipo_rows:
            if r["tipo"] in tipos:
                if solo_efectivo is True and r["metodo_pago_id"] != efectivo_id:
                    continue
                tot += Decimal(r["total"])
        return tot

    ventas_efectivo = sum((Decimal(r["total"]) for r in por_tipo_rows
                           if r["tipo"] == "VENTA" and r["metodo_pago_id"] == efectivo_id), Decimal(0))
    cobros_efectivo = sum((Decimal(r["total"]) for r in por_tipo_rows
                           if r["tipo"] == "PAGO_CLIENTE" and r["metodo_pago_id"] == efectivo_id), Decimal(0))
    ingresos_ef = sum((Decimal(r["total"]) for r in por_tipo_rows
                       if r["tipo"] == "INGRESO" and r["metodo_pago_id"] == efectivo_id), Decimal(0))
    retiros_ef = sum((Decimal(r["total"]) for r in por_tipo_rows
                      if r["tipo"] == "RETIRO" and r["metodo_pago_id"] == efectivo_id), Decimal(0))
    gastos_ef = sum((Decimal(r["total"]) for r in por_tipo_rows
                     if r["tipo"] == "GASTO" and r["metodo_pago_id"] == efectivo_id), Decimal(0))
    devol_ef = sum((Decimal(r["total"]) for r in por_tipo_rows
                    if r["tipo"] == "DEVOLUCION" and r["metodo_pago_id"] == efectivo_id), Decimal(0))

    esperado = (Decimal(caja["monto_inicial"]) + ventas_efectivo + cobros_efectivo + ingresos_ef
                - retiros_ef - gastos_ef - devol_ef)

    # Ventas/cobros por método de pago (netos de devoluciones)
    por_metodo = {}
    for r in por_tipo_rows:
        nombre = metodos[r["metodo_pago_id"]]["nombre"]
        signo = 1 if r["tipo"] in TIPOS_INGRESO else -1
        por_metodo.setdefault(nombre, Decimal(0))
        por_metodo[nombre] += signo * Decimal(r["total"])

    movimientos = db.query(
        """SELECT mc.*, mp.nombre AS metodo, u.nombre AS usuario
           FROM movimientos_caja mc JOIN metodos_pago mp ON mp.id=mc.metodo_pago_id
           JOIN usuarios u ON u.id=mc.usuario_id
           WHERE mc.caja_id=%s ORDER BY mc.fecha DESC, mc.id DESC""", (caja_id,))
    cant_ventas = db.scalar("SELECT COUNT(*) FROM ventas WHERE caja_id=%s AND estado<>'Anulada'", (caja_id,))
    return {
        "caja": caja,
        "ventas_efectivo": ventas_efectivo,
        "cobros_efectivo": cobros_efectivo,
        "ingresos_efectivo": ingresos_ef,
        "retiros_efectivo": retiros_ef,
        "gastos_efectivo": gastos_ef,
        "devoluciones_efectivo": devol_ef,
        "ventas_total": suma(("VENTA",)),
        "egresos_total": suma(TIPOS_EGRESO),
        "esperado": esperado,
        "por_metodo": por_metodo,
        "movimientos": movimientos,
        "cant_ventas": cant_ventas,
    }


def cerrar(caja_id, usuario_id, efectivo_real, observaciones=None):
    res = resumen(caja_id)
    if not res:
        raise NegocioError("Caja inexistente.")
    if res["caja"]["estado"] != "ABIERTA":
        raise NegocioError("La caja ya está cerrada.")
    if efectivo_real < 0:
        raise NegocioError("El efectivo real no puede ser negativo.")
    esperado = res["esperado"]
    diferencia = Decimal(efectivo_real) - esperado
    with db.transaction() as tx:
        tx.execute(
            """UPDATE cajas SET estado='CERRADA', usuario_cierre_id=%s, fecha_cierre=NOW(),
                      efectivo_esperado=%s, efectivo_real=%s, diferencia=%s,
                      observaciones=CONCAT_WS(' | ', observaciones, %s)
               WHERE id=%s AND estado='ABIERTA'""",
            (usuario_id, esperado, efectivo_real, diferencia, observaciones, caja_id))
        if tx.rowcount != 1:
            raise NegocioError("No se pudo cerrar la caja (¿ya estaba cerrada?).")
    return esperado, diferencia
