from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from .. import db
from ..models import ubicaciones
from ..utils.audit import auditar
from ..utils.auth import admin_required
from ..utils.helpers import clean, to_int
from .auth import validar_password

bp = Blueprint("usuarios", __name__, url_prefix="/usuarios")


@bp.route("/")
@admin_required
def index():
    rows = db.query("""SELECT u.*, r.nombre AS rol, ub.nombre AS ubicacion FROM usuarios u
                       JOIN roles r ON r.id=u.rol_id LEFT JOIN ubicaciones ub ON ub.id=u.ubicacion_id
                       ORDER BY u.activo DESC, r.id, u.nombre""")
    return render_template("usuarios/index.html", rows=rows)


@bp.route("/nuevo", methods=["GET", "POST"])
@bp.route("/<int:uid>/editar", methods=["GET", "POST"])
@admin_required
def form(uid=None):
    u = db.query("SELECT * FROM usuarios WHERE id=%s", (uid,), one=True) if uid else None
    if uid and not u:
        abort(404)
    roles = db.query("SELECT * FROM roles ORDER BY id")
    if request.method == "POST":
        f = request.form
        nombre = clean(f.get("nombre"), 100)
        username = (clean(f.get("username"), 50) or "").lower()
        rol_id = to_int(f.get("rol_id"))
        ub = to_int(f.get("ubicacion_id"))
        pw = f.get("password") or ""
        activo = 1 if f.get("activo", "1") == "1" else 0
        rol = next((r for r in roles if r["id"] == rol_id), None)
        err = None
        if not nombre or not username or not rol:
            err = "Nombre, usuario y rol son obligatorios."
        elif not username.replace(".", "").replace("_", "").isalnum():
            err = "El usuario sólo puede tener letras, números, punto o guion bajo."
        elif rol["codigo"] == "LOCAL" and not ub:
            err = "Un usuario de local debe tener un local asignado."
        elif (not u or pw) and (e := validar_password(pw)):
            err = e
        elif u and u["id"] == g.user["id"] and (not activo or rol["codigo"] != "ADMIN"):
            err = "No podés desactivarte ni quitarte el rol de administrador a vos mismo."
        if err:
            flash(err, "danger")
        else:
            if rol["codigo"] == "ADMIN":
                ub = None
            try:
                if u:
                    db.execute("""UPDATE usuarios SET nombre=%s, username=%s, email=%s, rol_id=%s, ubicacion_id=%s, activo=%s
                                  WHERE id=%s""", (nombre, username, clean(f.get("email"), 120), rol_id, ub, activo, uid))
                    if pw:
                        db.execute("UPDATE usuarios SET password_hash=%s, debe_cambiar_password=1 WHERE id=%s",
                                   (generate_password_hash(pw), uid))
                    auditar(f"{g.user['nombre']} editó el usuario {username}", "usuarios", uid)
                else:
                    uid = db.execute("""INSERT INTO usuarios (nombre, username, email, password_hash, rol_id, ubicacion_id, activo,
                                        debe_cambiar_password) VALUES (%s,%s,%s,%s,%s,%s,%s,1)""",
                                     (nombre, username, clean(f.get("email"), 120), generate_password_hash(pw), rol_id, ub, activo))
                    auditar(f"{g.user['nombre']} creó el usuario {username}", "usuarios", uid)
                flash("Usuario guardado. Deberá cambiar la contraseña al ingresar." if pw else "Usuario guardado.", "success")
                return redirect(url_for("usuarios.index"))
            except db.IntegrityError:
                flash("Ese nombre de usuario ya existe.", "danger")
    return render_template("usuarios/form.html", u=u, roles=roles, locales=ubicaciones.locales())


@bp.route("/<int:uid>/eliminar", methods=["POST"])
@admin_required
def eliminar(uid):
    if uid == g.user["id"]:
        flash("No podés eliminar tu propio usuario.", "danger")
        return redirect(url_for("usuarios.index"))
    u = db.query("SELECT * FROM usuarios WHERE id=%s", (uid,), one=True) or abort(404)
    try:
        db.execute("DELETE FROM usuarios WHERE id=%s", (uid,))
        auditar(f"{g.user['nombre']} eliminó el usuario {u['username']}", "usuarios", uid)
        flash("Usuario eliminado.", "success")
    except db.IntegrityError:
        db.execute("UPDATE usuarios SET activo=0 WHERE id=%s", (uid,))
        auditar(f"{g.user['nombre']} desactivó el usuario {u['username']} (tiene operaciones registradas)", "usuarios", uid)
        flash("El usuario tiene operaciones registradas: se desactivó en lugar de eliminarse.", "warning")
    return redirect(url_for("usuarios.index"))
