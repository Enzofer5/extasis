"""Gastos del negocio: servicios / fijos (luz, agua, alquiler, WiFi...) y gastos diarios pagados con la caja."""
from datetime import date

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from .. import db
from ..models import catalogos, ubicaciones
from ..services import NegocioError, caja_service
from ..utils.audit import auditar
from ..utils.auth import permiso_required
from ..utils.helpers import clean, paginar, parse_date, rango_fechas, to_decimal, to_int

bp = Blueprint("gastos", __name__, url_prefix="/gastos")


def _categorias(tipo):
    return db.query("SELECT * FROM categorias_gasto WHERE activo=1 AND tipo=%s ORDER BY nombre", (tipo,))


@bp.route("/", methods=["GET", "POST"])
@permiso_required("gastos.gestionar")
def index():
    if request.method == "POST":
        f = request.form
        accion = f.get("accion")
        monto = to_decimal(f.get("monto"))
        cat = to_int(f.get("categoria_gasto_id"))
        metodo = to_int(f.get("metodo_pago_id"))
        try:
            if monto <= 0 or not cat or not metodo:
                raise NegocioError("Completá el tipo de gasto, el monto y el medio de pago.")
            cat_row = db.query("SELECT * FROM categorias_gasto WHERE id=%s", (cat,), one=True)
            if not cat_row:
                raise NegocioError("Tipo de gasto inválido.")
            if accion == "diario":
                ub = to_int(f.get("ubicacion_id"))
                desc = clean(f.get("descripcion"), 200) or cat_row["nombre"]
                with db.transaction() as tx:
                    caja = caja_service.caja_abierta(ub, tx) if ub else None
                    if not caja:
                        raise NegocioError("Ese local no tiene la caja abierta: el gasto diario se descuenta de la caja.")
                    caja_service.registrar(tx, caja["id"], "GASTO", f"{cat_row['nombre']}: {desc}", monto, metodo, g.user["id"])
                    gid = tx.execute("""INSERT INTO gastos (categoria_gasto_id, descripcion, monto, ubicacion_id, fecha,
                                        metodo_pago_id, usuario_id, caja_id, observaciones)
                                        VALUES (%s,%s,%s,%s,CURDATE(),%s,%s,%s,%s)""",
                                     (cat, desc, monto, ub, metodo, g.user["id"], caja["id"], clean(f.get("observaciones"), 255)))
                    auditar(f"{g.user['nombre']} registró un gasto diario de caja: {desc} ${monto:,.2f}", "gastos", gid, tx)
                flash("Gasto diario registrado y descontado de la caja del local.", "success")
                return redirect(url_for("gastos.index", tab="diarios"))
            # servicio / gasto fijo
            periodo = (f.get("periodo") or "")[:7] or None
            desc = clean(f.get("descripcion"), 200) or (f"{cat_row['nombre']} {periodo[5:]}/{periodo[:4]}" if periodo else cat_row["nombre"])
            ub = to_int(f.get("ubicacion_id"))  # vacío = negocio general
            gid = db.execute("""INSERT INTO gastos (categoria_gasto_id, descripcion, monto, ubicacion_id, fecha, metodo_pago_id,
                                usuario_id, observaciones, periodo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                             (cat, desc, monto, ub, parse_date(f.get("fecha"), date.today()), metodo, g.user["id"],
                              clean(f.get("observaciones"), 255), periodo))
            auditar(f"{g.user['nombre']} registró el pago de {desc} por ${monto:,.2f}", "gastos", gid)
            flash("Pago de servicio registrado.", "success")
            return redirect(url_for("gastos.index", tab="servicios"))
        except NegocioError as e:
            flash(str(e), "danger")
            return redirect(url_for("gastos.index", tab="diarios" if accion == "diario" else "servicios"))

    args = request.args
    tab = args.get("tab") if args.get("tab") in ("servicios", "diarios") else "servicios"
    desde, hasta, hasta_ex = rango_fechas(args, 31)
    tipo = "SERVICIO" if tab == "servicios" else "DIARIO"
    where, params = ["g.fecha>=%s", "g.fecha<%s", "cg.tipo=%s"], [desde, hasta_ex, tipo]
    cat = to_int(args.get("categoria_gasto_id"))
    if cat:
        where.append("g.categoria_gasto_id=%s")
        params.append(cat)
    ub = args.get("ubicacion_id")
    if ub == "general":
        where.append("g.ubicacion_id IS NULL")
    elif to_int(ub):
        where.append("g.ubicacion_id=%s")
        params.append(int(ub))
    w = " AND ".join(where)
    base = f"""FROM gastos g JOIN categorias_gasto cg ON cg.id=g.categoria_gasto_id
               LEFT JOIN ubicaciones ub ON ub.id=g.ubicacion_id JOIN metodos_pago mp ON mp.id=g.metodo_pago_id
               JOIN usuarios u ON u.id=g.usuario_id WHERE {w}"""
    total = db.scalar(f"SELECT COALESCE(SUM(g.monto),0) {base}", params)
    por_cat = db.query(f"SELECT cg.nombre AS etiqueta, SUM(g.monto) AS total {base} GROUP BY cg.nombre ORDER BY total DESC", params)
    pag = paginar(db.scalar(f"SELECT COUNT(*) {base}", params))
    rows = db.query(f"""SELECT g.*, cg.nombre AS categoria, COALESCE(ub.nombre,'Negocio general') AS ubicacion,
                               mp.nombre AS metodo, u.nombre AS usuario
                        {base} ORDER BY g.fecha DESC, g.id DESC LIMIT %s OFFSET %s""", params + [pag.per_page, pag.offset])
    # Totales del mes para las dos pestañas
    ini_mes = date.today().replace(day=1)
    mes = {r["tipo"]: r["total"] for r in db.query(
        """SELECT cg.tipo, COALESCE(SUM(g.monto),0) AS total FROM gastos g JOIN categorias_gasto cg ON cg.id=g.categoria_gasto_id
           WHERE g.fecha >= %s GROUP BY cg.tipo""", (ini_mes,))}
    locales_caja = []
    for l in ubicaciones.locales():
        l["caja"] = caja_service.caja_abierta(l["id"])
        locales_caja.append(l)
    metodos = [m for m in catalogos.metodos_pago() if m["codigo"] not in ("CTACTE", "CREDPERS")]
    return render_template("gastos/index.html", tab=tab, rows=rows, pag=pag, total=total, por_cat=por_cat,
                           desde=desde, hasta=hasta, cats=_categorias(tipo), cats_servicio=_categorias("SERVICIO"),
                           cats_diario=_categorias("DIARIO"), ubics=ubicaciones.listar(), locales_caja=locales_caja,
                           metodos=metodos, hoy=date.today().isoformat(), periodo=date.today().strftime("%Y-%m"), mes=mes)
