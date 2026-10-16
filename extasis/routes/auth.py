import re
import time

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .. import db
from ..utils.audit import auditar
from ..utils.auth import login_required

bp = Blueprint("auth", __name__)

_intentos = {}  # protección simple contra fuerza bruta: ip -> [timestamps]


def _bloqueado(ip):
    ahora = time.time()
    lst = [t for t in _intentos.get(ip, []) if ahora - t < 300]
    _intentos[ip] = lst
    return len(lst) >= 8


def validar_password(pw):
    if len(pw) < 8:
        return "La contraseña debe tener al menos 8 caracteres."
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return "La contraseña debe combinar letras y números."
    return None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("user"):
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        ip = request.remote_addr or "?"
        if _bloqueado(ip):
            flash("Demasiados intentos fallidos. Esperá 5 minutos.", "danger")
            return render_template("auth/login.html"), 429
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        user = db.query("SELECT * FROM usuarios WHERE username=%s", (username,), one=True)
        if not user or not check_password_hash(user["password_hash"], password):
            _intentos.setdefault(ip, []).append(time.time())
            flash("Usuario o contraseña incorrectos.", "danger")
            return render_template("auth/login.html", username=username)
        if not user["activo"]:
            flash("El usuario está desactivado.", "danger")
            return render_template("auth/login.html", username=username)
        session.clear()
        session.permanent = True
        session["user_id"] = user["id"]
        db.execute("UPDATE usuarios SET ultimo_login=NOW() WHERE id=%s", (user["id"],))
        g.user = user
        auditar(f"{user['nombre']} inició sesión", "auth", user["id"])
        nxt = request.args.get("next")
        if nxt and nxt.startswith("/") and not nxt.startswith("//"):
            return redirect(nxt)
        return redirect(url_for("dashboard.index"))
    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/cambiar-password", methods=["GET", "POST"])
@login_required
def cambiar_password():
    if request.method == "POST":
        actual = request.form.get("actual") or ""
        nueva = request.form.get("nueva") or ""
        repetir = request.form.get("repetir") or ""
        row = db.query("SELECT password_hash FROM usuarios WHERE id=%s", (g.user["id"],), one=True)
        if not check_password_hash(row["password_hash"], actual):
            flash("La contraseña actual no es correcta.", "danger")
        elif nueva != repetir:
            flash("Las contraseñas nuevas no coinciden.", "danger")
        elif nueva == actual:
            flash("La nueva contraseña debe ser distinta de la actual.", "danger")
        elif (err := validar_password(nueva)):
            flash(err, "danger")
        else:
            db.execute("UPDATE usuarios SET password_hash=%s, debe_cambiar_password=0 WHERE id=%s",
                       (generate_password_hash(nueva), g.user["id"]))
            auditar(f"{g.user['nombre']} cambió su contraseña", "auth", g.user["id"])
            flash("Contraseña actualizada.", "success")
            return redirect(url_for("dashboard.index"))
    return render_template("auth/cambiar_password.html")
