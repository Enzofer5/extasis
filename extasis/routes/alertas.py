from flask import Blueprint, render_template

from ..services import alertas_service
from ..utils.auth import login_required, ubicacion_scope

bp = Blueprint("alertas", __name__, url_prefix="/alertas")


@bp.route("/")
@login_required
def index():
    return render_template("alertas/index.html", alertas=alertas_service.obtener(ubicacion_scope()))
