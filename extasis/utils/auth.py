"""Autenticación, roles, permisos y alcance por ubicación."""
from functools import wraps

from flask import abort, flash, g, redirect, request, session, url_for

from .. import db


def cargar_usuario():
    g.user = None
    g.permisos = set()
    uid = session.get("user_id")
    if not uid:
        return
    user = db.query(
        """SELECT u.id, u.nombre, u.username, u.email, u.rol_id, r.codigo AS rol,
                  r.nombre AS rol_nombre, u.ubicacion_id, u.activo, u.debe_cambiar_password,
                  ub.nombre AS ubicacion_nombre, ub.direccion AS ubicacion_direccion
           FROM usuarios u JOIN roles r ON r.id = u.rol_id
           LEFT JOIN ubicaciones ub ON ub.id = u.ubicacion_id
           WHERE u.id = %s""", (uid,), one=True)
    if not user or not user["activo"]:
        session.clear()
        return
    g.user = user
    rows = db.query(
        """SELECT p.codigo FROM rol_permisos rp JOIN permisos p ON p.id = rp.permiso_id
           WHERE rp.rol_id = %s""", (user["rol_id"],))
    g.permisos = {r["codigo"] for r in rows}


def es_admin():
    return bool(g.get("user")) and g.user["rol"] == "ADMIN"


def tiene_permiso(codigo):
    return es_admin() or codigo in g.get("permisos", set())


def ubicacion_scope():
    """None => ve todo (admin). Si no, el id del local del usuario."""
    if es_admin():
        return None
    return g.user["ubicacion_id"] if g.get("user") else -1


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.get("user"):
            if request.path.startswith("/api/"):
                return {"ok": False, "error": "Sesión expirada"}, 401
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def permiso_required(*codigos):
    def deco(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not any(tiene_permiso(c) for c in codigos):
                if request.path.startswith("/api/"):
                    return {"ok": False, "error": "No tenés permiso para esta acción"}, 403
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return deco


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not es_admin():
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def verificar_acceso_ubicacion(ubicacion_id):
    """Aborta 403 si un usuario de local intenta acceder a otra ubicación."""
    scope = ubicacion_scope()
    if scope is not None and int(ubicacion_id or 0) != int(scope or 0):
        abort(403)


def forzar_cambio_password():
    """Redirige a cambiar contraseña si es la primera vez que inicia sesión."""
    if g.get("user") and g.user["debe_cambiar_password"]:
        permitidos = {"auth.cambiar_password", "auth.logout", "static"}
        if request.endpoint not in permitidos:
            flash("Por seguridad, cambiá tu contraseña de prueba antes de continuar.", "warning")
            return redirect(url_for("auth.cambiar_password"))
    return None
