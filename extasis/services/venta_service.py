"""Ventas (POS), anulaciones y devoluciones."""
from decimal import ROUND_HALF_UP, Decimal

from .. import db
from ..models import catalogos, configuracion, financiacion
from ..utils.audit import auditar
from . import NegocioError, caja_service, cc_service, stock_service

D0 = Decimal("0")


def _q(v):
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def crear_venta(data, user, ubicacion_id, es_admin=False):
    """data = {items:[{variante_id, cantidad, precio?}], descuento_tipo, descuento_valor,
               cliente_id, metodo_pago_id, observaciones}"""
    items = data.get("items") or []
    if not items:
        raise NegocioError("El carrito está vacío.")
    metodo_id = int(data.get("metodo_pago_id") or 0)
    metodo = db.query("SELECT * FROM metodos_pago WHERE id=%s AND activo=1", (metodo_id,), one=True)
    if not metodo:
        raise NegocioError("Seleccioná un método de pago.")
    cliente_id = data.get("cliente_id") or None
    cliente_id = int(cliente_id) if cliente_id else None
    if metodo["codigo"] == "CTACTE" and not cliente_id:
        raise NegocioError("Para vender a cuenta corriente hay que seleccionar un cliente.")
    permitir_sin_stock = configuracion.get_bool("permitir_venta_sin_stock")

    # agrupar por variante
    agrupado = {}
    for it in items:
        vid = int(it.get("variante_id") or 0)
        cant = int(it.get("cantidad") or 0)
        if vid <= 0 or cant <= 0:
            raise NegocioError("Cantidad inválida en el carrito.")
        if vid in agrupado:
            agrupado[vid]["cantidad"] += cant
        else:
            agrupado[vid] = {"cantidad": cant, "precio": it.get("precio")}

    with db.transaction() as tx:
        caja = caja_service.caja_abierta(ubicacion_id, tx)
        if not caja:
            raise NegocioError("No hay una caja abierta en este local. Abrí la caja para vender.")
        if cliente_id:
            cli = tx.query("SELECT id FROM clientes WHERE id=%s AND activo=1", (cliente_id,), one=True)
            if not cli:
                raise NegocioError("Cliente inválido.")

        lineas = []
        subtotal = D0
        for vid, info in agrupado.items():
            v = tx.query("""SELECT v.id, p.precio_venta, p.precio_compra, p.activo, v.activo AS vact
                            FROM variantes_producto v JOIN productos p ON p.id=v.producto_id
                            WHERE v.id=%s""", (vid,), one=True)
            if not v or not v["activo"] or not v["vact"]:
                raise NegocioError("Uno de los productos no existe o está inactivo.")
            precio = Decimal(v["precio_venta"])
            if es_admin and info.get("precio") not in (None, ""):
                precio = _q(Decimal(str(info["precio"])))
                if precio < 0:
                    raise NegocioError("Precio inválido.")
            etiqueta = stock_service.etiqueta_variante(tx, vid)
            disponible = stock_service.cantidad(tx, vid, ubicacion_id, lock=True)
            if disponible < info["cantidad"] and not permitir_sin_stock:
                raise NegocioError(f"Producto sin stock en este local: {etiqueta} (disponible {disponible}).")
            lineas.append((vid, info["cantidad"], precio, Decimal(v["precio_compra"]), etiqueta))
            subtotal += precio * info["cantidad"]

        subtotal = _q(subtotal)
        tipo = data.get("descuento_tipo") or "monto"
        valor = Decimal(str(data.get("descuento_valor") or 0))
        if valor < 0:
            raise NegocioError("El descuento no puede ser negativo.")
        descuento = _q(subtotal * valor / 100) if tipo == "porc" else _q(valor)
        if tipo == "porc" and valor > 100:
            raise NegocioError("El descuento no puede superar el 100%.")
        if descuento > subtotal:
            raise NegocioError("El descuento no puede superar el subtotal.")
        total = subtotal - descuento

        # Tarjeta de crédito / crédito personal: plan de cuotas con interés
        plan, recargo = None, D0
        tipo_fin = financiacion.TIPO_POR_METODO.get(metodo["codigo"])
        if tipo_fin:
            plan_id = data.get("plan_id")
            if plan_id:
                plan = financiacion.get_plan(int(plan_id), tx)
                if not plan or plan["tipo"] != tipo_fin or not plan["activo"] or not plan["entidad_activa"]:
                    raise NegocioError("El plan de cuotas elegido no es válido.")
            elif financiacion.hay_planes(tipo_fin):
                raise NegocioError("Elegí la tarjeta / crédito y la cantidad de cuotas.")
        if plan:
            recargo = _q(total * Decimal(plan["interes_pct"]) / 100)
            total = total + recargo

        venta_id = tx.execute(
            """INSERT INTO ventas (ubicacion_id, caja_id, usuario_id, cliente_id, subtotal, descuento, total,
                                   metodo_pago_id, observaciones, plan_id, entidad, cuotas, interes_pct, recargo)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (ubicacion_id, caja["id"], user["id"], cliente_id, subtotal, descuento, total, metodo_id,
             (data.get("observaciones") or "")[:255] or None,
             plan["id"] if plan else None, plan["entidad"] if plan else None, plan["cuotas"] if plan else None,
             plan["interes_pct"] if plan else 0, recargo))

        for vid, cant, precio, costo, etiqueta in lineas:
            tx.execute(
                """INSERT INTO detalle_ventas (venta_id, variante_id, cantidad, precio_unitario, costo_unitario)
                   VALUES (%s,%s,%s,%s,%s)""", (venta_id, vid, cant, precio, costo))
            stock_service.mover(tx, vid, ubicacion_id, -cant, permitir_negativo=permitir_sin_stock, etiqueta=etiqueta)
            stock_service.registrar_movimiento(tx, "VENTA", vid, cant, user["id"], origen_id=ubicacion_id,
                                               motivo=f"Venta N° {venta_id}", ref_tipo="venta", ref_id=venta_id)

        caja_service.registrar(tx, caja["id"], "VENTA", f"Venta N° {venta_id}", total, metodo_id, user["id"], venta_id)
        if metodo["codigo"] == "CTACTE":
            cc_service.cargar_debe(tx, cliente_id, total, f"Compra - Venta N° {venta_id}", user["id"], venta_id)
        auditar(f"{user['nombre']} registró la venta N° {venta_id} por ${total:,.2f}", "ventas", venta_id, tx)
    return venta_id


def get_venta(venta_id):
    v = db.query(
        """SELECT v.*, ub.nombre AS ubicacion, ub.direccion AS ubicacion_direccion, ub.telefono AS ubicacion_telefono,
                  u.nombre AS vendedor, mp.nombre AS metodo, mp.codigo AS metodo_codigo,
                  CONCAT(c.apellido, ', ', c.nombre) AS cliente, c.dni AS cliente_dni
           FROM ventas v JOIN ubicaciones ub ON ub.id=v.ubicacion_id
           JOIN usuarios u ON u.id=v.usuario_id JOIN metodos_pago mp ON mp.id=v.metodo_pago_id
           LEFT JOIN clientes c ON c.id=v.cliente_id WHERE v.id=%s""", (venta_id,), one=True)
    if not v:
        return None, []
    det = db.query(
        """SELECT dv.*, p.nombre AS producto, p.codigo_interno, t.nombre AS talle, c.nombre AS color,
                  vp.codigo_barras,
                  COALESCE((SELECT SUM(dd.cantidad) FROM detalle_devoluciones dd WHERE dd.detalle_venta_id=dv.id),0)
                    AS devuelto
           FROM detalle_ventas dv JOIN variantes_producto vp ON vp.id=dv.variante_id
           JOIN productos p ON p.id=vp.producto_id JOIN talles t ON t.id=vp.talle_id
           JOIN colores c ON c.id=vp.color_id WHERE dv.venta_id=%s ORDER BY dv.id""", (venta_id,))
    for d in det:
        d["subtotal"] = Decimal(d["precio_unitario"]) * d["cantidad"]
        d["pendiente"] = d["cantidad"] - int(d["devuelto"])
    return v, det


def _factor_descuento(venta):
    sub = Decimal(venta["subtotal"])
    if sub <= 0:
        return Decimal(1)
    return Decimal(venta["total"]) / sub


def anular(venta_id, user, motivo):
    if not motivo:
        raise NegocioError("Indicá el motivo de la anulación.")
    with db.transaction() as tx:
        v = tx.query("""SELECT v.*, mp.codigo AS metodo_codigo FROM ventas v
                        JOIN metodos_pago mp ON mp.id=v.metodo_pago_id WHERE v.id=%s FOR UPDATE""",
                     (venta_id,), one=True)
        if not v:
            raise NegocioError("Venta inexistente.")
        if v["estado"] != "Completada":
            raise NegocioError(f"La venta ya está {v['estado'].lower()}.")
        factor = _factor_descuento(v)
        det = tx.query(
            """SELECT dv.*, COALESCE((SELECT SUM(dd.cantidad) FROM detalle_devoluciones dd
                                      WHERE dd.detalle_venta_id=dv.id),0) AS devuelto
               FROM detalle_ventas dv WHERE dv.venta_id=%s""", (venta_id,))
        monto = D0
        for d in det:
            pend = d["cantidad"] - int(d["devuelto"])
            if pend <= 0:
                continue
            stock_service.mover(tx, d["variante_id"], v["ubicacion_id"], pend)
            stock_service.registrar_movimiento(tx, "ANULACION", d["variante_id"], pend, user["id"],
                                               destino_id=v["ubicacion_id"], motivo=f"Anulación venta N° {venta_id}: {motivo}",
                                               ref_tipo="venta", ref_id=venta_id)
            monto += Decimal(d["precio_unitario"]) * pend * factor
        monto = _q(monto)
        if monto > 0:
            if v["metodo_codigo"] == "CTACTE" and v["cliente_id"]:
                cc_service.cargar_haber(tx, v["cliente_id"], monto, f"Anulación venta N° {venta_id}", user["id"], venta_id)
            caja = tx.query("SELECT id FROM cajas WHERE id=%s AND estado='ABIERTA'", (v["caja_id"],), one=True)
            if not caja and v["metodo_codigo"] != "CTACTE":
                # el dinero se reintegra desde la caja abierta actual del local
                caja = caja_service.caja_abierta(v["ubicacion_id"], tx)
            if caja:
                caja_service.registrar(tx, caja["id"], "DEVOLUCION", f"Anulación venta N° {venta_id}", monto,
                                       v["metodo_pago_id"], user["id"], venta_id)
        tx.execute("UPDATE ventas SET estado='Anulada', observaciones=CONCAT_WS(' | ', observaciones, %s) WHERE id=%s",
                   (f"ANULADA: {motivo}"[:200], venta_id))
        auditar(f"{user['nombre']} anuló la venta N° {venta_id} ({motivo})", "ventas", venta_id, tx)


def devolver(venta_id, items, motivo, user, nuevos=None, metodo_id=None, plan_id=None):
    """Devolución o CAMBIO de productos de una venta.

    items  = {detalle_venta_id: cantidad devuelta}
    nuevos = [(variante_id, cantidad)] productos que el cliente se lleva a cambio (opcional)
    La diferencia (nuevos - devuelto) la paga el cliente o se le reintegra con `metodo_id`.
    Sólo la DIFERENCIA mueve dinero en la caja, así el cierre cuadra.
    """
    if not motivo:
        raise NegocioError("Indicá el motivo de la devolución.")
    items = {int(k): int(c) for k, c in items.items() if int(c or 0) > 0}
    nuevos = [(int(v), int(c)) for v, c in (nuevos or []) if int(c or 0) > 0]
    if not items:
        raise NegocioError("Seleccioná al menos un producto y cantidad a devolver.")
    metodo = None
    if metodo_id:
        metodo = db.query("SELECT * FROM metodos_pago WHERE id=%s AND activo=1", (int(metodo_id),), one=True)
    with db.transaction() as tx:
        v = tx.query("""SELECT v.*, mp.codigo AS metodo_codigo FROM ventas v
                        JOIN metodos_pago mp ON mp.id=v.metodo_pago_id WHERE v.id=%s FOR UPDATE""",
                     (venta_id,), one=True)
        if not v:
            raise NegocioError("Venta inexistente.")
        if v["estado"] != "Completada":
            raise NegocioError(f"No se puede devolver: la venta está {v['estado'].lower()}.")
        ub = v["ubicacion_id"]
        caja = caja_service.caja_abierta(ub, tx)
        if not caja:
            raise NegocioError("Para registrar una devolución o un cambio tiene que haber una caja abierta en el local.")
        factor = _factor_descuento(v)
        era_ctacte = v["metodo_codigo"] == "CTACTE"

        dev_id = tx.execute(
            """INSERT INTO devoluciones (venta_id, ubicacion_id, usuario_id, caja_id, motivo, total, reintegro)
               VALUES (%s,%s,%s,%s,%s,0,'NINGUNO')""",
            (venta_id, ub, user["id"], caja["id"], motivo[:255]))
        devuelto = D0
        for det_id, cant in items.items():
            d = tx.query(
                """SELECT dv.*, COALESCE((SELECT SUM(dd.cantidad) FROM detalle_devoluciones dd
                                          WHERE dd.detalle_venta_id=dv.id),0) AS devuelto
                   FROM detalle_ventas dv WHERE dv.id=%s AND dv.venta_id=%s""", (det_id, venta_id), one=True)
            if not d:
                raise NegocioError("Ítem de venta inválido.")
            pend = d["cantidad"] - int(d["devuelto"])
            if cant > pend:
                raise NegocioError(f"No se pueden devolver {cant} unidades (máximo {pend}).")
            monto = _q(Decimal(d["precio_unitario"]) * cant * factor)
            devuelto += monto
            tx.execute("INSERT INTO detalle_devoluciones (devolucion_id, detalle_venta_id, cantidad, monto) VALUES (%s,%s,%s,%s)",
                       (dev_id, det_id, cant, monto))
            stock_service.mover(tx, d["variante_id"], ub, cant)
            stock_service.registrar_movimiento(tx, "DEVOLUCION", d["variante_id"], cant, user["id"], destino_id=ub,
                                               motivo=f"Devolución venta N° {venta_id}: {motivo}",
                                               ref_tipo="devolucion", ref_id=dev_id)

        # Venta original en cuenta corriente: lo devuelto descuenta la deuda del cliente
        credito = devuelto
        if era_ctacte and v["cliente_id"]:
            cc_service.cargar_haber(tx, v["cliente_id"], devuelto, f"Devolución N° {dev_id} (venta {venta_id})",
                                    user["id"], venta_id)
            credito = D0

        # Productos que se lleva a cambio
        nuevo_total, lineas = D0, []
        for vid, cant in nuevos:
            p = tx.query("""SELECT v.id, p.precio_venta, p.precio_compra, p.activo, v.activo AS vact
                            FROM variantes_producto v JOIN productos p ON p.id=v.producto_id WHERE v.id=%s""",
                         (vid,), one=True)
            if not p or not p["activo"] or not p["vact"]:
                raise NegocioError("Uno de los productos del cambio no existe o está inactivo.")
            etq = stock_service.etiqueta_variante(tx, vid)
            if stock_service.cantidad(tx, vid, ub, lock=True) < cant and not configuracion.get_bool("permitir_venta_sin_stock"):
                raise NegocioError(f"Producto sin stock en este local: {etq}.")
            lineas.append((vid, cant, Decimal(p["precio_venta"]), Decimal(p["precio_compra"]), etq))
            nuevo_total += Decimal(p["precio_venta"]) * cant
        nuevo_total = _q(nuevo_total)

        usado = min(credito, nuevo_total)
        diferencia = nuevo_total - credito          # > 0 paga el cliente · < 0 se le devuelve
        if diferencia != 0 and not metodo:
            raise NegocioError("Elegí con qué medio de pago se " + ("cobra" if diferencia > 0 else "devuelve") + " la diferencia.")
        if metodo and metodo["codigo"] == "CTACTE" and not v["cliente_id"] and diferencia != 0:
            raise NegocioError("La venta no tiene cliente: no se puede usar cuenta corriente.")

        venta_nueva = None
        recargo, plan = D0, None
        if lineas:
            if diferencia > 0:
                tipo_fin = financiacion.TIPO_POR_METODO.get(metodo["codigo"])
                if tipo_fin and plan_id:
                    plan = financiacion.get_plan(int(plan_id), tx)
                    if not plan or plan["tipo"] != tipo_fin:
                        raise NegocioError("El plan de cuotas elegido no es válido.")
                    recargo = _q(diferencia * Decimal(plan["interes_pct"]) / 100)
            metodo_venta = metodo["id"] if (metodo and diferencia > 0) else catalogos.id_metodo("EFECTIVO")
            venta_nueva = tx.execute(
                """INSERT INTO ventas (ubicacion_id, caja_id, usuario_id, cliente_id, subtotal, descuento, total, metodo_pago_id,
                                       observaciones, credito_cambio, devolucion_origen_id, plan_id, entidad, cuotas, interes_pct, recargo)
                   VALUES (%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (ub, caja["id"], user["id"], v["cliente_id"], nuevo_total, nuevo_total + recargo, metodo_venta,
                 f"Cambio de la venta N° {venta_id}", usado, dev_id, plan["id"] if plan else None,
                 plan["entidad"] if plan else None, plan["cuotas"] if plan else None,
                 plan["interes_pct"] if plan else 0, recargo))
            for vid, cant, precio, costo, etq in lineas:
                tx.execute("""INSERT INTO detalle_ventas (venta_id, variante_id, cantidad, precio_unitario, costo_unitario)
                              VALUES (%s,%s,%s,%s,%s)""", (venta_nueva, vid, cant, precio, costo))
                stock_service.mover(tx, vid, ub, -cant, permitir_negativo=configuracion.get_bool("permitir_venta_sin_stock"),
                                    etiqueta=etq)
                stock_service.registrar_movimiento(tx, "VENTA", vid, cant, user["id"], origen_id=ub,
                                                   motivo=f"Cambio (venta N° {venta_nueva})", ref_tipo="venta",
                                                   ref_id=venta_nueva)

        # Dinero: sólo se mueve la diferencia
        if diferencia > 0:
            monto = diferencia + recargo
            if metodo["codigo"] == "CTACTE":
                cc_service.cargar_debe(tx, v["cliente_id"], monto, f"Diferencia cambio - Venta N° {venta_nueva}",
                                       user["id"], venta_nueva)
            caja_service.registrar(tx, caja["id"], "VENTA", f"Diferencia por cambio · venta N° {venta_nueva}",
                                   monto, metodo["id"], user["id"], venta_nueva)
        elif diferencia < 0:
            monto = -diferencia
            if metodo["codigo"] == "CTACTE":
                cc_service.cargar_haber(tx, v["cliente_id"], monto, f"Devolución N° {dev_id} (venta {venta_id})",
                                        user["id"], venta_id)
            else:
                caja_service.registrar(tx, caja["id"], "DEVOLUCION", f"Devolución N° {dev_id} (venta {venta_id})",
                                       monto, metodo["id"], user["id"], venta_id)

        if lineas:
            reintegro = "CAMBIO"
        elif era_ctacte or (metodo and metodo["codigo"] == "CTACTE"):
            reintegro = "CUENTA_CORRIENTE"
        else:
            reintegro = "EFECTIVO" if diferencia != 0 else "NINGUNO"
        tx.execute("""UPDATE devoluciones SET total=%s, reintegro=%s, metodo_pago_id=%s, diferencia=%s, venta_cambio_id=%s
                      WHERE id=%s""",
                   (devuelto, reintegro, metodo["id"] if metodo and diferencia != 0 else None, diferencia, venta_nueva, dev_id))

        pendientes = tx.scalar(
            """SELECT SUM(dv.cantidad - COALESCE((SELECT SUM(dd.cantidad) FROM detalle_devoluciones dd
                                                   WHERE dd.detalle_venta_id=dv.id),0)) AS p
               FROM detalle_ventas dv WHERE dv.venta_id=%s""", (venta_id,), 0)
        if int(pendientes) <= 0:
            tx.execute("UPDATE ventas SET estado='Devuelta' WHERE id=%s", (venta_id,))
        txt = f"{user['nombre']} registró la devolución N° {dev_id} de la venta N° {venta_id} por ${devuelto:,.2f}"
        if venta_nueva:
            txt += f" con cambio (venta N° {venta_nueva}, diferencia ${diferencia:,.2f})"
        auditar(txt, "devoluciones", dev_id, tx)
    return dev_id, venta_nueva
