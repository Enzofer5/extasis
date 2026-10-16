"""ÉXTASIS — fábrica de la aplicación Flask."""
import os

from flask import Flask, flash, g, jsonify, redirect, render_template, request, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect

from . import db
from .config import Config

csrf = CSRFProtect()


def create_app(config_class=Config):
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.from_object(config_class)
    app.config["TEMPLATES_AUTO_RELOAD"] = True  # cambios en pantallas sin reiniciar
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_pool(app)
    csrf.init_app(app)

    from .utils import helpers
    from .utils.auth import cargar_usuario, es_admin, forzar_cambio_password, tiene_permiso

    app.jinja_env.filters["money"] = helpers.money
    app.jinja_env.filters["fecha"] = helpers.fecha_fmt
    app.jinja_env.filters["fecha_corta"] = lambda v: helpers.fecha_fmt(v, False)

    @app.before_request
    def _antes():
        if request.endpoint == "static":
            return None
        cargar_usuario()
        return forzar_cambio_password()

    @app.context_processor
    def _ctx():
        from .services import alertas_service
        alertas = []
        if g.get("user") and not g.user["debe_cambiar_password"] and request.endpoint != "static":
            try:
                from .utils.auth import ubicacion_scope
                alertas = alertas_service.obtener(ubicacion_scope())
            except Exception:  # las alertas nunca deben romper una pantalla
                alertas = []
        return {"es_admin": es_admin, "tiene_permiso": tiene_permiso, "alertas_nav": alertas,
                "nombre_negocio": "ÉXTASIS"}

    @app.after_request
    def _seguridad(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        return resp

    # Blueprints
    from .routes import (alertas, auditoria, auth, cajas, catalogos, clientes, compras, configuracion,
                         dashboard, devoluciones, empleados, gastos, inventarios, locales, panel, productos,
                         proveedores, reportes, solicitudes, stock, transferencias, usuarios, ventas)
    for mod in (auth, dashboard, productos, catalogos, stock, transferencias, solicitudes, compras,
                proveedores, clientes, ventas, devoluciones, cajas, empleados, gastos, reportes,
                inventarios, usuarios, locales, configuracion, auditoria, alertas, panel):
        app.register_blueprint(mod.bp)

    # Errores
    @app.errorhandler(CSRFError)
    def _csrf(e):
        if request.path.startswith("/api/") or request.is_json:
            return jsonify(ok=False, error="La sesión del formulario expiró. Recargá la página."), 400
        flash("El formulario expiró por seguridad. Volvé a intentarlo.", "danger")
        return redirect(request.referrer or url_for("dashboard.index"))

    @app.errorhandler(403)
    def _403(e):
        return render_template("errores/error.html", codigo=403,
                               mensaje="No tenés permiso para acceder a esta sección."), 403

    @app.errorhandler(404)
    def _404(e):
        return render_template("errores/error.html", codigo=404, mensaje="La página no existe."), 404

    @app.errorhandler(413)
    def _413(e):
        flash("El archivo es demasiado grande (máximo 5 MB).", "danger")
        return redirect(request.referrer or url_for("dashboard.index"))

    @app.errorhandler(500)
    def _500(e):
        return render_template("errores/error.html", codigo=500,
                               mensaje="Ocurrió un error inesperado. Si persiste, avisá al administrador."), 500

    return app
