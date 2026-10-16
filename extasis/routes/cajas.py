from datetime import date

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import db
from ..models import catalogos, ubicaciones
from ..services import NegocioError, caja_service
from ..utils.audit import auditar
from ..utils.auth import es_admin, permiso_required, ubicacion_scope, verificar_acceso_ubicacion
from ..utils.helpers import clean, paginar, rango_fechas, to_decimal, to_int

bp = Blueprint("cajas", __name__, url_prefix="/cajas")


@bp.route("/")
@permiso_required("caja.operar")
def index():
    scope = ubicacion_scope()
    if scope:
        return redirect(url_for("cajas.local", ub_id=scope))
    locales = ubicaciones.locales()
    for l in locales:
        c = caja_service.caja_abierta(l["id"])
        l["caja"] = c
        l["resumen"] = caja_service.resumen(c["id"]) if c else None
    return render_template("cajas/admin.html", locales=locales)


@bp.route("/local/<int:ub_id>")
@permiso_required("caja.operar")
def local(ub_id):
    verificar_acceso_ubicacion(ub_id)
    ub = ubicaciones.get(ub_id) or abort(404)
    if ub["tipo"] != "LOCAL":
        abort(404)
    caja = caja_service.caja_abierta(ub_id)
    res = caja_service.resumen(caja["id"]) if caja else None
    ultima = db.query("""SELECT * FROM cajas WHERE ubicacion_id=%s AND estado='CERRADA'
                         ORDER BY fecha_cierre DESC LIMIT 1""", (ub_id,), one=True)
    return render_template("cajas/local.html", ub=ub, caja=caja, res=res, ultima=ultima,
                           metodos=catalogos.metodos_pago(), cats_gasto=catalogos.listar("categorias_gasto"),
                           ahora=date.today())


@bp.route("/abrir", methods=["POST"])
@permiso_required("caja.operar")
def abrir():
    ub_id = ubicacion_scope() or to_int(request.form.get("ubicacion_id"))
    verificar_acceso_ubicacion(ub_id)
    monto = to_decimal(request.form.get("monto_inicial"))
    try:
        cid = caja_service.abrir(ub_id, g.user["id"], monto, clean(request.form.get("observaciones"), 255))
        ub = ubicaciones.get(ub_id)
        auditar(f"{g.user['nombre']} abrió la caja de {ub['nombre']} con ${monto:,.2f}", "cajas", cid)
        flash("Caja abierta. ¡Buenas ventas!", "success")
        if request.form.get("ir_pos") == "1":
            return redirect(url_for("ventas.pos", ubicacion_id=ub_id))
    except NegocioError as e:
        flash(str(e), "danger")
    return redirect(url_for("cajas.local", ub_id=ub_id))


def _caja_abierta_o_error(caja_id):
    c = db.query("SELECT * FROM cajas WHERE id=%s", (caja_id,), one=True) or abort(404)
    verificar_acceso_ubicacion(c["ubicacion_id"])
    return c


@bp.route("/<int:caja_id>/movimiento", methods=["POST"])
@permiso_required("caja.operar")
def movimiento(caja_id):
    c = _caja_abierta_o_error(caja_id)
    tipo = request.form.get("tipo")
    monto = to_decimal(request.form.get("monto"))
    concepto = clean(request.form.get("concepto"), 200)
    metodo = to_int(request.form.get("metodo_pago_id")) or catalogos.id_metodo("EFECTIVO")
    try:
        if c["estado"] != "ABIERTA":
            raise NegocioError("La caja está cerrada.")
        if tipo not in ("INGRESO", "RETIRO", "GASTO"):
            raise NegocioError("Tipo de movimiento inválido.")
        if monto <= 0:
            raise NegocioError("El monto debe ser mayor a cero.")
        if not concepto:
            raise NegocioError("Indicá el concepto.")
        with db.transaction() as tx:
            caja_service.registrar(tx, caja_id, tipo, concepto, monto, metodo, g.user["id"])
            if tipo == "GASTO":
                cat = to_int(request.form.get("categoria_gasto_id"))
                if not cat:
                    raise NegocioError("Seleccioná la categoría del gasto.")
                tx.execute("""INSERT INTO gastos (categoria_gasto_id, descripcion, monto, ubicacion_id, fecha, metodo_pago_id,
                              usuario_id, caja_id) VALUES (%s,%s,%s,%s,CURDATE(),%s,%s,%s)""",
                           (cat, concepto, monto, c["ubicacion_id"], metodo, g.user["id"], caja_id))
            auditar(f"{g.user['nombre']} registró {tipo.lower()} de caja por ${monto:,.2f} ({concepto})", "cajas", caja_id, tx)
        flash("Movimiento registrado.", "success")
    except NegocioError as e:
        flash(str(e), "danger")
    return redirect(url_for("cajas.local", ub_id=c["ubicacion_id"]))


@bp.route("/<int:caja_id>/cierre", methods=["GET", "POST"])
@permiso_required("caja.operar")
def cierre(caja_id):
    c = _caja_abierta_o_error(caja_id)
    if c["estado"] != "ABIERTA":
        return redirect(url_for("cajas.detalle", caja_id=caja_id))
    res = caja_service.resumen(caja_id)
    if request.method == "POST":
        real = request.form.get("efectivo_real")
        if real in (None, ""):
            flash("Ingresá el efectivo real contado.", "danger")
        else:
            try:
                esperado, dif = caja_service.cerrar(caja_id, g.user["id"], to_decimal(real),
                                                    clean(request.form.get("observaciones"), 200))
                auditar(f"{g.user['nombre']} realizó el cierre de caja de {res['caja']['ubicacion']} "
                        f"(esperado ${esperado:,.2f}, diferencia ${dif:,.2f})", "cajas", caja_id)
                flash("Caja cerrada correctamente.", "success")
                return redirect(url_for("cajas.detalle", caja_id=caja_id))
            except NegocioError as e:
                flash(str(e), "danger")
    return render_template("cajas/cierre.html", res=res)


@bp.route("/<int:caja_id>")
@permiso_required("caja.operar", "caja.ver_todas")
def detalle(caja_id):
    _caja_abierta_o_error(caja_id)
    res = caja_service.resumen(caja_id)
    return render_template("cajas/detalle.html", res=res)


@bp.route("/historial")
@permiso_required("caja.operar", "caja.ver_todas")
def historial():
    args = request.args
    scope = ubicacion_scope()
    desde, hasta, hasta_ex = rango_fechas(args, 30)
    where, params = ["c.fecha_apertura>=%s", "c.fecha_apertura<%s"], [desde, hasta_ex]
    ub = scope or to_int(args.get("ubicacion_id"))
    if ub:
        where.append("c.ubicacion_id=%s")
        params.append(ub)
    w = " AND ".join(where)
    pag = paginar(db.scalar(f"SELECT COUNT(*) FROM cajas c WHERE {w}", params))
    rows = db.query(f"""SELECT c.*, ub.nombre AS ubicacion, ua.nombre AS usuario_apertura, uc.nombre AS usuario_cierre,
                               (SELECT COALESCE(SUM(monto),0) FROM movimientos_caja m WHERE m.caja_id=c.id AND m.tipo='VENTA') AS ventas
                        FROM cajas c JOIN ubicaciones ub ON ub.id=c.ubicacion_id JOIN usuarios ua ON ua.id=c.usuario_apertura_id
                        LEFT JOIN usuarios uc ON uc.id=c.usuario_cierre_id WHERE {w}
                        ORDER BY c.fecha_apertura DESC LIMIT %s OFFSET %s""", params + [pag.per_page, pag.offset])
    return render_template("cajas/historial.html", rows=rows, pag=pag, desde=desde, hasta=hasta,
                           ubics=ubicaciones.locales(False) if es_admin() else [])
