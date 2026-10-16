"""Solicitudes de mercadería de los locales al depósito."""
import json

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import db
from ..models import ubicaciones
from ..services import NegocioError, stock_service
from ..utils.audit import auditar
from ..utils.auth import es_admin, login_required, permiso_required, ubicacion_scope
from ..utils.helpers import clean, paginar, to_int

bp = Blueprint("solicitudes", __name__, url_prefix="/solicitudes")

ESTADOS = ["Pendiente", "Aprobada", "Preparando", "Enviada", "Recibida", "Rechazada"]


@bp.route("/")
@permiso_required("solicitudes.crear", "solicitudes.gestionar")
def index():
    scope = ubicacion_scope()
    where, params = ["1=1"], []
    if scope:
        where.append("s.ubicacion_id=%s")
        params.append(scope)
    est = request.args.get("estado")
    if est in ESTADOS:
        where.append("s.estado=%s")
        params.append(est)
    elif not request.args.get("todas"):
        where.append("s.estado NOT IN ('Recibida','Rechazada')")
    w = " AND ".join(where)
    pag = paginar(db.scalar(f"SELECT COUNT(*) FROM solicitudes_stock s WHERE {w}", params))
    rows = db.query(f"""SELECT s.*, ub.nombre AS ubicacion, u.nombre AS usuario,
                               (SELECT SUM(cantidad) FROM detalle_solicitudes d WHERE d.solicitud_id=s.id) AS unidades,
                               (SELECT COUNT(*) FROM detalle_solicitudes d WHERE d.solicitud_id=s.id) AS items
                        FROM solicitudes_stock s JOIN ubicaciones ub ON ub.id=s.ubicacion_id
                        JOIN usuarios u ON u.id=s.usuario_id WHERE {w}
                        ORDER BY FIELD(s.estado,'Pendiente','Aprobada','Preparando','Enviada','Recibida','Rechazada'), s.id DESC
                        LIMIT %s OFFSET %s""", params + [pag.per_page, pag.offset])
    return render_template("solicitudes/index.html", rows=rows, pag=pag, estados=ESTADOS)


@bp.route("/nueva", methods=["GET", "POST"])
@permiso_required("solicitudes.crear")
def nueva():
    scope = ubicacion_scope()
    if request.method == "POST":
        ub = scope or to_int(request.form.get("ubicacion_id"))
        obs = clean(request.form.get("observaciones"), 255)
        try:
            items = json.loads(request.form.get("items") or "[]")
            items = [(int(i["variante_id"]), int(i["cantidad"])) for i in items if int(i["cantidad"]) > 0]
        except (ValueError, KeyError, TypeError):
            items = []
        if not ub:
            flash("Seleccioná el local que solicita.", "danger")
        elif not items:
            flash("Agregá al menos un producto a la solicitud.", "danger")
        else:
            with db.transaction() as tx:
                sid = tx.execute("INSERT INTO solicitudes_stock (ubicacion_id, usuario_id, observaciones) VALUES (%s,%s,%s)",
                                 (ub, g.user["id"], obs))
                for vid, cant in items:
                    tx.execute("INSERT INTO detalle_solicitudes (solicitud_id, variante_id, cantidad) VALUES (%s,%s,%s)",
                               (sid, vid, cant))
                auditar(f"{g.user['nombre']} solicitó mercadería al depósito (solicitud N° {sid})", "solicitudes", sid, tx)
            flash(f"Solicitud N° {sid} enviada al depósito.", "success")
            return redirect(url_for("solicitudes.detalle", sid=sid))
    return render_template("solicitudes/nueva.html", locales=ubicaciones.locales())


def _get(sid):
    s = db.query("""SELECT s.*, ub.nombre AS ubicacion, u.nombre AS usuario, ua.nombre AS actualizado_por_nombre
                    FROM solicitudes_stock s JOIN ubicaciones ub ON ub.id=s.ubicacion_id
                    JOIN usuarios u ON u.id=s.usuario_id LEFT JOIN usuarios ua ON ua.id=s.actualizado_por
                    WHERE s.id=%s""", (sid,), one=True)
    if not s:
        abort(404)
    scope = ubicacion_scope()
    if scope and scope != s["ubicacion_id"]:
        abort(403)
    return s


@bp.route("/<int:sid>")
@permiso_required("solicitudes.crear", "solicitudes.gestionar")
def detalle(sid):
    s = _get(sid)
    dep = ubicaciones.deposito_central()
    det = db.query("""SELECT d.*, p.nombre AS producto, t.nombre AS talle, c.nombre AS color, v.codigo_barras,
                             COALESCE((SELECT cantidad FROM stock st WHERE st.variante_id=d.variante_id AND st.ubicacion_id=%s),0) AS stock_deposito,
                             COALESCE((SELECT cantidad FROM stock st WHERE st.variante_id=d.variante_id AND st.ubicacion_id=%s),0) AS stock_local
                      FROM detalle_solicitudes d JOIN variantes_producto v ON v.id=d.variante_id
                      JOIN productos p ON p.id=v.producto_id JOIN talles t ON t.id=v.talle_id
                      JOIN colores c ON c.id=v.color_id WHERE d.solicitud_id=%s""",
                   (dep["id"] if dep else 0, s["ubicacion_id"], sid))
    transf = db.query("SELECT * FROM transferencias WHERE solicitud_id=%s ORDER BY id", (sid,))
    return render_template("solicitudes/detalle.html", s=s, det=det, transf=transf, deposito=dep,
                           depositos=ubicaciones.depositos())


@bp.route("/<int:sid>/estado", methods=["POST"])
@login_required
def cambiar_estado(sid):
    s = _get(sid)
    nuevo = request.form.get("estado")
    respuesta = clean(request.form.get("respuesta"), 255)
    transiciones = {
        "Pendiente": ["Aprobada", "Rechazada"],
        "Aprobada": ["Preparando", "Enviada", "Rechazada"],
        "Preparando": ["Enviada", "Rechazada"],
        "Enviada": ["Recibida"],
    }
    if nuevo not in transiciones.get(s["estado"], []):
        flash("Cambio de estado no permitido.", "danger")
        return redirect(url_for("solicitudes.detalle", sid=sid))
    # Sólo el dueño aprueba/prepara/envía/rechaza. El local (o el dueño) confirma la recepción.
    if nuevo != "Recibida" and not es_admin():
        abort(403)
    try:
        with db.transaction() as tx:
            if nuevo == "Enviada":
                origen = to_int(request.form.get("origen_id")) or ubicaciones.deposito_central()["id"]
                det = tx.query("SELECT id, variante_id, cantidad FROM detalle_solicitudes WHERE solicitud_id=%s", (sid,))
                items = []
                for d in det:
                    cant = to_int(request.form.get(f"enviar_{d['id']}"), d["cantidad"])
                    if cant and cant > 0:
                        items.append((d["variante_id"], cant))
                tid = stock_service.transferir(tx, origen, s["ubicacion_id"], items, g.user["id"],
                                               f"Solicitud N° {sid}", solicitud_id=sid, en_transito=True)
                auditar(f"{g.user['nombre']} envió la solicitud N° {sid} (transferencia N° {tid})", "solicitudes", sid, tx)
            elif nuevo == "Recibida":
                pend = tx.query("SELECT id FROM transferencias WHERE solicitud_id=%s AND estado='En tránsito'", (sid,))
                for t in pend:
                    stock_service.recibir(tx, t["id"], g.user["id"])
                auditar(f"{g.user['nombre']} recibió la mercadería de la solicitud N° {sid}", "solicitudes", sid, tx)
            else:
                auditar(f"{g.user['nombre']} cambió la solicitud N° {sid} a {nuevo}", "solicitudes", sid, tx)
            tx.execute("""UPDATE solicitudes_stock SET estado=%s, respuesta=COALESCE(%s, respuesta),
                          actualizado_por=%s, actualizado_en=NOW() WHERE id=%s""",
                       (nuevo, respuesta, g.user["id"], sid))
        flash(f"Solicitud marcada como {nuevo}.", "success")
    except NegocioError as e:
        flash(str(e), "danger")
    return redirect(url_for("solicitudes.detalle", sid=sid))
