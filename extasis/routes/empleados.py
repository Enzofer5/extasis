from datetime import date

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import db
from ..models import catalogos, ubicaciones
from ..utils.audit import auditar
from ..utils.auth import permiso_required
from ..utils.helpers import clean, hay_filtros, paginar, parse_date, rango_fechas, to_decimal, to_int

bp = Blueprint("empleados", __name__, url_prefix="/empleados")

PUESTOS = ["Vendedor", "Encargado", "Cajero", "Administrativo", "Depósito", "Otro"]


@bp.route("/")
@permiso_required("empleados.gestionar")
def index():
    args = request.args
    rows, pag = [], None
    buscado = hay_filtros(args)
    if buscado:
        where, params = ["1=1"], []
        q = clean(args.get("q"))
        if q:
            where.append("(e.nombre LIKE %s OR e.apellido LIKE %s OR e.dni=%s)")
            params += [f"%{q}%", f"%{q}%", q]
        if args.get("puesto") in PUESTOS:
            where.append("e.puesto=%s")
            params.append(args["puesto"])
        ub = to_int(args.get("ubicacion_id"))
        if ub:
            where.append("e.ubicacion_id=%s")
            params.append(ub)
        if args.get("estado") in ("0", "1"):
            where.append("e.activo=%s")
            params.append(int(args["estado"]))
        w = " AND ".join(where)
        pag = paginar(db.scalar(f"SELECT COUNT(*) FROM empleados e WHERE {w}", params))
        rows = db.query(f"""SELECT e.*, ub.nombre AS ubicacion,
                                   (SELECT COALESCE(SUM(monto),0) FROM pagos_empleados p WHERE p.empleado_id=e.id) AS pagado
                            FROM empleados e LEFT JOIN ubicaciones ub ON ub.id=e.ubicacion_id
                            WHERE {w} ORDER BY e.apellido, e.nombre LIMIT %s OFFSET %s""",
                        params + [pag.per_page, pag.offset])
    return render_template("empleados/index.html", rows=rows, pag=pag, buscado=buscado, puestos=PUESTOS,
                           ubics=ubicaciones.listar())


@bp.route("/nuevo", methods=["GET", "POST"])
@bp.route("/<int:eid>/editar", methods=["GET", "POST"])
@permiso_required("empleados.gestionar")
def form(eid=None):
    e = db.query("SELECT * FROM empleados WHERE id=%s", (eid,), one=True) if eid else None
    if eid and not e:
        abort(404)
    if request.method == "POST":
        f = request.form
        d = {
            "nombre": clean(f.get("nombre"), 80), "apellido": clean(f.get("apellido"), 80),
            "dni": (clean(f.get("dni"), 15) or "").replace(".", ""), "telefono": clean(f.get("telefono"), 40),
            "email": clean(f.get("email"), 120), "puesto": f.get("puesto") if f.get("puesto") in PUESTOS else "Otro",
            "fecha_ingreso": parse_date(f.get("fecha_ingreso")), "sueldo": to_decimal(f.get("sueldo")),
            "activo": 1 if f.get("activo", "1") == "1" else 0, "ubicacion_id": to_int(f.get("ubicacion_id")),
        }
        if not d["nombre"] or not d["apellido"] or not d["dni"]:
            flash("Nombre, apellido y DNI son obligatorios.", "danger")
        elif d["sueldo"] < 0:
            flash("El sueldo no puede ser negativo.", "danger")
        else:
            try:
                if e:
                    sets = ", ".join(f"{k}=%s" for k in d)
                    db.execute(f"UPDATE empleados SET {sets} WHERE id=%s", list(d.values()) + [eid])
                    auditar(f"{g.user['nombre']} editó al empleado {d['apellido']}, {d['nombre']}", "empleados", eid)
                else:
                    cols = ", ".join(d)
                    eid = db.execute(f"INSERT INTO empleados ({cols}) VALUES ({', '.join(['%s'] * len(d))})", list(d.values()))
                    auditar(f"{g.user['nombre']} dio de alta al empleado {d['apellido']}, {d['nombre']}", "empleados", eid)
                flash("Empleado guardado.", "success")
                return redirect(url_for("empleados.detalle", eid=eid))
            except db.IntegrityError:
                flash("Ya existe un empleado con ese DNI.", "danger")
    return render_template("empleados/form.html", e=e, puestos=PUESTOS, ubics=ubicaciones.listar())


@bp.route("/<int:eid>")
@permiso_required("empleados.gestionar")
def detalle(eid):
    e = db.query("""SELECT e.*, ub.nombre AS ubicacion FROM empleados e LEFT JOIN ubicaciones ub ON ub.id=e.ubicacion_id
                    WHERE e.id=%s""", (eid,), one=True) or abort(404)
    pagos = db.query("""SELECT p.*, mp.nombre AS metodo, u.nombre AS usuario FROM pagos_empleados p
                        JOIN metodos_pago mp ON mp.id=p.metodo_pago_id JOIN usuarios u ON u.id=p.usuario_id
                        WHERE p.empleado_id=%s ORDER BY p.fecha DESC, p.id DESC""", (eid,))
    total = sum(p["monto"] for p in pagos) if pagos else 0
    return render_template("empleados/detalle.html", e=e, pagos=pagos, total=total,
                           metodos=[m for m in catalogos.metodos_pago() if m["codigo"] != "CTACTE"],
                           hoy=date.today().isoformat(), periodo=date.today().strftime("%Y-%m"))


@bp.route("/<int:eid>/pago", methods=["POST"])
@permiso_required("empleados.gestionar")
def pago(eid):
    e = db.query("SELECT * FROM empleados WHERE id=%s", (eid,), one=True) or abort(404)
    f = request.form
    monto = to_decimal(f.get("monto"))
    periodo = (f.get("periodo") or "")[:7]
    concepto = clean(f.get("concepto"), 120)
    metodo = to_int(f.get("metodo_pago_id"))
    if monto <= 0 or not concepto or len(periodo) != 7 or not metodo:
        flash("Completá concepto, período, monto y método de pago.", "danger")
    else:
        pid = db.execute("""INSERT INTO pagos_empleados (empleado_id, concepto, periodo, monto, fecha, metodo_pago_id,
                            usuario_id, observaciones) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                         (eid, concepto, periodo, monto, parse_date(f.get("fecha"), date.today()), metodo, g.user["id"],
                          clean(f.get("observaciones"), 255)))
        auditar(f"{g.user['nombre']} registró pago de ${monto:,.2f} a {e['apellido']}, {e['nombre']} ({concepto})",
                "empleados", pid)
        flash("Pago registrado.", "success")
    return redirect(url_for("empleados.detalle", eid=eid))


@bp.route("/pagos")
@permiso_required("empleados.gestionar")
def pagos():
    args = request.args
    desde, hasta, hasta_ex = rango_fechas(args, 90)
    where, params = ["p.fecha>=%s", "p.fecha<%s"], [desde, hasta_ex]
    ub = to_int(args.get("ubicacion_id"))
    if ub:
        where.append("e.ubicacion_id=%s")
        params.append(ub)
    if args.get("periodo"):
        where.append("p.periodo=%s")
        params.append(args["periodo"][:7])
    eid = to_int(args.get("empleado_id"))
    if eid:
        where.append("p.empleado_id=%s")
        params.append(eid)
    w = " AND ".join(where)
    base = f"""FROM pagos_empleados p JOIN empleados e ON e.id=p.empleado_id LEFT JOIN ubicaciones ub ON ub.id=e.ubicacion_id
               JOIN metodos_pago mp ON mp.id=p.metodo_pago_id WHERE {w}"""
    total = db.scalar(f"SELECT COALESCE(SUM(p.monto),0) {base}", params)
    por_empleado = db.query(f"""SELECT CONCAT(e.apellido, ', ', e.nombre) AS etiqueta, SUM(p.monto) AS total
                                {base} GROUP BY e.id ORDER BY total DESC""", params)
    por_local = db.query(f"""SELECT COALESCE(ub.nombre,'General') AS etiqueta, SUM(p.monto) AS total
                             {base} GROUP BY ub.nombre ORDER BY total DESC""", params)
    por_periodo = db.query(f"""SELECT p.periodo AS etiqueta, SUM(p.monto) AS total {base}
                               GROUP BY p.periodo ORDER BY p.periodo DESC""", params)
    pag = paginar(db.scalar(f"SELECT COUNT(*) {base}", params))
    rows = db.query(f"""SELECT p.*, CONCAT(e.apellido, ', ', e.nombre) AS empleado, ub.nombre AS ubicacion,
                               mp.nombre AS metodo {base} ORDER BY p.fecha DESC LIMIT %s OFFSET %s""",
                    params + [pag.per_page, pag.offset])
    return render_template("empleados/pagos.html", rows=rows, pag=pag, total=total, por_empleado=por_empleado,
                           por_local=por_local, por_periodo=por_periodo, desde=desde, hasta=hasta,
                           ubics=ubicaciones.listar(), empleados=db.query("SELECT id, nombre, apellido FROM empleados ORDER BY apellido"))
