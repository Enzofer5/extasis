from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from .. import db
from ..models import catalogos, configuracion, ubicaciones
from ..services import NegocioError, caja_service, venta_service
from ..utils.auth import admin_required, es_admin, permiso_required, ubicacion_scope, verificar_acceso_ubicacion
from ..utils.helpers import clean, hay_filtros, paginar, rango_fechas, to_int

bp = Blueprint("ventas", __name__)

ESTADOS = ["Completada", "Anulada", "Devuelta"]


def _ubicacion_pos():
    scope = ubicacion_scope()
    if scope:
        return scope
    ub = to_int(request.args.get("ubicacion_id") or request.cookies.get("pos_ubicacion"))
    if ub:
        return ub
    loc = ubicaciones.locales()
    return loc[0]["id"] if loc else None


@bp.route("/pos")
@permiso_required("ventas.crear")
def pos():
    ub_id = _ubicacion_pos()
    if not ub_id:
        flash("No hay locales activos.", "danger")
        return redirect(url_for("dashboard.index"))
    ub = ubicaciones.get(ub_id)
    if not ub or ub["tipo"] != "LOCAL":
        abort(404)
    # Cuenta corriente queda fuera del menú simple (requiere elegir cliente)
    metodos = [m for m in catalogos.metodos_pago() if m["codigo"] != "CTACTE"]
    caja = caja_service.caja_abierta(ub_id)
    from ..models import financiacion
    resp = render_template("ventas/pos.html", ub=ub, caja=caja, metodos=metodos,
                           financiacion=financiacion.opciones_pos(),
                           locales=ubicaciones.locales() if es_admin() else [],
                           sin_stock=configuracion.get_bool("permitir_venta_sin_stock"))
    from flask import make_response
    r = make_response(resp)
    if es_admin():
        r.set_cookie("pos_ubicacion", str(ub_id), samesite="Lax", httponly=True)
    return r


@bp.route("/api/ventas", methods=["POST"])
@permiso_required("ventas.crear")
def api_crear():
    data = request.get_json(silent=True) or {}
    ub = ubicacion_scope() or to_int(data.get("ubicacion_id"))
    if not ub:
        return jsonify(ok=False, error="Local no definido."), 400
    try:
        vid = venta_service.crear_venta(data, g.user, ub, es_admin=es_admin())
        return jsonify(ok=True, venta_id=vid, ticket_url=url_for("ventas.ticket", venta_id=vid))
    except NegocioError as e:
        return jsonify(ok=False, error=str(e)), 400


@bp.route("/ventas")
@permiso_required("ventas.ver")
def index():
    args = request.args
    scope = ubicacion_scope()
    rows, pag, totales = [], None, None
    desde, hasta, hasta_ex = rango_fechas(args, 1)
    buscado = hay_filtros(args)
    if buscado:
        where, params = ["v.fecha>=%s", "v.fecha<%s"], [desde, hasta_ex]
        ub = scope or to_int(args.get("ubicacion_id"))
        if ub:
            where.append("v.ubicacion_id=%s")
            params.append(ub)
        num = to_int(args.get("numero"))
        if num:
            where = ["v.id=%s"] + (["v.ubicacion_id=%s"] if scope else [])
            params = [num] + ([scope] if scope else [])
        if args.get("estado") in ESTADOS:
            where.append("v.estado=%s")
            params.append(args["estado"])
        for campo in ("usuario_id", "metodo_pago_id"):
            val = to_int(args.get(campo))
            if val:
                where.append(f"v.{campo}=%s")
                params.append(val)
        q = clean(args.get("cliente"))
        if q:
            where.append("(c.apellido LIKE %s OR c.nombre LIKE %s OR c.dni=%s)")
            params += [f"%{q}%", f"%{q}%", q]
        prod = clean(args.get("producto"))
        if prod:
            where.append("""EXISTS (SELECT 1 FROM detalle_ventas dv JOIN variantes_producto vp ON vp.id=dv.variante_id
                            JOIN productos p ON p.id=vp.producto_id WHERE dv.venta_id=v.id
                            AND (p.nombre LIKE %s OR vp.codigo_barras=%s))""")
            params += [f"%{prod}%", prod]
        w = " AND ".join(where)
        base = f"""FROM ventas v JOIN ubicaciones ub ON ub.id=v.ubicacion_id JOIN usuarios u ON u.id=v.usuario_id
                   JOIN metodos_pago mp ON mp.id=v.metodo_pago_id LEFT JOIN clientes c ON c.id=v.cliente_id WHERE {w}"""
        totales = db.query(f"""SELECT COUNT(*) AS n, COALESCE(SUM(IF(v.estado='Completada', v.total, 0)),0) AS total
                               {base}""", params, one=True)
        pag = paginar(totales["n"])
        rows = db.query(f"""SELECT v.*, ub.nombre AS ubicacion, u.nombre AS vendedor, mp.nombre AS metodo,
                                   CONCAT(c.apellido, ', ', c.nombre) AS cliente
                            {base} ORDER BY v.id DESC LIMIT %s OFFSET %s""", params + [pag.per_page, pag.offset])
    usuarios = db.query("SELECT id, nombre FROM usuarios ORDER BY nombre") if es_admin() else []
    return render_template("ventas/index.html", rows=rows, pag=pag, buscado=buscado, totales=totales,
                           desde=desde, hasta=hasta, estados=ESTADOS, metodos=catalogos.metodos_pago(),
                           ubics=ubicaciones.locales(False) if es_admin() else [], usuarios=usuarios)


def _venta_o_404(venta_id):
    v, det = venta_service.get_venta(venta_id)
    if not v:
        abort(404)
    verificar_acceso_ubicacion(v["ubicacion_id"])
    return v, det


@bp.route("/ventas/<int:venta_id>")
@permiso_required("ventas.ver")
def detalle(venta_id):
    v, det = _venta_o_404(venta_id)
    devs = db.query("""SELECT d.*, u.nombre AS usuario FROM devoluciones d JOIN usuarios u ON u.id=d.usuario_id
                       WHERE d.venta_id=%s ORDER BY d.id""", (venta_id,))
    return render_template("ventas/detalle.html", v=v, det=det, devs=devs)


@bp.route("/ventas/<int:venta_id>/ticket")
@permiso_required("ventas.ver")
def ticket(venta_id):
    v, det = _venta_o_404(venta_id)
    return render_template("ventas/ticket.html", v=v, det=det,
                           negocio=configuracion.get("nombre_negocio", "ÉXTASIS"),
                           pie=configuracion.get("ticket_pie", "¡Gracias por su compra!"),
                           auto=request.args.get("auto") == "1")


@bp.route("/ventas/<int:venta_id>/anular", methods=["POST"])
@admin_required
def anular(venta_id):
    try:
        venta_service.anular(venta_id, g.user, clean(request.form.get("motivo"), 200))
        flash(f"Venta N° {venta_id} anulada. Stock y caja revertidos.", "success")
    except NegocioError as e:
        flash(str(e), "danger")
    return redirect(url_for("ventas.detalle", venta_id=venta_id))
