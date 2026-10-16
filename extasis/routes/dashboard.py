from datetime import date, timedelta

from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for

from .. import db
from ..models import ubicaciones
from ..services import caja_service, reportes_service
from ..utils.auth import es_admin, login_required, ubicacion_scope
from ..utils.helpers import PERIODOS, periodo

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def index():
    hoy = date.today()
    manana = hoy + timedelta(days=1)
    inicio_mes = hoy.replace(day=1)
    if es_admin():
        return _panel_dueno()

    ub = g.user["ubicacion_id"]
    if not ub:
        return render_template("errores/error.html", codigo=403,
                               mensaje="Tu usuario no tiene un local asignado. Avisale al administrador.")
    hoy_t = reportes_service.totales_ventas(hoy, manana, ub)
    mes_t = reportes_service.totales_ventas(inicio_mes, manana, ub)
    caja = caja_service.caja_abierta(ub)
    resumen = caja_service.resumen(caja["id"]) if caja else None
    stock_local = db.scalar("SELECT COALESCE(SUM(cantidad),0) FROM stock WHERE ubicacion_id=%s AND cantidad>0", (ub,))
    bajo = db.query("""SELECT p.nombre AS producto, t.nombre AS talle, c.nombre AS color, s.cantidad, s.stock_minimo
                       FROM stock s JOIN variantes_producto v ON v.id=s.variante_id
                       JOIN productos p ON p.id=v.producto_id JOIN talles t ON t.id=v.talle_id
                       JOIN colores c ON c.id=v.color_id
                       WHERE s.ubicacion_id=%s AND p.activo=1 AND s.cantidad<=s.stock_minimo
                       ORDER BY s.cantidad, p.nombre LIMIT 10""", (ub,))
    ultimas = db.query("""SELECT v.id, v.fecha, v.total, v.estado, mp.nombre AS metodo
                          FROM ventas v JOIN metodos_pago mp ON mp.id=v.metodo_pago_id
                          WHERE v.ubicacion_id=%s ORDER BY v.id DESC LIMIT 8""", (ub,))
    return render_template("dashboard/local.html", hoy=hoy_t, mes=mes_t, caja=caja, resumen=resumen,
                           stock_local=stock_local, bajo=bajo, ultimas=ultimas)


def _panel_dueno():
    """Inicio del dueño: resumen general, cada local por separado y el depósito."""
    desde, hasta, hasta_ex, clave = periodo(request.args, "hoy")

    deposito = ubicaciones.deposito_central()
    if deposito:
        deposito["stock"] = reportes_service.resumen_stock(deposito["id"])
        deposito["envios"] = db.query(
            """SELECT t.id, t.fecha, ud.nombre AS destino,
                      (SELECT SUM(cantidad) FROM detalle_transferencias d WHERE d.transferencia_id=t.id) AS unidades
               FROM transferencias t JOIN ubicaciones ud ON ud.id=t.destino_id
               WHERE t.origen_id=%s ORDER BY t.id DESC LIMIT 5""", (deposito["id"],))

    locales = ubicaciones.locales()
    for loc in locales:
        loc["ventas"] = reportes_service.ganancia(desde, hasta_ex, loc["id"])
        loc["por_metodo"] = reportes_service.ventas_agrupadas(desde, hasta_ex, "metodo", loc["id"])
        loc["stock"] = reportes_service.resumen_stock(loc["id"])
        caja = caja_service.caja_abierta(loc["id"])
        loc["caja"] = caja
        loc["caja_resumen"] = caja_service.resumen(caja["id"]) if caja else None
        loc["ultimas"] = db.query(
            """SELECT v.id, v.fecha, v.total, v.estado, mp.nombre AS metodo
               FROM ventas v JOIN metodos_pago mp ON mp.id=v.metodo_pago_id
               WHERE v.ubicacion_id=%s ORDER BY v.id DESC LIMIT 5""", (loc["id"],))

    return render_template("dashboard/admin.html", periodos=PERIODOS, clave=clave, desde=desde, hasta=hasta,
                           total=reportes_service.ganancia(desde, hasta_ex),
                           sin_costo=reportes_service.lineas_sin_costo(desde, hasta_ex),
                           stock=reportes_service.resumen_stock(),
                           movs=reportes_service.resumen_movimientos(desde, hasta_ex),
                           deposito=deposito, locales=locales)


@bp.route("/api/dashboard/graficos")
@login_required
def graficos():
    hoy = date.today()
    manana = hoy + timedelta(days=1)
    scope = ubicacion_scope()
    hace7 = hoy - timedelta(days=6)
    dias = {(hace7 + timedelta(days=i)): 0 for i in range(7)}
    for r in reportes_service.ventas_agrupadas(hace7, manana, "dia", scope):
        dias[r["etiqueta"]] = float(r["total"])
    data = {
        "ultimos7": {"labels": [d.strftime("%d/%m") for d in dias], "values": list(dias.values())},
    }
    inicio_mes = hoy.replace(day=1)
    metodo = reportes_service.ventas_agrupadas(inicio_mes, manana, "metodo", scope)
    data["metodos"] = {"labels": [r["etiqueta"] for r in metodo], "values": [float(r["total"]) for r in metodo]}
    top = reportes_service.ventas_agrupadas(inicio_mes, manana, "producto", scope, limite=8)
    data["top"] = {"labels": [r["etiqueta"] for r in top], "values": [int(r["unidades"]) for r in top]}
    cat = reportes_service.ventas_agrupadas(inicio_mes, manana, "categoria", scope)
    data["categorias"] = {"labels": [r["etiqueta"] for r in cat], "values": [float(r["total"]) for r in cat]}
    if scope is None:
        loc = reportes_service.ventas_agrupadas(inicio_mes, manana, "local")
        data["locales"] = {"labels": [r["etiqueta"] for r in loc], "values": [float(r["total"]) for r in loc]}
        gm = reportes_service.ganancia_mensual(6)
        data["ganancia"] = {"labels": [r["etiqueta"] for r in gm],
                            "ventas": [float(r["ventas"]) for r in gm],
                            "ganancia": [float(r["bruta"]) for r in gm]}
        st = reportes_service.stock_por_ubicacion()
        data["stock"] = {"labels": [r["etiqueta"] for r in st], "values": [int(r["unidades"]) for r in st]}
    return jsonify(data)


@bp.route("/inicio")
def inicio():
    return redirect(url_for("dashboard.index"))
