import csv
import io
from datetime import date, timedelta

from flask import Blueprint, Response, render_template, request

from .. import db
from ..models import configuracion, ubicaciones
from ..services import reportes_service
from ..utils.auth import permiso_required
from ..utils.helpers import PERIODOS, periodo, to_int

bp = Blueprint("reportes", __name__, url_prefix="/reportes")

AGRUPACIONES = [("dia", "Día"), ("local", "Local"), ("vendedor", "Vendedor"), ("producto", "Producto"),
                ("categoria", "Categoría"), ("temporada", "Temporada"), ("metodo", "Método de pago"), ("mes", "Mes")]


def _periodo(args, default_dias=30):
    """Hoy / últimos 7 días / este mes / mes anterior, o ?desde=&hasta=. Sin nada: este mes."""
    desde, hasta, hasta_ex, _clave = periodo(args, "mes")
    return desde, hasta, hasta_ex


@bp.route("/")
@permiso_required("reportes.ver")
def ventas():
    args = request.args
    desde, hasta, hasta_ex = _periodo(args)
    ub = to_int(args.get("ubicacion_id"))
    por = args.get("por") if args.get("por") in dict(AGRUPACIONES) else "local"
    tot = reportes_service.totales_ventas(desde, hasta_ex, ub)
    filas = reportes_service.ventas_agrupadas(desde, hasta_ex, por, ub)
    if args.get("csv") == "1":
        out = io.StringIO()
        w = csv.writer(out, delimiter=";")
        w.writerow([dict(AGRUPACIONES)[por], "Operaciones", "Unidades", "Ventas", "Costo", "Ganancia bruta"])
        for f in filas:
            w.writerow([f["etiqueta"], f["operaciones"], f["unidades"], f"{f['total']:.2f}".replace(".", ","),
                        f"{f['costo']:.2f}".replace(".", ","), f"{f['ganancia_bruta']:.2f}".replace(".", ",")])
        return Response("﻿" + out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=ventas_{por}_{desde}_{hasta}.csv"})
    return render_template("reportes/ventas.html", tot=tot, filas=filas, por=por, agrupaciones=AGRUPACIONES,
                           desde=desde, hasta=hasta, ubics=ubicaciones.locales(False), ub=ub)


@bp.route("/stock")
@permiso_required("reportes.ver")
def stock():
    args = request.args
    por_ub = reportes_service.stock_por_ubicacion()
    desde, hasta, hasta_ex = _periodo(args, 30)
    top = reportes_service.ventas_agrupadas(desde, hasta_ex, "producto", None, limite=15)
    sin_stock = db.query("""SELECT p.id, p.nombre, p.codigo_interno FROM productos p WHERE p.activo=1 AND
                            COALESCE((SELECT SUM(s.cantidad) FROM stock s JOIN variantes_producto v ON v.id=s.variante_id
                                      WHERE v.producto_id=p.id),0) <= 0 ORDER BY p.nombre LIMIT 200""")
    bajo = db.scalar("""SELECT COUNT(*) FROM stock s JOIN variantes_producto v ON v.id=s.variante_id
                        JOIN productos p ON p.id=v.producto_id
                        WHERE p.activo=1 AND s.cantidad>0 AND s.cantidad<=s.stock_minimo""")
    dias_ant = configuracion.get_int("dias_antiguedad_producto", 180)
    antiguos = db.query("""SELECT p.id, p.nombre, p.creado_en, SUM(s.cantidad) AS unidades,
                                  (SELECT MAX(v2.fecha) FROM ventas v2 JOIN detalle_ventas d2 ON d2.venta_id=v2.id
                                   JOIN variantes_producto vp2 ON vp2.id=d2.variante_id WHERE vp2.producto_id=p.id) AS ultima_venta
                           FROM productos p JOIN variantes_producto v ON v.producto_id=p.id
                           JOIN stock s ON s.variante_id=v.id AND s.cantidad>0
                           WHERE p.activo=1 AND p.creado_en < (NOW() - INTERVAL %s DAY)
                           GROUP BY p.id, p.nombre, p.creado_en ORDER BY p.creado_en LIMIT 100""", (dias_ant,))
    por_cat = db.query("""SELECT COALESCE(c.nombre,'Sin categoría') AS etiqueta, SUM(s.cantidad) AS unidades
                          FROM stock s JOIN variantes_producto v ON v.id=s.variante_id JOIN productos p ON p.id=v.producto_id
                          LEFT JOIN categorias c ON c.id=p.categoria_id WHERE s.cantidad>0
                          GROUP BY c.nombre ORDER BY unidades DESC""")
    return render_template("reportes/stock.html", por_ub=por_ub, top=top, sin_stock=sin_stock, bajo=bajo,
                           antiguos=antiguos, dias_ant=dias_ant, por_cat=por_cat, desde=desde, hasta=hasta)


@bp.route("/ganancias")
@permiso_required("reportes.ver")
def ganancias():
    args = request.args
    desde, hasta, hasta_ex, clave = periodo(args, "mes")
    ub = to_int(args.get("ubicacion_id"))
    total = reportes_service.ganancia(desde, hasta_ex, ub)
    # sin filtro de local: una fila por local + "Negocio general" (gastos/sueldos sin local asignado)
    por_local = [f for f in reportes_service.ganancia_por_local(desde, hasta_ex)
                 if f["etiqueta"] == "Negocio general" or f["ventas"] or f["gastos"] or f["sueldos"]] if not ub else []
    por_prod = reportes_service.ventas_agrupadas(desde, hasta_ex, "producto", ub, limite=30)
    if args.get("csv") == "1":
        out = io.StringIO()
        w = csv.writer(out, delimiter=";")
        num = lambda v: f"{v:.2f}".replace(".", ",")
        w.writerow(["Local", "Ventas netas", "Costo mercadería vendida", "Ganancia bruta", "Gastos", "Sueldos",
                    "Ganancia neta"])
        for f in (por_local or [dict(total, etiqueta="Seleccionado")]):
            w.writerow([f["etiqueta"], num(f["ventas"]), num(f["costo"]), num(f["bruta"]), num(f["gastos"]),
                        num(f["sueldos"]), num(f["neta"])])
        w.writerow(["TOTAL", num(total["ventas"]), num(total["costo"]), num(total["bruta"]), num(total["gastos"]),
                    num(total["sueldos"]), num(total["neta"])])
        w.writerow([])
        w.writerow(["Producto", "Prendas", "Ventas", "Costo", "Ganancia bruta"])
        for f in por_prod:
            w.writerow([f["etiqueta"], f["unidades"], num(f["total"]), num(f["costo"]), num(f["ganancia_bruta"])])
        return Response("﻿" + out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=ganancias_{desde}_{hasta}.csv"})
    return render_template("reportes/ganancias.html", total=total, por_local=por_local,
                           mensual=reportes_service.ganancia_mensual(12, ub), por_prod=por_prod,
                           por_cat=reportes_service.ventas_agrupadas(desde, hasta_ex, "categoria", ub),
                           sin_costo=reportes_service.lineas_sin_costo(desde, hasta_ex, ub),
                           desde=desde, hasta=hasta, clave=clave, periodos=PERIODOS,
                           ubics=ubicaciones.locales(), ub=ub)


@bp.route("/caja")
@permiso_required("reportes.ver")
def caja():
    args = request.args
    desde, hasta, hasta_ex = _periodo(args, 30)
    ub = to_int(args.get("ubicacion_id"))
    cajas, movs = reportes_service.caja_resumen(desde, hasta_ex, ub)
    dif_total = sum((c["diferencia"] or 0) for c in cajas)
    ingresos = sum(m["total"] for m in movs if m["tipo"] in ("VENTA", "PAGO_CLIENTE", "INGRESO"))
    egresos = sum(m["total"] for m in movs if m["tipo"] in ("RETIRO", "GASTO", "DEVOLUCION"))
    metodos = {}
    for m in movs:
        signo = 1 if m["tipo"] in ("VENTA", "PAGO_CLIENTE", "INGRESO") else -1
        metodos[m["metodo"]] = metodos.get(m["metodo"], 0) + signo * m["total"]
    return render_template("reportes/caja.html", cajas=cajas, movs=movs, dif_total=dif_total, ingresos=ingresos,
                           egresos=egresos, metodos=metodos, desde=desde, hasta=hasta,
                           ubics=ubicaciones.locales(False), ub=ub)
