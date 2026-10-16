import json

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import db
from ..models import ubicaciones
from ..services import NegocioError, stock_service
from ..utils.audit import auditar
from ..utils.auth import admin_required, login_required, ubicacion_scope
from ..utils.helpers import clean, hay_filtros, paginar, rango_fechas, to_int

bp = Blueprint("transferencias", __name__, url_prefix="/transferencias")


@bp.route("/")
@login_required
def index():
    args = request.args
    scope = ubicacion_scope()
    desde, hasta, hasta_ex = rango_fechas(args, 30)
    where, params = ["t.fecha>=%s", "t.fecha<%s"], [desde, hasta_ex]
    if scope:
        where.append("(t.origen_id=%s OR t.destino_id=%s)")
        params += [scope, scope]
    else:
        for campo in ("origen_id", "destino_id"):
            val = to_int(args.get(campo))
            if val:
                where.append(f"t.{campo}=%s")
                params.append(val)
    w = " AND ".join(where)
    pag = paginar(db.scalar(f"SELECT COUNT(*) FROM transferencias t WHERE {w}", params))
    rows = db.query(f"""SELECT t.*, uo.nombre AS origen, ud.nombre AS destino, u.nombre AS usuario,
                               (SELECT SUM(cantidad) FROM detalle_transferencias d WHERE d.transferencia_id=t.id) AS unidades
                        FROM transferencias t JOIN ubicaciones uo ON uo.id=t.origen_id
                        JOIN ubicaciones ud ON ud.id=t.destino_id JOIN usuarios u ON u.id=t.usuario_id
                        WHERE {w} ORDER BY t.id DESC LIMIT %s OFFSET %s""", params + [pag.per_page, pag.offset])
    return render_template("transferencias/index.html", rows=rows, pag=pag, desde=desde, hasta=hasta,
                           ubics=ubicaciones.listar(), buscado=hay_filtros(args))


@bp.route("/nueva", methods=["GET", "POST"])
@admin_required
def nueva():
    if request.method == "POST":
        origen = to_int(request.form.get("origen_id"))
        destino = to_int(request.form.get("destino_id"))
        obs = clean(request.form.get("observaciones"), 255)
        try:
            items = json.loads(request.form.get("items") or "[]")
            items = [(int(i["variante_id"]), int(i["cantidad"])) for i in items]
        except (ValueError, KeyError, TypeError):
            items = []
        try:
            if not origen or not destino:
                raise NegocioError("Seleccioná origen y destino.")
            with db.transaction() as tx:
                tid = stock_service.transferir(tx, origen, destino, items, g.user["id"], obs)
                uo = tx.query("SELECT nombre FROM ubicaciones WHERE id=%s", (origen,), one=True)["nombre"]
                ud = tx.query("SELECT nombre FROM ubicaciones WHERE id=%s", (destino,), one=True)["nombre"]
                unidades = sum(c for _, c in items)
                auditar(f"{g.user['nombre']} transfirió {unidades} unidades de {uo} a {ud}", "transferencias", tid, tx)
            flash(f"Transferencia N° {tid} realizada.", "success")
            return redirect(url_for("transferencias.detalle", tid=tid))
        except NegocioError as e:
            flash(str(e), "danger")
    dep = ubicaciones.deposito_central()
    return render_template("transferencias/nueva.html", ubics=ubicaciones.listar(),
                           origen_default=dep["id"] if dep else None)


@bp.route("/<int:tid>")
@login_required
def detalle(tid):
    t = db.query("""SELECT t.*, uo.nombre AS origen, ud.nombre AS destino, u.nombre AS usuario
                    FROM transferencias t JOIN ubicaciones uo ON uo.id=t.origen_id
                    JOIN ubicaciones ud ON ud.id=t.destino_id JOIN usuarios u ON u.id=t.usuario_id
                    WHERE t.id=%s""", (tid,), one=True) or abort(404)
    scope = ubicacion_scope()
    if scope and scope not in (t["origen_id"], t["destino_id"]):
        abort(403)
    det = db.query("""SELECT d.cantidad, p.nombre AS producto, t.nombre AS talle, c.nombre AS color, v.codigo_barras
                      FROM detalle_transferencias d JOIN variantes_producto v ON v.id=d.variante_id
                      JOIN productos p ON p.id=v.producto_id JOIN talles t ON t.id=v.talle_id
                      JOIN colores c ON c.id=v.color_id WHERE d.transferencia_id=%s""", (tid,))
    return render_template("transferencias/detalle.html", t=t, det=det)


@bp.route("/<int:tid>/recibir", methods=["POST"])
@login_required
def recibir(tid):
    t = db.query("SELECT * FROM transferencias WHERE id=%s", (tid,), one=True) or abort(404)
    scope = ubicacion_scope()
    if scope and scope != t["destino_id"]:
        abort(403)
    try:
        with db.transaction() as tx:
            stock_service.recibir(tx, tid, g.user["id"])
            if t["solicitud_id"]:
                tx.execute("""UPDATE solicitudes_stock SET estado='Recibida', actualizado_por=%s, actualizado_en=NOW()
                              WHERE id=%s""", (g.user["id"], t["solicitud_id"]))
            auditar(f"{g.user['nombre']} recibió la transferencia N° {tid}", "transferencias", tid, tx)
        flash("Mercadería recibida y sumada al stock.", "success")
    except NegocioError as e:
        flash(str(e), "danger")
    return redirect(request.referrer or url_for("transferencias.detalle", tid=tid))
