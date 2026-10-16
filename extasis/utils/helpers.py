"""Utilidades generales: formato, parseo, paginación, fechas."""
import math
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import current_app, request


def money(value):
    """$ 1.234.567,89 (formato argentino)."""
    try:
        v = Decimal(value or 0)
    except (InvalidOperation, TypeError):
        v = Decimal(0)
    neg = v < 0
    v = abs(v).quantize(Decimal("0.01"))
    entero, dec = f"{v:.2f}".split(".")
    entero = f"{int(entero):,}".replace(",", ".")
    txt = f"$ {entero},{dec}" if dec != "00" else f"$ {entero}"
    return f"-{txt}" if neg else txt


def to_decimal(value, default=Decimal("0")):
    if value is None or value == "":
        return default
    try:
        s = str(value).strip().replace("$", "").replace(" ", "")
        # admite 1.234,56 o 1234.56
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return default


def to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clean(value, maxlen=None):
    if value is None:
        return None
    v = str(value).strip()
    if v == "":
        return None
    return v[:maxlen] if maxlen else v


def fecha_fmt(value, con_hora=True):
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M") if con_hora else value.strftime("%d/%m/%Y")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return str(value)


def parse_date(value, default=None):
    if not value:
        return default
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return default


def rango_fechas(args, default_dias=30):
    """Lee ?desde=&hasta= (YYYY-MM-DD). Devuelve (desde, hasta_inclusive, hasta_exclusivo)."""
    hoy = date.today()
    desde = parse_date(args.get("desde"), hoy - timedelta(days=default_dias - 1))
    hasta = parse_date(args.get("hasta"), hoy)
    if hasta < desde:
        desde, hasta = hasta, desde
    return desde, hasta, hasta + timedelta(days=1)


PERIODOS = [("hoy", "Hoy"), ("7dias", "Últimos 7 días"), ("mes", "Este mes"), ("mes_anterior", "Mes anterior")]


def periodo(args, default="mes"):
    """Período elegido con ?periodo= (o ?desde=&hasta= para un rango a elección).

    Devuelve (desde, hasta_inclusive, hasta_exclusivo, clave); clave es "rango" si se usaron fechas.
    """
    hoy = date.today()
    clave = args.get("periodo")
    if clave not in dict(PERIODOS):
        if args.get("desde") or args.get("hasta"):
            desde, hasta, hasta_ex = rango_fechas(args)
            return desde, hasta, hasta_ex, "rango"
        clave = default
    if clave == "hoy":
        desde, hasta = hoy, hoy
    elif clave == "7dias":
        desde, hasta = hoy - timedelta(days=6), hoy
    elif clave == "mes":
        desde, hasta = hoy.replace(day=1), hoy
    else:  # mes_anterior
        hasta = hoy.replace(day=1) - timedelta(days=1)
        desde = hasta.replace(day=1)
    return desde, hasta, hasta + timedelta(days=1), clave


class Paginacion:
    def __init__(self, total, page, per_page):
        self.total = total
        self.page = page
        self.per_page = per_page
        self.pages = max(1, math.ceil(total / per_page)) if per_page else 1

    @property
    def offset(self):
        return (self.page - 1) * self.per_page

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page < self.pages

    def url(self, page):
        args = request.args.to_dict()
        args["page"] = page
        from urllib.parse import urlencode
        return f"{request.path}?{urlencode(args)}"


def paginar(total):
    page = max(1, to_int(request.args.get("page"), 1))
    per_page = current_app.config.get("PER_PAGE", 20)
    return Paginacion(total, page, per_page)


def hay_filtros(args, ignorar=("page",)):
    """Las listas se muestran siempre, sin tener que apretar "Buscar" primero (modo simple)."""
    return True


def ean13_check_digit(base12):
    total = 0
    for i, ch in enumerate(base12):
        n = int(ch)
        total += n * (3 if i % 2 else 1)
    return str((10 - total % 10) % 10)


def allowed_image(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in current_app.config["ALLOWED_IMAGE_EXT"]
