from decimal import Decimal

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from .. import db
from ..models import catalogos, ubicaciones
from ..services import NegocioError, cc_service
from ..utils.audit import auditar
from ..utils.auth import es_admin, permiso_required, ubicacion_scope
from ..utils.helpers import clean, hay_filtros, paginar, to_decimal, to_int

bp = Blueprint("clientes", __name__)

CAMPOS = ["nombre", "apellido", "dni", "telefono", "whatsapp", "email", "direccion"]


def _scope_sql(alias="c"):
    scope = ubicacion_scope()
    if scope:
        return f" AND {alias}.ubicacion_id=%s", [scope]
    return "", []


@bp.route("/clientes")
@permiso_required("clientes.gestionar")
def index():
    args = request.args
    rows, pag = [], None
    buscado = hay_filtros(args)
    if buscado:
        where, params = ["1=1"], []
        s, sp = _scope_sql()
        q = clean(args.get("q"))
        if q:
            where.append("(c.nombre LIKE %s OR c.apellido LIKE %s OR c.dni=%s OR c.telefono LIKE %s OR CONCAT(c.nombre,' ',c.apellido) LIKE %s)")
            params += [f"%{q}%", f"%{q}%", q, f"%{q}%", f"%{q}%"]
        if args.get("estado") in ("0", "1"):
            where.append("c.activo=%s")
            params.append(int(args["estado"]))
        ub = to_int(args.get("ubicacion_id"))
        if ub and es_admin():
            where.append("c.ubicacion_id=%s")
            params.append(ub)
        if args.get("con_saldo") == "1":
            where.append("COALESCE(sc.saldo,0) > 0")
        w = " AND ".join(where) + s
        params += sp
        base = f"FROM clientes c LEFT JOIN v_saldos_cc sc ON sc.cliente_id=c.id LEFT JOIN ubicaciones ub ON ub.id=c.ubicacion_id WHERE {w}"
        pag = paginar(db.scalar(f"SELECT COUNT(*) {base}", params))
        rows = db.query(f"""SELECT c.*, COALESCE(sc.saldo,0) AS saldo, ub.nombre AS ubicacion,
                                   (SELECT MAX(fecha) FROM ventas v WHERE v.cliente_id=c.id AND v.estado<>'Anulada') AS ultima_compra
                            {base} ORDER BY c.apellido, c.nombre LIMIT %s OFFSET %s""", params + [pag.per_page, pag.offset])
    return render_template("clientes/index.html", rows=rows, pag=pag, buscado=buscado,
                           ubics=ubicaciones.locales() if es_admin() else [])


def _get(cid):
    c = db.query("""SELECT c.*, ub.nombre AS ubicacion FROM clientes c LEFT JOIN ubicaciones ub ON ub.id=c.ubicacion_id
                    WHERE c.id=%s""", (cid,), one=True)
    if not c:
        abort(404)
    scope = ubicacion_scope()
    if scope and c["ubicacion_id"] != scope:
        abort(403)
    return c


def _datos(form):
    d = {k: clean(form.get(k), 200) for k in CAMPOS}
    if not d["nombre"] or not d["apellido"]:
        raise ValueError("Nombre y apellido son obligatorios.")
    if d["dni"] and not d["dni"].replace(".", "").isdigit():
        raise ValueError("El DNI debe contener sólo números.")
    if d["dni"]:
        d["dni"] = d["dni"].replace(".", "")
    return d


@bp.route("/clientes/nuevo", methods=["GET", "POST"])
@bp.route("/clientes/<int:cid>/editar", methods=["GET", "POST"])
@permiso_required("clientes.gestionar")
def form(cid=None):
    c = _get(cid) if cid else None
    if request.method == "POST":
        try:
            d = _datos(request.form)
            if es_admin():
                d["ubicacion_id"] = to_int(request.form.get("ubicacion_id"))
                d["activo"] = 1 if request.form.get("activo", "1") == "1" else 0
            elif not c:
                d["ubicacion_id"] = g.user["ubicacion_id"]
            limite = to_decimal(request.form.get("limite_credito"))
            with db.transaction() as tx:
                if c:
                    sets = ", ".join(f"{k}=%s" for k in d)
                    tx.execute(f"UPDATE clientes SET {sets} WHERE id=%s", list(d.values()) + [cid])
                    accion = "editó"
                else:
                    cols = ", ".join(d)
                    cid = tx.execute(f"INSERT INTO clientes ({cols}) VALUES ({', '.join(['%s'] * len(d))})", list(d.values()))
                    accion = "registró"
                cuenta = cc_service.cuenta_de(tx, cid)
                if es_admin():
                    tx.execute("UPDATE cuentas_corrientes SET limite_credito=%s WHERE id=%s", (max(limite, 0), cuenta["id"]))
                auditar(f"{g.user['nombre']} {accion} el cliente {d['apellido']}, {d['nombre']}", "clientes", cid, tx)
            flash("Cliente guardado.", "success")
            return redirect(url_for("clientes.detalle", cid=cid))
        except ValueError as e:
            flash(str(e), "danger")
        except db.IntegrityError:
            flash("Ya existe un cliente con ese DNI.", "danger")
    limite = db.scalar("SELECT limite_credito FROM cuentas_corrientes WHERE cliente_id=%s", (cid,), 0) if cid else 0
    return render_template("clientes/form.html", c=c, limite=limite,
                           ubics=ubicaciones.locales() if es_admin() else [])


@bp.route("/clientes/<int:cid>")
@permiso_required("clientes.gestionar")
def detalle(cid):
    c = _get(cid)
    ventas = db.query("""SELECT v.id, v.fecha, v.total, v.estado, mp.nombre AS metodo, ub.nombre AS ubicacion
                         FROM ventas v JOIN metodos_pago mp ON mp.id=v.metodo_pago_id JOIN ubicaciones ub ON ub.id=v.ubicacion_id
                         WHERE v.cliente_id=%s ORDER BY v.fecha DESC LIMIT 50""", (cid,))
    total_gastado = db.scalar("SELECT COALESCE(SUM(total),0) FROM ventas WHERE cliente_id=%s AND estado='Completada'", (cid,))
    movs = cc_service.movimientos(cid)
    saldo = movs[-1]["saldo"] if movs else Decimal(0)
    limite = db.scalar("SELECT limite_credito FROM cuentas_corrientes WHERE cliente_id=%s", (cid,), 0)
    return render_template("clientes/detalle.html", c=c, ventas=ventas, total_gastado=total_gastado,
                           ultima=ventas[0]["fecha"] if ventas else None, movs=movs, saldo=saldo, limite=limite,
                           metodos=[m for m in catalogos.metodos_pago() if m["codigo"] != "CTACTE"],
                           locales=ubicaciones.locales() if es_admin() else [])


@bp.route("/clientes/<int:cid>/pago", methods=["POST"])
@permiso_required("clientes.cobrar")
def pago(cid):
    c = _get(cid)
    monto = to_decimal(request.form.get("monto"))
    metodo = to_int(request.form.get("metodo_pago_id"))
    ub = ubicacion_scope() or to_int(request.form.get("ubicacion_id"))
    try:
        cc_service.registrar_pago(cid, monto, metodo, g.user["id"], ub, clean(request.form.get("concepto"), 200))
        auditar(f"{g.user['nombre']} registró un pago de ${monto:,.2f} de {c['apellido']}, {c['nombre']}", "clientes", cid)
        flash("Pago registrado en la cuenta corriente.", "success")
    except NegocioError as e:
        flash(str(e), "danger")
    return redirect(url_for("clientes.detalle", cid=cid))


@bp.route("/clientes/cuentas")
@permiso_required("clientes.gestionar")
def cuentas():
    s, sp = _scope_sql()
    rows = db.query(f"""SELECT c.id, c.nombre, c.apellido, c.dni, c.telefono, c.whatsapp, ub.nombre AS ubicacion,
                               sc.debe, sc.haber, sc.saldo, sc.ultimo_movimiento, cc.limite_credito
                        FROM v_saldos_cc sc JOIN clientes c ON c.id=sc.cliente_id
                        JOIN cuentas_corrientes cc ON cc.id=sc.cuenta_id
                        LEFT JOIN ubicaciones ub ON ub.id=c.ubicacion_id
                        WHERE sc.saldo <> 0 {s} ORDER BY sc.saldo DESC""", sp)
    total = sum((Decimal(r["saldo"]) for r in rows), Decimal(0))
    return render_template("clientes/cuentas.html", rows=rows, total=total)


# ------------------------------------------------------------------ API (POS)
@bp.route("/api/clientes/buscar")
@permiso_required("clientes.gestionar", "ventas.crear")
def api_buscar():
    q = clean(request.args.get("q"))
    if not q:
        return jsonify([])
    s, sp = _scope_sql()
    rows = db.query(f"""SELECT c.id, c.nombre, c.apellido, c.dni, c.telefono, COALESCE(sc.saldo,0) AS saldo
                        FROM clientes c LEFT JOIN v_saldos_cc sc ON sc.cliente_id=c.id
                        WHERE c.activo=1 AND (c.nombre LIKE %s OR c.apellido LIKE %s OR c.dni=%s
                              OR CONCAT(c.nombre,' ',c.apellido) LIKE %s) {s}
                        ORDER BY c.apellido LIMIT 15""", [f"%{q}%", f"%{q}%", q, f"%{q}%"] + sp)
    return jsonify([{**r, "saldo": float(r["saldo"])} for r in rows])


@bp.route("/api/clientes", methods=["POST"])
@permiso_required("clientes.gestionar")
def api_crear():
    data = request.get_json(silent=True) or {}
    try:
        d = _datos(data)
        d["ubicacion_id"] = g.user["ubicacion_id"] if not es_admin() else to_int(data.get("ubicacion_id"))
        with db.transaction() as tx:
            cols = ", ".join(d)
            cid = tx.execute(f"INSERT INTO clientes ({cols}) VALUES ({', '.join(['%s'] * len(d))})", list(d.values()))
            cc_service.cuenta_de(tx, cid)
            auditar(f"{g.user['nombre']} registró el cliente {d['apellido']}, {d['nombre']}", "clientes", cid, tx)
        return jsonify(ok=True, cliente={"id": cid, "nombre": d["nombre"], "apellido": d["apellido"],
                                         "dni": d["dni"], "saldo": 0})
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except db.IntegrityError:
        return jsonify(ok=False, error="Ya existe un cliente con ese DNI."), 400
