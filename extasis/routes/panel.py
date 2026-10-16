"""Panel del dueño: depósito central, ficha de cada local y comparativa entre locales.

Todo se calcula con los datos reales (stock, ventas netas de devoluciones/anulaciones,
costos guardados en cada venta, gastos y sueldos registrados). Sólo para el administrador.
"""
import csv
import io

from flask import Blueprint, Response, abort, render_template, request

from .. import db
from ..models import ubicaciones
from ..services import caja_service, reportes_service
from ..utils.auth import admin_required
from ..utils.helpers import PERIODOS, clean, paginar, periodo, to_int

bp = Blueprint("panel", __name__, url_prefix="/panel")


def _stock_de(ubicacion_id, args, solo_con_stock=True):
    """Stock de UNA ubicación por variante (nunca mezclado con otras ubicaciones)."""
    where, params = ["s.ubicacion_id=%s", "p.activo=1", "v.activo=1"], [ubicacion_id]
    q = clean(args.get("q"))
    if q:
        where.append("(p.nombre LIKE %s OR p.codigo_interno=%s OR v.codigo_barras=%s OR p.codigo_barras=%s)")
        params += [f"%{q}%", q, q, q]
    if solo_con_stock:
        where.append("s.cantidad > 0")
    if args.get("estado") == "bajo":
        where.append("s.cantidad <= s.stock_minimo")
    w = " AND ".join(where)
    base = f"""FROM stock s JOIN variantes_producto v ON v.id=s.variante_id
               JOIN productos p ON p.id=v.producto_id JOIN talles t ON t.id=v.talle_id
               JOIN colores c ON c.id=v.color_id WHERE {w}"""
    columnas = f"""SELECT p.id AS producto_id, p.nombre AS producto, p.codigo_interno, v.codigo_barras,
                          t.nombre AS talle, c.nombre AS color, c.hex, s.cantidad, s.stock_minimo,
                          p.precio_compra, p.precio_venta, s.cantidad * p.precio_compra AS valor_costo
                   {base} ORDER BY p.nombre, c.nombre, t.orden"""
    return base, columnas, params


def _csv(nombre, encabezados, filas):
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(encabezados)
    for f in filas:
        w.writerow([str(x).replace(".", ",") if isinstance(x, float) or hasattr(x, "quantize") else x for x in f])
    return Response("﻿" + out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={nombre}.csv"})


def _ultimos_movimientos(ubicacion_id, limite=15):
    return db.query("""SELECT m.fecha, m.tipo, m.cantidad, m.motivo, p.nombre AS producto, t.nombre AS talle,
                              c.nombre AS color, uo.nombre AS origen, ud.nombre AS destino, u.nombre AS usuario
                       FROM movimientos_stock m JOIN variantes_producto v ON v.id=m.variante_id
                       JOIN productos p ON p.id=v.producto_id JOIN talles t ON t.id=v.talle_id
                       JOIN colores c ON c.id=v.color_id JOIN usuarios u ON u.id=m.usuario_id
                       LEFT JOIN ubicaciones uo ON uo.id=m.origen_id LEFT JOIN ubicaciones ud ON ud.id=m.destino_id
                       WHERE m.origen_id=%s OR m.destino_id=%s
                       ORDER BY m.fecha DESC, m.id DESC LIMIT %s""", (ubicacion_id, ubicacion_id, limite))


# ------------------------------------------------------------------ Depósito central
@bp.route("/deposito")
@admin_required
def deposito():
    dep = ubicaciones.deposito_central() or abort(404)
    args = request.args
    base, columnas, params = _stock_de(dep["id"], args, solo_con_stock=args.get("todos") != "1")
    if args.get("csv") == "1":
        filas = db.query(columnas, params)
        return _csv("stock_deposito", ["Producto", "Código", "Código de barras", "Talle", "Color", "Cantidad",
                                       "Stock mínimo", "Costo unitario", "Precio de venta", "Valor a costo"],
                    [[f["producto"], f["codigo_interno"] or "", f["codigo_barras"] or "", f["talle"], f["color"],
                      f["cantidad"], f["stock_minimo"], f["precio_compra"], f["precio_venta"], f["valor_costo"]]
                     for f in filas])
    pag = paginar(db.scalar(f"SELECT COUNT(*) {base}", params))
    rows = db.query(columnas + " LIMIT %s OFFSET %s", params + [pag.per_page, pag.offset])
    desde, hasta, hasta_ex, clave = periodo(args, "mes")
    return render_template("panel/deposito.html", dep=dep, resumen=reportes_service.resumen_stock(dep["id"]),
                           rows=rows, pag=pag, movs=_ultimos_movimientos(dep["id"]),
                           mov_periodo=reportes_service.resumen_movimientos(desde, hasta_ex, dep["id"]),
                           envios=db.query("""SELECT ud.nombre AS destino, COUNT(DISTINCT t.id) AS envios,
                                                     COALESCE(SUM(d.cantidad),0) AS unidades
                                              FROM transferencias t JOIN ubicaciones ud ON ud.id=t.destino_id
                                              JOIN detalle_transferencias d ON d.transferencia_id=t.id
                                              WHERE t.origen_id=%s AND t.fecha>=%s AND t.fecha<%s
                                              GROUP BY ud.id, ud.nombre ORDER BY ud.id""",
                                           (dep["id"], desde, hasta_ex)),
                           periodos=PERIODOS, clave=clave, desde=desde, hasta=hasta)


# ------------------------------------------------------------------ Locales: comparativa
@bp.route("/locales")
@admin_required
def locales():
    desde, hasta, hasta_ex, clave = periodo(request.args, "mes")
    filas = reportes_service.comparativa_locales(desde, hasta_ex)
    destacados = {}
    if filas:
        destacados = {
            "vende_mas": max(filas, key=lambda f: f["ventas"]),
            "gana_mas": max(filas, key=lambda f: f["bruta"]),
            "reponer": max(filas, key=lambda f: f["stock"]["por_agotarse"]),
        }
    return render_template("panel/locales.html", filas=filas, destacados=destacados,
                           periodos=PERIODOS, clave=clave, desde=desde, hasta=hasta)


# ------------------------------------------------------------------ Ficha de un local
@bp.route("/locales/<int:lid>")
@admin_required
def local(lid):
    loc = ubicaciones.get(lid)
    if not loc or loc["tipo"] != "LOCAL":
        abort(404)
    args = request.args
    desde, hasta, hasta_ex, clave = periodo(args, "mes")
    base, columnas, params = _stock_de(lid, args, solo_con_stock=args.get("todos") != "1")
    if args.get("csv") == "1":
        filas = db.query(columnas, params)
        return _csv(f"stock_local_{lid}", ["Producto", "Código", "Código de barras", "Talle", "Color", "Cantidad",
                                           "Stock mínimo", "Costo unitario", "Precio de venta", "Valor a costo"],
                    [[f["producto"], f["codigo_interno"] or "", f["codigo_barras"] or "", f["talle"], f["color"],
                      f["cantidad"], f["stock_minimo"], f["precio_compra"], f["precio_venta"], f["valor_costo"]]
                     for f in filas])
    pag = paginar(db.scalar(f"SELECT COUNT(*) {base}", params))
    rows = db.query(columnas + " LIMIT %s OFFSET %s", params + [pag.per_page, pag.offset])
    caja = caja_service.caja_abierta(lid)
    ventas = db.query("""SELECT v.id, v.fecha, v.total, v.estado, mp.nombre AS metodo, u.nombre AS vendedor,
                                (SELECT SUM(cantidad) FROM detalle_ventas d WHERE d.venta_id=v.id) AS unidades
                         FROM ventas v JOIN metodos_pago mp ON mp.id=v.metodo_pago_id
                         JOIN usuarios u ON u.id=v.usuario_id
                         WHERE v.ubicacion_id=%s AND v.fecha>=%s AND v.fecha<%s
                         ORDER BY v.id DESC LIMIT 15""", (lid, desde, hasta_ex))
    bajo = db.query("""SELECT p.nombre AS producto, t.nombre AS talle, c.nombre AS color, s.cantidad, s.stock_minimo,
                              COALESCE((SELECT s2.cantidad FROM stock s2 WHERE s2.variante_id=s.variante_id
                                        AND s2.ubicacion_id=%s),0) AS en_deposito
                       FROM stock s JOIN variantes_producto v ON v.id=s.variante_id
                       JOIN productos p ON p.id=v.producto_id JOIN talles t ON t.id=v.talle_id
                       JOIN colores c ON c.id=v.color_id
                       WHERE s.ubicacion_id=%s AND p.activo=1 AND v.activo=1 AND s.cantidad<=s.stock_minimo
                       ORDER BY s.cantidad, p.nombre LIMIT 15""",
                    ((ubicaciones.deposito_central() or {}).get("id"), lid))
    return render_template(
        "panel/local.html", loc=loc, locales=ubicaciones.locales(),
        res=reportes_service.ganancia(desde, hasta_ex, lid),
        sin_costo=reportes_service.lineas_sin_costo(desde, hasta_ex, lid),
        stock=reportes_service.resumen_stock(lid), rows=rows, pag=pag, bajo=bajo, ventas=ventas,
        por_metodo=reportes_service.ventas_agrupadas(desde, hasta_ex, "metodo", lid),
        top=reportes_service.ventas_agrupadas(desde, hasta_ex, "producto", lid, limite=10),
        movs=_ultimos_movimientos(lid), caja=caja, caja_resumen=caja_service.resumen(caja["id"]) if caja else None,
        periodos=PERIODOS, clave=clave, desde=desde, hasta=hasta)
