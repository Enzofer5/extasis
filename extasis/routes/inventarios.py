"""Inventarios físicos: conteo -> diferencia -> autorización del administrador -> ajuste."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import db
from ..models import catalogos, ubicaciones
from ..services import NegocioError, stock_service
from ..utils.audit import auditar
from ..utils.auth import admin_required, permiso_required, ubicacion_scope, verificar_acceso_ubicacion
from ..utils.helpers import clean, paginar, to_int

bp = Blueprint("inventarios", __name__, url_prefix="/inventarios")


@bp.route("/")
@permiso_required("inventarios.crear", "inventarios.aprobar")
def index():
    scope = ubicacion_scope()
    where, params = ["1=1"], []
    if scope:
        where.append("i.ubicacion_id=%s")
        params.append(scope)
    w = " AND ".join(where)
    pag = paginar(db.scalar(f"SELECT COUNT(*) FROM inventarios i WHERE {w}", params))
    rows = db.query(f"""SELECT i.*, ub.nombre AS ubicacion, u.nombre AS usuario, ua.nombre AS aprobador,
                               (SELECT COUNT(*) FROM detalle_inventarios d WHERE d.inventario_id=i.id) AS items,
                               (SELECT COALESCE(SUM(d.stock_real-d.stock_sistema),0) FROM detalle_inventarios d WHERE d.inventario_id=i.id) AS diferencia
                        FROM inventarios i JOIN ubicaciones ub ON ub.id=i.ubicacion_id JOIN usuarios u ON u.id=i.usuario_id
                        LEFT JOIN usuarios ua ON ua.id=i.aprobado_por WHERE {w}
                        ORDER BY i.id DESC LIMIT %s OFFSET %s""", params + [pag.per_page, pag.offset])
    return render_template("inventarios/index.html", rows=rows, pag=pag)


@bp.route("/nuevo", methods=["GET", "POST"])
@permiso_required("inventarios.crear")
def nuevo():
    scope = ubicacion_scope()
    ub_id = scope or to_int(request.values.get("ubicacion_id"))
    cat = to_int(request.values.get("categoria_id"))
    q = clean(request.values.get("q"))
    items = []
    if ub_id:
        verificar_acceso_ubicacion(ub_id)
        where, params = ["p.activo=1", "v.activo=1"], [ub_id]
        if cat:
            where.append("p.categoria_id=%s")
            params.append(cat)
        if q:
            where.append("(p.nombre LIKE %s OR v.codigo_barras=%s)")
            params += [f"%{q}%", q]
        if not cat and not q:
            where.append("EXISTS (SELECT 1 FROM stock s2 WHERE s2.variante_id=v.id AND s2.ubicacion_id=%s AND s2.cantidad<>0)")
            params.append(ub_id)
        items = db.query(f"""SELECT v.id AS variante_id, v.codigo_barras, p.nombre AS producto, t.nombre AS talle,
                                    c.nombre AS color, COALESCE(s.cantidad,0) AS sistema
                             FROM variantes_producto v JOIN productos p ON p.id=v.producto_id
                             JOIN talles t ON t.id=v.talle_id JOIN colores c ON c.id=v.color_id
                             LEFT JOIN stock s ON s.variante_id=v.id AND s.ubicacion_id=%s
                             WHERE {' AND '.join(where)} ORDER BY p.nombre, c.nombre, t.orden LIMIT 500""", params)
    if request.method == "POST" and request.form.get("guardar") == "1":
        motivo = clean(request.form.get("motivo"), 255)
        contados = []
        for it in items:
            real = request.form.get(f"real_{it['variante_id']}")
            if real not in (None, ""):
                contados.append((it["variante_id"], it["sistema"], max(0, to_int(real, 0))))
        if not motivo:
            flash("Indicá el motivo del inventario.", "danger")
        elif not contados:
            flash("No cargaste ninguna cantidad real.", "danger")
        else:
            with db.transaction() as tx:
                iid = tx.execute("INSERT INTO inventarios (ubicacion_id, usuario_id, motivo) VALUES (%s,%s,%s)",
                                 (ub_id, g.user["id"], motivo))
                for vid, sistema, real in contados:
                    tx.execute("""INSERT INTO detalle_inventarios (inventario_id, variante_id, stock_sistema, stock_real)
                                  VALUES (%s,%s,%s,%s)""", (iid, vid, sistema, real))
                auditar(f"{g.user['nombre']} cargó el inventario N° {iid} ({len(contados)} artículos)",
                        "inventarios", iid, tx)
            flash("Inventario guardado. Queda pendiente de autorización del administrador.", "success")
            return redirect(url_for("inventarios.detalle", iid=iid))
    return render_template("inventarios/nuevo.html", ub_id=ub_id, items=items, cat=cat, q=q,
                           ubics=ubicaciones.listar() if not scope else [],
                           categorias=catalogos.categorias_principales())


@bp.route("/<int:iid>")
@permiso_required("inventarios.crear", "inventarios.aprobar")
def detalle(iid):
    i = db.query("""SELECT i.*, ub.nombre AS ubicacion, u.nombre AS usuario, ua.nombre AS aprobador
                    FROM inventarios i JOIN ubicaciones ub ON ub.id=i.ubicacion_id JOIN usuarios u ON u.id=i.usuario_id
                    LEFT JOIN usuarios ua ON ua.id=i.aprobado_por WHERE i.id=%s""", (iid,), one=True) or abort(404)
    verificar_acceso_ubicacion(i["ubicacion_id"])
    det = db.query("""SELECT d.*, d.stock_real-d.stock_sistema AS diferencia, p.nombre AS producto, t.nombre AS talle,
                             c.nombre AS color, COALESCE(s.cantidad,0) AS actual
                      FROM detalle_inventarios d JOIN variantes_producto v ON v.id=d.variante_id
                      JOIN productos p ON p.id=v.producto_id JOIN talles t ON t.id=v.talle_id JOIN colores c ON c.id=v.color_id
                      LEFT JOIN stock s ON s.variante_id=d.variante_id AND s.ubicacion_id=%s
                      WHERE d.inventario_id=%s ORDER BY (d.stock_real-d.stock_sistema)=0, p.nombre""",
                   (i["ubicacion_id"], iid))
    return render_template("inventarios/detalle.html", i=i, det=det)


@bp.route("/<int:iid>/resolver", methods=["POST"])
@admin_required
def resolver(iid):
    accion = request.form.get("accion")
    try:
        with db.transaction() as tx:
            i = tx.query("SELECT * FROM inventarios WHERE id=%s FOR UPDATE", (iid,), one=True)
            if not i or i["estado"] != "Pendiente":
                raise NegocioError("El inventario ya fue resuelto.")
            if accion == "aprobar":
                det = tx.query("SELECT * FROM detalle_inventarios WHERE inventario_id=%s", (iid,))
                ajustes = 0
                for d in det:
                    diff = stock_service.establecer(tx, d["variante_id"], i["ubicacion_id"], d["stock_real"])
                    if diff:
                        ajustes += 1
                        stock_service.registrar_movimiento(
                            tx, "AJUSTE", d["variante_id"], diff, g.user["id"],
                            origen_id=i["ubicacion_id"] if diff < 0 else None,
                            destino_id=i["ubicacion_id"] if diff > 0 else None,
                            motivo=f"Inventario N° {iid}: {i['motivo']}", ref_tipo="inventario", ref_id=iid)
                estado = "Aprobado"
                auditar(f"{g.user['nombre']} aprobó el inventario N° {iid} ({ajustes} ajustes)", "inventarios", iid, tx)
            else:
                estado = "Rechazado"
                auditar(f"{g.user['nombre']} rechazó el inventario N° {iid}", "inventarios", iid, tx)
            tx.execute("UPDATE inventarios SET estado=%s, aprobado_por=%s, fecha_aprobacion=NOW() WHERE id=%s",
                       (estado, g.user["id"], iid))
        flash(f"Inventario {estado.lower()}.", "success")
    except NegocioError as e:
        flash(str(e), "danger")
    return redirect(url_for("inventarios.detalle", iid=iid))
