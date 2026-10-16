from flask import Blueprint, render_template, request

from .. import db
from ..utils.auth import permiso_required
from ..utils.helpers import clean, paginar, rango_fechas, to_int

bp = Blueprint("auditoria", __name__, url_prefix="/auditoria")


@bp.route("/")
@permiso_required("auditoria.ver")
def index():
    args = request.args
    desde, hasta, hasta_ex = rango_fechas(args, 7)
    where, params = ["a.fecha>=%s", "a.fecha<%s"], [desde, hasta_ex]
    mod = clean(args.get("modulo"), 40)
    if mod:
        where.append("a.modulo=%s")
        params.append(mod)
    uid = to_int(args.get("usuario_id"))
    if uid:
        where.append("a.usuario_id=%s")
        params.append(uid)
    q = clean(args.get("q"))
    if q:
        where.append("a.accion LIKE %s")
        params.append(f"%{q}%")
    w = " AND ".join(where)
    pag = paginar(db.scalar(f"SELECT COUNT(*) FROM auditoria a WHERE {w}", params))
    rows = db.query(f"""SELECT a.*, u.nombre AS usuario FROM auditoria a LEFT JOIN usuarios u ON u.id=a.usuario_id
                        WHERE {w} ORDER BY a.id DESC LIMIT %s OFFSET %s""", params + [pag.per_page, pag.offset])
    modulos = [r["modulo"] for r in db.query("SELECT DISTINCT modulo FROM auditoria ORDER BY modulo")]
    usuarios = db.query("SELECT id, nombre FROM usuarios ORDER BY nombre")
    return render_template("auditoria/index.html", rows=rows, pag=pag, desde=desde, hasta=hasta,
                           modulos=modulos, usuarios=usuarios)
