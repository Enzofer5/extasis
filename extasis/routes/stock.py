import csv
import io

from flask import Blueprint, Response, flash, g, jsonify, redirect, render_template, request, url_for

from .. import db
from ..models import catalogos, productos, ubicaciones
from ..services import NegocioError, stock_service
from ..utils.audit import auditar
from ..utils.auth import admin_required, es_admin, login_required, permiso_required, ubicacion_scope
from ..utils.helpers import clean, hay_filtros, paginar, rango_fechas, to_int

bp = Blueprint("stock", __name__)

TIPOS_MOV = ["ENTRADA", "SALIDA", "VENTA", "DEVOLUCION", "TRANSFERENCIA", "AJUSTE", "COMPRA", "ANULACION"]
NOMBRES_MOV = {"ENTRADA": "Entrada", "SALIDA": "Salida", "VENTA": "Venta", "DEVOLUCION": "Devolución",
               "TRANSFERENCIA": "Envío entre ubicaciones", "AJUSTE": "Ajuste", "COMPRA": "Compra",
               "ANULACION": "Venta anulada"}


def _ubic_permitida(ubicacion_id):
    scope = ubicacion_scope()
    if scope is not None:
        return scope
    return ubicacion_id


@bp.route("/stock")
@permiso_required("stock.ver_local", "stock.ver_todo")
def index():
    args = request.args
    scope = ubicacion_scope()
    ubics = [ubicaciones.get(scope)] if scope else ubicaciones.listar()
    filtro_ub = scope or to_int(args.get("ubicacion_id"))
    rows, pag = [], None
    buscado = hay_filtros(args)
    if buscado:
        where, params = ["p.activo=1", "v.activo=1"], []
        q = clean(args.get("q"))
        if q:
            where.append("(p.nombre LIKE %s OR p.codigo_interno=%s OR v.codigo_barras=%s OR p.codigo_barras=%s)")
            params += [f"%{q}%", q, q, q]
        for campo, col in (("categoria_id", "p.categoria_id"), ("marca_id", "p.marca_id"),
                           ("talle_id", "v.talle_id"), ("color_id", "v.color_id")):
            val = to_int(args.get(campo))
            if val:
                where.append(f"{col}=%s")
                params.append(val)
        if filtro_ub:
            cond_s = "AND s2.ubicacion_id=%s"
        else:
            cond_s = ""
        if args.get("con_stock") == "1":
            where.append(f"EXISTS (SELECT 1 FROM stock s2 WHERE s2.variante_id=v.id AND s2.cantidad>0 {cond_s})")
            if filtro_ub:
                params.append(filtro_ub)
        w = " AND ".join(where)
        base = f"""FROM variantes_producto v JOIN productos p ON p.id=v.producto_id
                   JOIN talles t ON t.id=v.talle_id JOIN colores c ON c.id=v.color_id
                   LEFT JOIN categorias cat ON cat.id=p.categoria_id WHERE {w}"""
        total = db.scalar(f"SELECT COUNT(*) {base}", params)
        pag = paginar(total)
        rows = db.query(f"""SELECT v.id AS variante_id, v.codigo_barras, p.id AS producto_id, p.nombre AS producto,
                                   p.codigo_interno, t.nombre AS talle, c.nombre AS color, c.hex, cat.nombre AS categoria,
                                   p.precio_venta
                            {base} ORDER BY p.nombre, c.nombre, t.orden LIMIT %s OFFSET %s""",
                        params + [pag.per_page, pag.offset])
        if rows:
            ids = [r["variante_id"] for r in rows]
            ph = ",".join(["%s"] * len(ids))
            st = db.query(f"SELECT variante_id, ubicacion_id, cantidad, stock_minimo FROM stock WHERE variante_id IN ({ph})", ids)
            m = {(s["variante_id"], s["ubicacion_id"]): s for s in st}
            for r in rows:
                r["stock"] = {u["id"]: (m.get((r["variante_id"], u["id"])) or {}).get("cantidad", 0) for u in ubics}
                r["minimo"] = {u["id"]: (m.get((r["variante_id"], u["id"])) or {}).get("stock_minimo", 0) for u in ubics}
                r["total"] = sum(r["stock"].values())
    if filtro_ub and not scope:
        ubics_vista = [u for u in ubics if u["id"] == filtro_ub]
    else:
        ubics_vista = ubics
    return render_template("stock/index.html", rows=rows, pag=pag, buscado=buscado, ubics=ubics,
                           ubics_vista=ubics_vista, categorias=catalogos.categorias_principales(),
                           marcas=catalogos.listar("marcas"), talles=catalogos.listar("talles"),
                           colores=catalogos.listar("colores"))


@bp.route("/stock/bajo")
@permiso_required("stock.ver_local", "stock.ver_todo")
def bajo_stock():
    scope = ubicacion_scope()
    filtro_ub = scope or to_int(request.args.get("ubicacion_id"))
    sql = """SELECT p.id AS producto_id, p.nombre AS producto, t.nombre AS talle, c.nombre AS color, v.codigo_barras,
                    ub.nombre AS ubicacion, ub.id AS ubicacion_id, s.cantidad, s.stock_minimo, v.id AS variante_id
             FROM stock s JOIN variantes_producto v ON v.id=s.variante_id JOIN productos p ON p.id=v.producto_id
             JOIN talles t ON t.id=v.talle_id JOIN colores c ON c.id=v.color_id JOIN ubicaciones ub ON ub.id=s.ubicacion_id
             WHERE p.activo=1 AND v.activo=1 AND s.cantidad<=s.stock_minimo"""
    params = []
    if filtro_ub:
        sql += " AND s.ubicacion_id=%s"
        params.append(filtro_ub)
    sql += " ORDER BY s.cantidad, ub.id, p.nombre LIMIT 500"
    rows = db.query(sql, params)
    return render_template("stock/bajo.html", rows=rows, ubics=ubicaciones.listar() if not scope else [],
                           filtro_ub=filtro_ub)


@bp.route("/stock/movimientos")
@permiso_required("stock.ver_local", "stock.ver_todo")
def movimientos():
    args = request.args
    scope = ubicacion_scope()
    rows, pag = [], None
    buscado = hay_filtros(args)
    desde, hasta, hasta_ex = rango_fechas(args, 30)
    if buscado:
        where, params = ["m.fecha>=%s", "m.fecha<%s"], [desde, hasta_ex]
        ub = scope or to_int(args.get("ubicacion_id"))
        if ub:
            where.append("(m.origen_id=%s OR m.destino_id=%s)")
            params += [ub, ub]
        if args.get("tipo") in TIPOS_MOV:
            where.append("m.tipo=%s")
            params.append(args["tipo"])
        q = clean(args.get("q"))
        if q:
            where.append("(p.nombre LIKE %s OR v.codigo_barras=%s OR p.codigo_interno=%s)")
            params += [f"%{q}%", q, q]
        w = " AND ".join(where)
        base = f"""FROM movimientos_stock m JOIN variantes_producto v ON v.id=m.variante_id
                   JOIN productos p ON p.id=v.producto_id JOIN talles t ON t.id=v.talle_id
                   JOIN colores c ON c.id=v.color_id JOIN usuarios u ON u.id=m.usuario_id
                   LEFT JOIN ubicaciones uo ON uo.id=m.origen_id LEFT JOIN ubicaciones ud ON ud.id=m.destino_id
                   WHERE {w}"""
        columnas = f"""SELECT m.*, p.nombre AS producto, p.codigo_interno, t.nombre AS talle, c.nombre AS color,
                              u.nombre AS usuario, uo.nombre AS origen, ud.nombre AS destino
                       {base} ORDER BY m.fecha DESC, m.id DESC"""
        if args.get("csv") == "1":
            out = io.StringIO()
            w = csv.writer(out, delimiter=";")
            w.writerow(["Fecha", "Tipo", "Producto", "Código", "Talle", "Color", "Cantidad", "Origen", "Destino",
                        "Usuario", "Motivo"])
            for m in db.query(columnas, params):
                w.writerow([m["fecha"].strftime("%d/%m/%Y %H:%M"), NOMBRES_MOV.get(m["tipo"], m["tipo"]), m["producto"],
                            m["codigo_interno"] or "", m["talle"], m["color"], m["cantidad"], m["origen"] or "",
                            m["destino"] or "", m["usuario"], m["motivo"] or ""])
            return Response("﻿" + out.getvalue(), mimetype="text/csv",
                            headers={"Content-Disposition": f"attachment; filename=movimientos_{desde}_{hasta}.csv"})
        pag = paginar(db.scalar(f"SELECT COUNT(*) {base}", params))
        rows = db.query(columnas + " LIMIT %s OFFSET %s", params + [pag.per_page, pag.offset])
    return render_template("stock/movimientos.html", rows=rows, pag=pag, buscado=buscado, tipos=TIPOS_MOV,
                           nombres=NOMBRES_MOV,
                           ubics=ubicaciones.listar(solo_activas=False) if not scope else [], desde=desde, hasta=hasta)


@bp.route("/stock/ajuste", methods=["GET", "POST"])
@admin_required
def ajuste():
    """Entradas, salidas y ajustes manuales de stock en cualquier ubicación."""
    if request.method == "POST":
        variante_id = to_int(request.form.get("variante_id"))
        ubicacion_id = to_int(request.form.get("ubicacion_id"))
        tipo = request.form.get("tipo")
        cantidad = to_int(request.form.get("cantidad"), -1)
        motivo = clean(request.form.get("motivo"), 255)
        try:
            if not variante_id or not ubicacion_id:
                raise NegocioError("Seleccioná el producto/variante y la ubicación.")
            if tipo not in ("ENTRADA", "SALIDA", "AJUSTE") or cantidad < 0:
                raise NegocioError("Datos inválidos.")
            if not motivo:
                raise NegocioError("El motivo es obligatorio.")
            with db.transaction() as tx:
                et = stock_service.etiqueta_variante(tx, variante_id)
                if tipo == "ENTRADA":
                    if cantidad == 0:
                        raise NegocioError("La cantidad debe ser mayor a cero.")
                    stock_service.mover(tx, variante_id, ubicacion_id, cantidad)
                    stock_service.registrar_movimiento(tx, "ENTRADA", variante_id, cantidad, g.user["id"],
                                                       destino_id=ubicacion_id, motivo=motivo)
                    diff = cantidad
                elif tipo == "SALIDA":
                    if cantidad == 0:
                        raise NegocioError("La cantidad debe ser mayor a cero.")
                    stock_service.mover(tx, variante_id, ubicacion_id, -cantidad, etiqueta=et)
                    stock_service.registrar_movimiento(tx, "SALIDA", variante_id, cantidad, g.user["id"],
                                                       origen_id=ubicacion_id, motivo=motivo)
                    diff = -cantidad
                else:
                    diff = stock_service.establecer(tx, variante_id, ubicacion_id, cantidad)
                    stock_service.registrar_movimiento(tx, "AJUSTE", variante_id, diff, g.user["id"],
                                                       origen_id=ubicacion_id if diff < 0 else None,
                                                       destino_id=ubicacion_id if diff >= 0 else None,
                                                       motivo=f"Ajuste a {cantidad} u.: {motivo}")
                ub = tx.query("SELECT nombre FROM ubicaciones WHERE id=%s", (ubicacion_id,), one=True)
                auditar(f"{g.user['nombre']} registró {tipo.lower()} de stock ({diff:+d}) de {et} en {ub['nombre']}",
                        "stock", variante_id, tx)
            flash(f"Movimiento registrado ({diff:+d} unidades).", "success")
            return redirect(url_for("stock.ajuste"))
        except NegocioError as e:
            flash(str(e), "danger")
    return render_template("stock/ajuste.html", ubics=ubicaciones.listar(),
                           deposito=ubicaciones.deposito_central())


# ------------------------------------------------------------------ API
@bp.route("/api/variantes/buscar")
@login_required
def api_buscar():
    ub = _ubic_permitida(to_int(request.args.get("ubicacion_id")))
    rows = productos.buscar_variantes(request.args.get("q"), ub, limit=30)
    return jsonify([_variante_json(r) for r in rows])


@bp.route("/api/variantes/codigo")
@login_required
def api_codigo():
    ub = _ubic_permitida(to_int(request.args.get("ubicacion_id")))
    rows = productos.variantes_por_codigo(request.args.get("codigo"), ub)
    return jsonify([_variante_json(r) for r in rows])


def _variante_json(r):
    return {
        "variante_id": r["variante_id"], "producto_id": r["producto_id"], "producto": r["producto"],
        "talle": r["talle"], "color": r["color"], "color_hex": r.get("color_hex"),
        "codigo_barras": r["codigo_barras"], "codigo_interno": r["codigo_interno"],
        "precio": float(r["precio_venta"]), "costo": float(r["precio_compra"]) if es_admin() else None,
        "stock": int(r.get("stock") or 0), "marca": r.get("marca"),
        "imagen": url_for("static", filename=f"uploads/{r['imagen']}") if r.get("imagen") else None,
    }
