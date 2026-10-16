"""Cuentas corrientes de clientes (Debe / Haber / Saldo)."""
from decimal import Decimal

from .. import db
from ..models import catalogos
from . import NegocioError
from . import caja_service


def cuenta_de(tx, cliente_id, crear=True):
    row = tx.query("SELECT * FROM cuentas_corrientes WHERE cliente_id=%s", (cliente_id,), one=True)
    if row or not crear:
        return row
    cid = tx.execute("INSERT INTO cuentas_corrientes (cliente_id) VALUES (%s)", (cliente_id,))
    return tx.query("SELECT * FROM cuentas_corrientes WHERE id=%s", (cid,), one=True)


def saldo(cliente_id):
    return Decimal(db.scalar("SELECT saldo FROM v_saldos_cc WHERE cliente_id=%s", (cliente_id,), 0) or 0)


def saldo_tx(tx, cuenta_id):
    return Decimal(tx.scalar("SELECT COALESCE(SUM(debe-haber),0) AS s FROM movimientos_cuenta_corriente WHERE cuenta_id=%s",
                             (cuenta_id,), 0))


def cargar_debe(tx, cliente_id, monto, concepto, usuario_id, venta_id=None):
    cuenta = cuenta_de(tx, cliente_id)
    limite = Decimal(cuenta["limite_credito"] or 0)
    if limite > 0 and saldo_tx(tx, cuenta["id"]) + Decimal(monto) > limite:
        raise NegocioError(f"La operación supera el límite de crédito del cliente (${limite:,.2f}).")
    tx.execute(
        """INSERT INTO movimientos_cuenta_corriente (cuenta_id, concepto, debe, venta_id, metodo_pago_id, usuario_id)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (cuenta["id"], concepto, monto, venta_id, catalogos.id_metodo("CTACTE"), usuario_id))


def cargar_haber(tx, cliente_id, monto, concepto, usuario_id, venta_id=None, metodo_pago_id=None):
    cuenta = cuenta_de(tx, cliente_id)
    tx.execute(
        """INSERT INTO movimientos_cuenta_corriente (cuenta_id, concepto, haber, venta_id, metodo_pago_id, usuario_id)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (cuenta["id"], concepto, monto, venta_id, metodo_pago_id, usuario_id))


def registrar_pago(cliente_id, monto, metodo_pago_id, usuario_id, ubicacion_id=None, concepto=None):
    """Pago (total o parcial) del cliente. Si hay caja abierta en el local, ingresa a la caja."""
    monto = Decimal(monto)
    if monto <= 0:
        raise NegocioError("El monto debe ser mayor a cero.")
    if int(metodo_pago_id) == catalogos.id_metodo("CTACTE"):
        raise NegocioError("Elegí cómo paga el cliente (efectivo, transferencia, etc.).")
    with db.transaction() as tx:
        caja = caja_service.caja_abierta(ubicacion_id, tx) if ubicacion_id else None
        if ubicacion_id and not caja:
            raise NegocioError("Para cobrar en el local tiene que haber una caja abierta.")
        cli = tx.query("SELECT nombre, apellido FROM clientes WHERE id=%s", (cliente_id,), one=True)
        if not cli:
            raise NegocioError("Cliente inexistente.")
        concepto = concepto or "Pago a cuenta"
        cargar_haber(tx, cliente_id, monto, concepto, usuario_id, metodo_pago_id=metodo_pago_id)
        if caja:
            caja_service.registrar(tx, caja["id"], "PAGO_CLIENTE",
                                   f"Pago CC {cli['apellido']}, {cli['nombre']}", monto, metodo_pago_id, usuario_id)
    return True


def movimientos(cliente_id):
    rows = db.query(
        """SELECT m.*, u.nombre AS usuario, mp.nombre AS metodo
           FROM movimientos_cuenta_corriente m
           JOIN cuentas_corrientes cc ON cc.id=m.cuenta_id
           JOIN usuarios u ON u.id=m.usuario_id
           LEFT JOIN metodos_pago mp ON mp.id=m.metodo_pago_id
           WHERE cc.cliente_id=%s ORDER BY m.fecha, m.id""", (cliente_id,))
    s = Decimal(0)
    for r in rows:
        s += Decimal(r["debe"]) - Decimal(r["haber"])
        r["saldo"] = s
    return rows
