"""ABM genérico de tablas maestras: categorías, marcas, temporadas, talles, colores, etc."""
import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import db
from ..models.catalogos import CATALOGOS, categorias_principales, listar
from ..utils.audit import auditar
from ..utils.auth import admin_required
from ..utils.helpers import clean, to_int

bp = Blueprint("catalogos", __name__, url_prefix="/catalogos")


def _valores(tabla, form):
    nombre = clean(form.get("nombre"), 80)
    if not nombre:
        raise ValueError("El nombre es obligatorio.")
    vals = {"nombre": nombre}
    if tabla == "categorias":
        vals["parent_id"] = to_int(form.get("parent_id"))
    elif tabla == "talles":
        vals["orden"] = to_int(form.get("orden"), 0)
    elif tabla == "colores":
        hexv = (form.get("hex") or "").strip()
        vals["hex"] = hexv if re.fullmatch(r"#[0-9a-fA-F]{6}", hexv) else None
    elif tabla == "categorias_gasto":
        vals["tipo"] = "DIARIO" if form.get("tipo") == "DIARIO" else "SERVICIO"
    return vals


@bp.route("/<tabla>", methods=["GET", "POST"])
@admin_required
def index(tabla):
    if tabla not in CATALOGOS:
        abort(404)
    meta = CATALOGOS[tabla]
    if request.method == "POST":
        try:
            vals = _valores(tabla, request.form)
            if tabla == "metodos_pago":
                raise ValueError("Los métodos de pago son fijos; sólo se pueden renombrar o desactivar.")
            cols = ", ".join(vals.keys())
            ph = ", ".join(["%s"] * len(vals))
            new_id = db.execute(f"INSERT INTO {tabla} ({cols}) VALUES ({ph})", list(vals.values()))
            auditar(f"{g.user['nombre']} creó '{vals['nombre']}' en {meta['titulo']}", "catalogos", new_id)
            flash("Registro creado.", "success")
        except ValueError as e:
            flash(str(e), "danger")
        except db.IntegrityError:
            flash("Ya existe un registro con ese nombre.", "danger")
        return redirect(_volver() or url_for("catalogos.index", tabla=tabla))
    rows = listar(tabla, solo_activos=False)
    padres = {c["id"]: c["nombre"] for c in categorias_principales(False)} if tabla == "categorias" else {}
    return render_template("configuracion/catalogo.html", tabla=tabla, meta=meta, rows=rows, padres=padres,
                           catalogos=CATALOGOS)


@bp.route("/<tabla>/<int:item_id>", methods=["POST"])
@admin_required
def editar(tabla, item_id):
    if tabla not in CATALOGOS:
        abort(404)
    accion = request.form.get("accion")
    try:
        if accion == "estado":
            db.execute(f"UPDATE {tabla} SET activo=1-activo WHERE id=%s", (item_id,))
            flash("Estado actualizado.", "success")
        elif accion == "eliminar":
            if tabla == "metodos_pago":
                raise ValueError("Los métodos de pago no se pueden eliminar, sólo desactivar.")
            try:
                db.execute(f"DELETE FROM {tabla} WHERE id=%s", (item_id,))
                flash("Eliminado.", "success")
            except db.IntegrityError:
                db.execute(f"UPDATE {tabla} SET activo=0 WHERE id=%s", (item_id,))
                flash("Está en uso en registros anteriores: se desactivó en lugar de eliminarse.", "warning")
        else:
            vals = _valores(tabla, request.form)
            if tabla == "categorias" and vals.get("parent_id") == item_id:
                raise ValueError("Una categoría no puede ser subcategoría de sí misma.")
            sets = ", ".join(f"{k}=%s" for k in vals)
            db.execute(f"UPDATE {tabla} SET {sets} WHERE id=%s", list(vals.values()) + [item_id])
            auditar(f"{g.user['nombre']} editó '{vals['nombre']}' en {CATALOGOS[tabla]['titulo']}", "catalogos", item_id)
            flash("Registro actualizado.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    except db.IntegrityError:
        flash("Ya existe un registro con ese nombre.", "danger")
    return redirect(_volver() or url_for("catalogos.index", tabla=tabla))


def _volver():
    v = request.form.get("volver") or ""
    return v if v.startswith("/") and not v.startswith("//") else None
