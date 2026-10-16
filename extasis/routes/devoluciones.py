from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import db
from ..services import NegocioError, caja_service, venta_service
from ..utils.auth import permiso_required, ubicacion_scope, verificar_acceso_ubicacion
from ..utils.helpers import clean, paginar, rango_fechas, to_int

bp = Blueprint("devoluciones", __name__, url_prefix="/devoluciones")


@bp.route("/")
@permiso_required("devoluciones.crear")
def index():
    args = request.args
    scope = ubicacion_scope()
    desde, hasta, hasta_ex = rango_fechas(args, 30)
    where, params = ["d.fecha>=%s", "d.fecha<%s"], [desde, hasta_ex]
    if scope:
        where.append("d.ubicacion_id=%s")
        params.append(scope)
    w = " AND ".join(where)
    pag = paginar(db.scalar(f"SELECT COUNT(*) FROM devoluciones d WHERE {w}", params))
    rows = db.query(f"""SELECT d.*, ub.nombre AS ubicacion, u.nombre AS usuario FROM devoluciones d
                        JOIN ubicaciones ub ON ub.id=d.ubicacion_id JOIN usuarios u ON u.id=d.usuario_id
                        WHERE {w} ORDER BY d.id DESC LIMIT %s OFFSET %s""", params + [pag.per_page, pag.offset])
    return render_template("devoluciones/index.html", rows=rows, pag=pag, desde=desde, hasta=hasta)


@bp.route("/nueva", methods=["GET", "POST"])
@permiso_required("devoluciones.crear")
def nueva():
    venta_id = to_int(request.values.get("venta_id"))
    v, det = (None, [])
    if venta_id:
        v, det = venta_service.get_venta(venta_id)
        if not v:
            flash("No existe una venta con ese número.", "warning")
        else:
            verificar_acceso_ubicacion(v["ubicacion_id"])
    if request.method == "POST" and v:
        import json
        items = {d["id"]: to_int(request.form.get(f"cant_{d['id']}"), 0) for d in det}
        try:
            nuevos = json.loads(request.form.get("nuevos") or "[]")
            nuevos = [(int(i["variante_id"]), int(i["cantidad"])) for i in nuevos]
        except (ValueError, KeyError, TypeError):
            nuevos = []
        try:
            dev_id, venta_nueva = venta_service.devolver(
                venta_id, items, clean(request.form.get("motivo"), 255), g.user, nuevos=nuevos,
                metodo_id=to_int(request.form.get("metodo_pago_id")), plan_id=to_int(request.form.get("plan_id")))
            if venta_nueva:
                flash(f"Cambio registrado (devolución N° {dev_id}, venta N° {venta_nueva}). Stock y caja actualizados.", "success")
                return redirect(url_for("ventas.detalle", venta_id=venta_nueva))
            flash(f"Devolución N° {dev_id} registrada. Stock y caja actualizados.", "success")
            return redirect(url_for("devoluciones.detalle", dev_id=dev_id))
        except NegocioError as e:
            flash(str(e), "danger")
            v, det = venta_service.get_venta(venta_id)
    caja = caja_service.caja_abierta(v["ubicacion_id"]) if v else None
    from ..models import catalogos, financiacion
    metodos = [m for m in catalogos.metodos_pago() if m["codigo"] != "CTACTE" or (v and v["cliente_id"])]
    factor = (v["total"] / v["subtotal"]) if v and v["subtotal"] else 1
    for d in det:
        d["valor_unit"] = round(float(d["precio_unitario"] * factor), 2)
    return render_template("devoluciones/nueva.html", v=v, det=det, caja=caja, metodos=metodos,
                           financiacion=financiacion.opciones_pos())


@bp.route("/<int:dev_id>")
@permiso_required("devoluciones.crear")
def detalle(dev_id):
    d = db.query("""SELECT d.*, ub.nombre AS ubicacion, u.nombre AS usuario, mp.nombre AS metodo FROM devoluciones d
                    JOIN ubicaciones ub ON ub.id=d.ubicacion_id JOIN usuarios u ON u.id=d.usuario_id
                    LEFT JOIN metodos_pago mp ON mp.id=d.metodo_pago_id
                    WHERE d.id=%s""", (dev_id,), one=True) or abort(404)
    verificar_acceso_ubicacion(d["ubicacion_id"])
    items = db.query("""SELECT dd.*, p.nombre AS producto, t.nombre AS talle, c.nombre AS color
                        FROM detalle_devoluciones dd JOIN detalle_ventas dv ON dv.id=dd.detalle_venta_id
                        JOIN variantes_producto vp ON vp.id=dv.variante_id JOIN productos p ON p.id=vp.producto_id
                        JOIN talles t ON t.id=vp.talle_id JOIN colores c ON c.id=vp.color_id
                        WHERE dd.devolucion_id=%s""", (dev_id,))
    return render_template("devoluciones/detalle.html", d=d, items=items)
