"""ABM de locales y depósitos (tabla ubicaciones)."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import db
from ..utils.audit import auditar
from ..utils.auth import admin_required
from ..utils.helpers import clean

bp = Blueprint("locales", __name__, url_prefix="/locales")

CAMPOS = ["nombre", "direccion", "telefono", "responsable", "horarios", "observaciones"]


@bp.route("/")
@admin_required
def index():
    rows = db.query("""SELECT ub.*,
                              (SELECT COALESCE(SUM(cantidad),0) FROM stock s WHERE s.ubicacion_id=ub.id AND s.cantidad>0) AS unidades,
                              (SELECT COUNT(*) FROM usuarios u WHERE u.ubicacion_id=ub.id AND u.activo=1) AS usuarios,
                              (SELECT estado FROM cajas c WHERE c.ubicacion_id=ub.id AND c.estado='ABIERTA' LIMIT 1) AS caja
                       FROM ubicaciones ub ORDER BY ub.tipo, ub.id""")
    return render_template("configuracion/locales.html", rows=rows)


@bp.route("/nuevo", methods=["GET", "POST"])
@bp.route("/<int:lid>/editar", methods=["GET", "POST"])
@admin_required
def form(lid=None):
    l = db.query("SELECT * FROM ubicaciones WHERE id=%s", (lid,), one=True) if lid else None
    if lid and not l:
        abort(404)
    if request.method == "POST":
        d = {k: clean(request.form.get(k), 2000 if k == "observaciones" else 200) for k in CAMPOS}
        d["activo"] = 1 if request.form.get("activo", "1") == "1" else 0
        tipo = request.form.get("tipo") if request.form.get("tipo") in ("LOCAL", "DEPOSITO") else "LOCAL"
        if not d["nombre"]:
            flash("El nombre es obligatorio.", "danger")
        elif l and not d["activo"] and db.scalar("SELECT COUNT(*) FROM cajas WHERE ubicacion_id=%s AND estado='ABIERTA'", (lid,)):
            flash("No se puede desactivar un local con la caja abierta.", "danger")
        else:
            try:
                if l:
                    sets = ", ".join(f"{k}=%s" for k in d)
                    db.execute(f"UPDATE ubicaciones SET {sets} WHERE id=%s", list(d.values()) + [lid])
                    auditar(f"{g.user['nombre']} editó {d['nombre']}", "locales", lid)
                else:
                    d["tipo"] = tipo
                    cols = ", ".join(d)
                    lid = db.execute(f"INSERT INTO ubicaciones ({cols}) VALUES ({', '.join(['%s'] * len(d))})", list(d.values()))
                    auditar(f"{g.user['nombre']} creó {d['nombre']} ({tipo})", "locales", lid)
                flash("Guardado.", "success")
                return redirect(url_for("locales.index"))
            except db.IntegrityError:
                flash("Ya existe una ubicación con ese nombre.", "danger")
    return render_template("configuracion/local_form.html", l=l)
