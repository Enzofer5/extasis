from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from ..models import configuracion
from ..models.catalogos import CATALOGOS
from ..utils.audit import auditar
from ..utils.auth import admin_required

bp = Blueprint("configuracion", __name__, url_prefix="/configuracion")


@bp.route("/", methods=["GET", "POST"])
@admin_required
def index():
    if request.method == "POST":
        for item in configuracion.todas():
            clave = item["clave"]
            if clave in ("permitir_venta_sin_stock",):
                valor = "1" if request.form.get(clave) == "1" else "0"
            else:
                valor = (request.form.get(clave) or "").strip()[:255]
                if clave.startswith(("dias_", "stock_minimo")):
                    valor = valor if valor.isdigit() else item["valor"]
                if not valor:
                    valor = item["valor"]
            if valor != item["valor"]:
                configuracion.set_valor(clave, valor)
                auditar(f"{g.user['nombre']} cambió la configuración '{clave}' a '{valor}'", "configuracion", clave)
        flash("Configuración guardada.", "success")
        return redirect(url_for("configuracion.index"))
    return render_template("configuracion/index.html", items=configuracion.todas(), catalogos=CATALOGOS)


# ------------------------------------------------------------------ Tarjetas y créditos
@bp.route("/financiacion", methods=["GET", "POST"])
@admin_required
def financiacion():
    from .. import db
    from ..models import financiacion as fin
    from ..utils.helpers import clean, to_decimal, to_int

    if request.method == "POST":
        accion = request.form.get("accion")
        try:
            if accion == "entidad_nueva":
                nombre = clean(request.form.get("nombre"), 60)
                tipo = request.form.get("tipo")
                if not nombre or tipo not in fin.TIPOS:
                    raise ValueError("Indicá el nombre y el tipo.")
                eid = db.execute("INSERT INTO entidades_financieras (nombre, tipo) VALUES (%s,%s)", (nombre, tipo))
                auditar(f"{g.user['nombre']} creó la {fin.TIPOS[tipo].lower()} {nombre}", "configuracion", eid)
                flash(f"{nombre} creada. Ahora agregale sus planes de cuotas.", "success")
            elif accion == "entidad_editar":
                eid = to_int(request.form.get("entidad_id"))
                nombre = clean(request.form.get("nombre"), 60)
                if not nombre:
                    raise ValueError("El nombre no puede quedar vacío.")
                db.execute("UPDATE entidades_financieras SET nombre=%s, activo=%s WHERE id=%s",
                           (nombre, 1 if request.form.get("activo") == "1" else 0, eid))
                auditar(f"{g.user['nombre']} editó la tarjeta/crédito {nombre}", "configuracion", eid)
                flash("Guardado.", "success")
            elif accion == "entidad_eliminar":
                eid = to_int(request.form.get("entidad_id"))
                e = db.query("SELECT nombre FROM entidades_financieras WHERE id=%s", (eid,), one=True)
                db.execute("DELETE FROM entidades_financieras WHERE id=%s", (eid,))
                auditar(f"{g.user['nombre']} eliminó la tarjeta/crédito {e['nombre'] if e else eid}", "configuracion", eid)
                flash("Eliminada. Las ventas ya hechas conservan sus datos.", "success")
            elif accion == "plan_nuevo":
                eid = to_int(request.form.get("entidad_id"))
                cuotas = to_int(request.form.get("cuotas"), 0)
                interes = to_decimal(request.form.get("interes_pct"))
                if cuotas <= 0 or interes < 0:
                    raise ValueError("Las cuotas deben ser mayores a 0 y el interés no puede ser negativo.")
                db.execute("""INSERT INTO planes_cuotas (entidad_id, cuotas, interes_pct) VALUES (%s,%s,%s)
                              ON DUPLICATE KEY UPDATE interes_pct=VALUES(interes_pct), activo=1""", (eid, cuotas, interes))
                auditar(f"{g.user['nombre']} cargó el plan de {cuotas} cuotas con {interes}% de interés", "configuracion", eid)
                flash("Plan guardado.", "success")
            elif accion == "plan_editar":
                pid = to_int(request.form.get("plan_id"))
                cuotas = to_int(request.form.get("cuotas"), 0)
                interes = to_decimal(request.form.get("interes_pct"))
                if cuotas <= 0 or interes < 0:
                    raise ValueError("Datos del plan inválidos.")
                db.execute("UPDATE planes_cuotas SET cuotas=%s, interes_pct=%s, activo=%s WHERE id=%s",
                           (cuotas, interes, 1 if request.form.get("activo") == "1" else 0, pid))
                auditar(f"{g.user['nombre']} modificó un plan: {cuotas} cuotas al {interes}%", "configuracion", pid)
                flash("Plan actualizado.", "success")
            elif accion == "plan_eliminar":
                pid = to_int(request.form.get("plan_id"))
                db.execute("DELETE FROM planes_cuotas WHERE id=%s", (pid,))
                flash("Plan eliminado.", "success")
        except ValueError as e:
            flash(str(e), "danger")
        except db.IntegrityError:
            flash("Ya existe una tarjeta/crédito con ese nombre o un plan con esa cantidad de cuotas.", "danger")
        return redirect(url_for("configuracion.financiacion"))
    return render_template("configuracion/financiacion.html", entidades=fin.entidades(), tipos=fin.TIPOS,
                           catalogos=CATALOGOS)
