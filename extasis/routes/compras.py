import json
from datetime import date
from decimal import Decimal

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import db
from ..models import catalogos, ubicaciones
from ..services import NegocioError, stock_service
from ..utils.audit import auditar
from ..utils.auth import permiso_required
from ..utils.helpers import clean, hay_filtros, paginar, parse_date, rango_fechas, to_decimal, to_int

bp = Blueprint("compras", __name__, url_prefix="/compras")


@bp.route("/")
@permiso_required("compras.gestionar")
def index():
    args = request.args
    desde, hasta, hasta_ex = rango_fechas(args, 90)
    rows, pag = [], None
    buscado = hay_filtros(args)
    if buscado:
        where, params = ["c.fecha>=%s", "c.fecha<%s"], [desde, hasta_ex]
        prov = to_int(args.get("proveedor_id"))
        if prov:
            where.append("c.proveedor_id=%s")
            params.append(prov)
        q = clean(args.get("q"))
        if q:
            where.append("c.numero_factura LIKE %s")
            params.append(f"%{q}%")
        w = " AND ".join(where)
        pag = paginar(db.scalar(f"SELECT COUNT(*) FROM compras c WHERE {w}", params))
        rows = db.query(f"""SELECT c.*, p.razon_social, u.nombre AS usuario, ub.nombre AS ubicacion, mp.nombre AS metodo,
                                   c.total - c.monto_pagado - COALESCE((SELECT SUM(monto) FROM pagos pa WHERE pa.compra_id=c.id),0) AS saldo
                            FROM compras c JOIN proveedores p ON p.id=c.proveedor_id JOIN usuarios u ON u.id=c.usuario_id
                            JOIN ubicaciones ub ON ub.id=c.ubicacion_id LEFT JOIN metodos_pago mp ON mp.id=c.metodo_pago_id
                            WHERE {w} ORDER BY c.fecha DESC, c.id DESC LIMIT %s OFFSET %s""",
                        params + [pag.per_page, pag.offset])
    provs = db.query("SELECT id, razon_social FROM proveedores ORDER BY razon_social")
    return render_template("compras/index.html", rows=rows, pag=pag, buscado=buscado, desde=desde, hasta=hasta,
                           proveedores=provs)


@bp.route("/nueva", methods=["GET", "POST"])
@permiso_required("compras.gestionar")
def nueva():
    if request.method == "POST":
        f = request.form
        try:
            proveedor_id = to_int(f.get("proveedor_id"))
            ubicacion_id = to_int(f.get("ubicacion_id"))
            fecha = parse_date(f.get("fecha"), date.today())
            metodo = to_int(f.get("metodo_pago_id"))
            pagado = to_decimal(f.get("monto_pagado"))
            actualizar_precio = f.get("actualizar_precio") == "1"
            try:
                items = json.loads(f.get("items") or "[]")
                items = [(int(i["variante_id"]), int(i["cantidad"]), Decimal(str(i["precio"]))) for i in items]
            except (ValueError, KeyError, TypeError, ArithmeticError):
                raise NegocioError("Los productos cargados no son válidos.")
            if not proveedor_id:
                raise NegocioError("Seleccioná el proveedor.")
            if not ubicacion_id:
                raise NegocioError("Seleccioná el depósito que recibe.")
            if not items:
                raise NegocioError("Agregá al menos un producto.")
            if any(c <= 0 or p < 0 for _, c, p in items):
                raise NegocioError("Cantidades y precios deben ser positivos.")
            total = sum((p * c for _, c, p in items), Decimal(0))
            if pagado < 0 or pagado > total:
                raise NegocioError("El monto pagado debe estar entre 0 y el total.")
            with db.transaction() as tx:
                cid = tx.execute(
                    """INSERT INTO compras (proveedor_id, ubicacion_id, numero_factura, fecha, total, metodo_pago_id,
                       monto_pagado, usuario_id, observaciones) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (proveedor_id, ubicacion_id, clean(f.get("numero_factura"), 40), fecha, total,
                     metodo, pagado, g.user["id"], clean(f.get("observaciones"), 255)))
                for vid, cant, precio in items:
                    tx.execute("INSERT INTO detalle_compras (compra_id, variante_id, cantidad, precio_compra) VALUES (%s,%s,%s,%s)",
                               (cid, vid, cant, precio))
                    stock_service.mover(tx, vid, ubicacion_id, cant)
                    stock_service.registrar_movimiento(tx, "COMPRA", vid, cant, g.user["id"], destino_id=ubicacion_id,
                                                       motivo=f"Compra N° {cid}", ref_tipo="compra", ref_id=cid)
                    if actualizar_precio:
                        tx.execute("""UPDATE productos p JOIN variantes_producto v ON v.producto_id=p.id
                                      SET p.precio_compra=%s WHERE v.id=%s""", (precio, vid))
                prov = tx.query("SELECT razon_social FROM proveedores WHERE id=%s", (proveedor_id,), one=True)
                auditar(f"{g.user['nombre']} registró la compra N° {cid} a {prov['razon_social']} por ${total:,.2f}",
                        "compras", cid, tx)
            flash(f"Compra N° {cid} registrada. Stock del depósito actualizado.", "success")
            return redirect(url_for("compras.detalle", cid=cid))
        except NegocioError as e:
            flash(str(e), "danger")
        except db.IntegrityError:
            flash("Ya existe una compra con ese número de factura para el proveedor.", "danger")
    provs = db.query("SELECT id, razon_social FROM proveedores WHERE activo=1 ORDER BY razon_social")
    return render_template("compras/nueva.html", proveedores=provs, depositos=ubicaciones.listar(),
                           deposito=ubicaciones.deposito_central(), metodos=catalogos.metodos_pago(),
                           hoy=date.today().isoformat())


@bp.route("/<int:cid>")
@permiso_required("compras.gestionar")
def detalle(cid):
    c = db.query("""SELECT c.*, p.razon_social, p.cuit, u.nombre AS usuario, ub.nombre AS ubicacion, mp.nombre AS metodo
                    FROM compras c JOIN proveedores p ON p.id=c.proveedor_id JOIN usuarios u ON u.id=c.usuario_id
                    JOIN ubicaciones ub ON ub.id=c.ubicacion_id LEFT JOIN metodos_pago mp ON mp.id=c.metodo_pago_id
                    WHERE c.id=%s""", (cid,), one=True) or abort(404)
    det = db.query("""SELECT d.*, d.cantidad*d.precio_compra AS subtotal, p.nombre AS producto, t.nombre AS talle,
                             co.nombre AS color FROM detalle_compras d JOIN variantes_producto v ON v.id=d.variante_id
                      JOIN productos p ON p.id=v.producto_id JOIN talles t ON t.id=v.talle_id
                      JOIN colores co ON co.id=v.color_id WHERE d.compra_id=%s""", (cid,))
    pagos = db.query("""SELECT pa.*, mp.nombre AS metodo, u.nombre AS usuario FROM pagos pa
                        JOIN metodos_pago mp ON mp.id=pa.metodo_pago_id JOIN usuarios u ON u.id=pa.usuario_id
                        WHERE pa.compra_id=%s ORDER BY pa.fecha""", (cid,))
    saldo = Decimal(c["total"]) - Decimal(c["monto_pagado"]) - sum((Decimal(p["monto"]) for p in pagos), Decimal(0))
    return render_template("compras/detalle.html", c=c, det=det, pagos=pagos, saldo=saldo,
                           metodos=catalogos.metodos_pago(), hoy=date.today().isoformat())
