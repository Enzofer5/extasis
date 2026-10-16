from datetime import date
from decimal import Decimal

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import db
from ..models import catalogos
from ..utils.audit import auditar
from ..utils.auth import permiso_required
from ..utils.helpers import clean, hay_filtros, paginar, parse_date, to_decimal, to_int

bp = Blueprint("proveedores", __name__, url_prefix="/proveedores")

CAMPOS = ["razon_social", "nombre", "cuit", "dni", "telefono", "email", "direccion", "contacto", "observaciones"]

DEUDA_SQL = """(SELECT COALESCE(SUM(c.total - c.monto_pagado),0) FROM compras c WHERE c.proveedor_id=p.id)
               - (SELECT COALESCE(SUM(pa.monto),0) FROM pagos pa WHERE pa.proveedor_id=p.id)"""


@bp.route("/")
@permiso_required("proveedores.gestionar")
def index():
    args = request.args
    rows, pag = [], None
    buscado = hay_filtros(args)
    if buscado:
        where, params = ["1=1"], []
        q = clean(args.get("q"))
        if q:
            where.append("(p.razon_social LIKE %s OR p.nombre LIKE %s OR p.cuit=%s OR p.dni=%s)")
            params += [f"%{q}%", f"%{q}%", q, q]
        if args.get("estado") in ("0", "1"):
            where.append("p.activo=%s")
            params.append(int(args["estado"]))
        if args.get("con_deuda") == "1":
            where.append(f"({DEUDA_SQL}) > 0")
        w = " AND ".join(where)
        pag = paginar(db.scalar(f"SELECT COUNT(*) FROM proveedores p WHERE {w}", params))
        rows = db.query(f"""SELECT p.*, ({DEUDA_SQL}) AS deuda,
                                   (SELECT COALESCE(SUM(total),0) FROM compras c WHERE c.proveedor_id=p.id) AS comprado
                            FROM proveedores p WHERE {w} ORDER BY p.razon_social LIMIT %s OFFSET %s""",
                        params + [pag.per_page, pag.offset])
    return render_template("proveedores/index.html", rows=rows, pag=pag, buscado=buscado)


def _datos(form):
    d = {k: clean(form.get(k), 2000 if k == "observaciones" else 200) for k in CAMPOS}
    if not d["razon_social"]:
        raise ValueError("La razón social es obligatoria.")
    return d


@bp.route("/nuevo", methods=["GET", "POST"])
@bp.route("/<int:pid>/editar", methods=["GET", "POST"])
@permiso_required("proveedores.gestionar")
def form(pid=None):
    p = db.query("SELECT * FROM proveedores WHERE id=%s", (pid,), one=True) if pid else None
    if pid and not p:
        abort(404)
    if request.method == "POST":
        try:
            d = _datos(request.form)
            d["activo"] = 1 if request.form.get("activo", "1") == "1" else 0
            if p:
                sets = ", ".join(f"{k}=%s" for k in d)
                db.execute(f"UPDATE proveedores SET {sets} WHERE id=%s", list(d.values()) + [pid])
                auditar(f"{g.user['nombre']} editó el proveedor {d['razon_social']}", "proveedores", pid)
            else:
                cols = ", ".join(d)
                pid = db.execute(f"INSERT INTO proveedores ({cols}) VALUES ({', '.join(['%s'] * len(d))})", list(d.values()))
                auditar(f"{g.user['nombre']} creó el proveedor {d['razon_social']}", "proveedores", pid)
            flash("Proveedor guardado.", "success")
            return redirect(url_for("proveedores.detalle", pid=pid))
        except ValueError as e:
            flash(str(e), "danger")
        except db.IntegrityError:
            flash("Ya existe un proveedor con ese CUIT.", "danger")
    return render_template("proveedores/form.html", p=p)


@bp.route("/<int:pid>")
@permiso_required("proveedores.gestionar")
def detalle(pid):
    p = db.query(f"SELECT p.*, ({DEUDA_SQL}) AS deuda FROM proveedores p WHERE p.id=%s", (pid,), one=True) or abort(404)
    compras = db.query("""SELECT c.*, c.total - c.monto_pagado - COALESCE((SELECT SUM(monto) FROM pagos pa WHERE pa.compra_id=c.id),0) AS saldo
                          FROM compras c WHERE c.proveedor_id=%s ORDER BY c.fecha DESC LIMIT 100""", (pid,))
    pagos = db.query("""SELECT pa.*, mp.nombre AS metodo, u.nombre AS usuario FROM pagos pa
                        JOIN metodos_pago mp ON mp.id=pa.metodo_pago_id JOIN usuarios u ON u.id=pa.usuario_id
                        WHERE pa.proveedor_id=%s ORDER BY pa.fecha DESC LIMIT 100""", (pid,))
    total_comprado = db.scalar("SELECT COALESCE(SUM(total),0) FROM compras WHERE proveedor_id=%s", (pid,))
    total_pagado = Decimal(db.scalar("SELECT COALESCE(SUM(monto_pagado),0) FROM compras WHERE proveedor_id=%s", (pid,))) + \
        Decimal(db.scalar("SELECT COALESCE(SUM(monto),0) FROM pagos WHERE proveedor_id=%s", (pid,)))
    return render_template("proveedores/detalle.html", p=p, compras=compras, pagos=pagos,
                           total_comprado=total_comprado, total_pagado=total_pagado,
                           metodos=[m for m in catalogos.metodos_pago() if m["codigo"] != "CTACTE"],
                           hoy=date.today().isoformat())


@bp.route("/<int:pid>/pago", methods=["POST"])
@permiso_required("proveedores.gestionar")
def pago(pid):
    p = db.query(f"SELECT p.*, ({DEUDA_SQL}) AS deuda FROM proveedores p WHERE p.id=%s", (pid,), one=True) or abort(404)
    monto = to_decimal(request.form.get("monto"))
    compra_id = to_int(request.form.get("compra_id"))
    metodo = to_int(request.form.get("metodo_pago_id"))
    if monto <= 0 or not metodo:
        flash("Indicá monto y método de pago.", "danger")
    elif monto > Decimal(p["deuda"]):
        flash(f"El pago supera la deuda pendiente (${p['deuda']:,.2f}).", "danger")
    else:
        if compra_id:
            ok = db.scalar("SELECT COUNT(*) FROM compras WHERE id=%s AND proveedor_id=%s", (compra_id, pid))
            compra_id = compra_id if ok else None
        db.execute("""INSERT INTO pagos (proveedor_id, compra_id, fecha, monto, metodo_pago_id, usuario_id, observaciones)
                      VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                   (pid, compra_id, parse_date(request.form.get("fecha"), date.today()), monto, metodo, g.user["id"],
                    clean(request.form.get("observaciones"), 255)))
        auditar(f"{g.user['nombre']} registró un pago de ${monto:,.2f} a {p['razon_social']}", "proveedores", pid)
        flash("Pago registrado.", "success")
    return redirect(request.referrer or url_for("proveedores.detalle", pid=pid))
