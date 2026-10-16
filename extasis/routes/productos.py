import os
import uuid

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from .. import db
from ..models import catalogos, configuracion, productos, ubicaciones
from ..utils.audit import auditar
from ..utils.auth import admin_required, es_admin, permiso_required, ubicacion_scope
from ..utils.helpers import allowed_image, clean, ean13_check_digit, hay_filtros, paginar, to_decimal, to_int

bp = Blueprint("productos", __name__, url_prefix="/productos")

GENEROS = ["Hombre", "Mujer", "Unisex", "Niño", "Niña"]


def _filtros_ctx():
    return {
        "marcas": catalogos.listar("marcas"),
        "categorias": catalogos.categorias_principales(),
        "subcategorias": catalogos.subcategorias(),
        "temporadas": catalogos.listar("temporadas"),
        "talles": catalogos.listar("talles"),
        "colores": catalogos.listar("colores"),
        "generos": GENEROS,
    }


@bp.route("/")
@permiso_required("productos.ver")
def index():
    args = request.args
    rows, pag = [], None
    buscado = hay_filtros(args)
    scope = ubicacion_scope()
    if buscado:
        where, params = ["1=1"], []
        q = clean(args.get("q"))
        if q:
            where.append("""(p.nombre LIKE %s OR p.codigo_interno=%s OR p.codigo_barras=%s
                             OR EXISTS (SELECT 1 FROM variantes_producto v2 WHERE v2.producto_id=p.id AND v2.codigo_barras=%s))""")
            params += [f"%{q}%", q, q, q]
        for campo, col in (("marca_id", "p.marca_id"), ("categoria_id", "p.categoria_id"),
                           ("temporada_id", "p.temporada_id")):
            val = to_int(args.get(campo))
            if val:
                where.append(f"{col}=%s")
                params.append(val)
        if args.get("genero") in GENEROS:
            where.append("p.genero=%s")
            params.append(args["genero"])
        for campo, col in (("talle_id", "talle_id"), ("color_id", "color_id")):
            val = to_int(args.get(campo))
            if val:
                where.append(f"EXISTS (SELECT 1 FROM variantes_producto v3 WHERE v3.producto_id=p.id AND v3.{col}=%s)")
                params.append(val)
        estado = args.get("estado", "1" if not es_admin() else "")
        if not es_admin():
            estado = "1"
        if estado in ("0", "1"):
            where.append("p.activo=%s")
            params.append(int(estado))
        w = " AND ".join(where)
        total = db.scalar(f"SELECT COUNT(*) FROM productos p WHERE {w}", params)
        pag = paginar(total)
        if scope:
            stock_expr = """COALESCE((SELECT SUM(s.cantidad) FROM stock s JOIN variantes_producto v ON v.id=s.variante_id
                             WHERE v.producto_id=p.id AND s.ubicacion_id=%s),0)"""
            sp = [scope]
        else:
            stock_expr = """COALESCE((SELECT SUM(s.cantidad) FROM stock s JOIN variantes_producto v ON v.id=s.variante_id
                             WHERE v.producto_id=p.id),0)"""
            sp = []
        rows = db.query(
            f"""SELECT p.*, m.nombre AS marca, c.nombre AS categoria, {stock_expr} AS stock,
                       (SELECT COUNT(*) FROM variantes_producto v WHERE v.producto_id=p.id AND v.activo=1) AS n_variantes
                FROM productos p LEFT JOIN marcas m ON m.id=p.marca_id LEFT JOIN categorias c ON c.id=p.categoria_id
                WHERE {w} ORDER BY p.nombre LIMIT %s OFFSET %s""", sp + params + [pag.per_page, pag.offset])
    return render_template("productos/index.html", rows=rows, pag=pag, buscado=buscado, **_filtros_ctx())


def _guardar_imagen(file):
    if not file or not file.filename:
        return None
    if not allowed_image(file.filename):
        raise ValueError("Formato de imagen no permitido (usá JPG, PNG o WEBP).")
    ext = secure_filename(file.filename).rsplit(".", 1)[-1].lower()
    nombre = f"prod_{uuid.uuid4().hex[:12]}.{ext}"
    file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], nombre))
    return nombre


def generar_codigo_variante(variante_id):
    prefijo = (configuracion.get("prefijo_codigo_barras", "200") or "200")[:3].ljust(3, "0")
    base = f"{prefijo}{int(variante_id):09d}"
    return base + ean13_check_digit(base)


def crear_variantes(tx, producto_id, talles_ids, colores_ids):
    creadas = 0
    for t in talles_ids:
        for c in colores_ids:
            existe = tx.query("SELECT id, activo FROM variantes_producto WHERE producto_id=%s AND talle_id=%s AND color_id=%s",
                              (producto_id, t, c), one=True)
            if existe:
                if not existe["activo"]:
                    tx.execute("UPDATE variantes_producto SET activo=1 WHERE id=%s", (existe["id"],))
                continue
            vid = tx.execute("INSERT INTO variantes_producto (producto_id, talle_id, color_id, codigo_barras) VALUES (%s,%s,%s,%s)",
                             (producto_id, t, c, f"TMP-{uuid.uuid4().hex[:20]}"))
            tx.execute("UPDATE variantes_producto SET codigo_barras=%s WHERE id=%s", (generar_codigo_variante(vid), vid))
            creadas += 1
    return creadas


def _datos_form(form):
    nombre = clean(form.get("nombre"), 150)
    if not nombre:
        raise ValueError("El nombre es obligatorio.")
    pc = to_decimal(form.get("precio_compra"))
    pv = to_decimal(form.get("precio_venta"))
    if pc < 0 or pv < 0:
        raise ValueError("Los precios no pueden ser negativos.")
    genero = form.get("genero") if form.get("genero") in GENEROS else "Unisex"
    return {
        "codigo_interno": clean(form.get("codigo_interno"), 30),
        "codigo_barras": clean(form.get("codigo_barras"), 40),
        "nombre": nombre,
        "marca_id": to_int(form.get("marca_id")),
        "categoria_id": to_int(form.get("categoria_id")),
        "subcategoria_id": to_int(form.get("subcategoria_id")),
        "descripcion": clean(form.get("descripcion"), 2000),
        "precio_compra": pc, "precio_venta": pv,
        "temporada_id": to_int(form.get("temporada_id")),  # ya no se pide en el formulario
        "genero": genero,
    }


@bp.route("/nuevo", methods=["GET", "POST"])
@admin_required
def nuevo():
    if request.method == "GET":
        return redirect(url_for("productos.carga"))
    if request.method == "POST":
        try:
            d = _datos_form(request.form)
            d["codigo_interno"] = d["codigo_interno"] or productos.siguiente_codigo_interno()
            talles_ids = [int(x) for x in request.form.getlist("talles")] or [1]
            colores_ids = [int(x) for x in request.form.getlist("colores")] or [1]
            imagen = _guardar_imagen(request.files.get("imagen"))
            with db.transaction() as tx:
                pid = tx.execute(
                    """INSERT INTO productos (codigo_interno, codigo_barras, nombre, marca_id, categoria_id, subcategoria_id,
                       descripcion, precio_compra, precio_venta, imagen, temporada_id, genero)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (d["codigo_interno"], d["codigo_barras"], d["nombre"], d["marca_id"], d["categoria_id"],
                     d["subcategoria_id"], d["descripcion"], d["precio_compra"], d["precio_venta"], imagen,
                     d["temporada_id"], d["genero"]))
                n = crear_variantes(tx, pid, talles_ids, colores_ids)
                auditar(f"{g.user['nombre']} creó el producto {d['nombre']} con {n} variantes", "productos", pid, tx)
            flash(f"Producto creado con {n} variantes.", "success")
            return redirect(url_for("productos.detalle", producto_id=pid))
        except ValueError as e:
            flash(str(e), "danger")
        except db.IntegrityError:
            flash("Ya existe un producto con ese código interno o código de barras.", "danger")
    return render_template("productos/form.html", p=None, sugerido=productos.siguiente_codigo_interno(),
                           variantes=[], **_filtros_ctx())


@bp.route("/<int:producto_id>/editar", methods=["GET", "POST"])
@admin_required
def editar(producto_id):
    p = productos.get(producto_id) or abort(404)
    if request.method == "POST":
        try:
            d = _datos_form(request.form)
            d["temporada_id"] = d["temporada_id"] or p["temporada_id"]
            d["codigo_interno"] = d["codigo_interno"] or p["codigo_interno"]
            imagen = _guardar_imagen(request.files.get("imagen")) or p["imagen"]
            talles_ids = [int(x) for x in request.form.getlist("talles")]
            colores_ids = [int(x) for x in request.form.getlist("colores")]
            with db.transaction() as tx:
                tx.execute(
                    """UPDATE productos SET codigo_interno=%s, codigo_barras=%s, nombre=%s, marca_id=%s, categoria_id=%s,
                       subcategoria_id=%s, descripcion=%s, precio_compra=%s, precio_venta=%s, imagen=%s, temporada_id=%s,
                       genero=%s WHERE id=%s""",
                    (d["codigo_interno"], d["codigo_barras"], d["nombre"], d["marca_id"], d["categoria_id"],
                     d["subcategoria_id"], d["descripcion"], d["precio_compra"], d["precio_venta"], imagen,
                     d["temporada_id"], d["genero"], producto_id))
                n = crear_variantes(tx, producto_id, talles_ids, colores_ids) if talles_ids and colores_ids else 0
                cambios = []
                if d["precio_venta"] != p["precio_venta"]:
                    cambios.append(f"precio de venta ${p['precio_venta']} → ${d['precio_venta']}")
                if d["precio_compra"] != p["precio_compra"]:
                    cambios.append(f"precio de compra ${p['precio_compra']} → ${d['precio_compra']}")
                txt = f"{g.user['nombre']} modificó el producto {d['nombre']}"
                if cambios:
                    txt += " (" + "; ".join(cambios) + ")"
                auditar(txt, "productos", producto_id, tx)
            flash("Producto actualizado." + (f" Se agregaron {n} variantes." if n else ""), "success")
            return redirect(url_for("productos.detalle", producto_id=producto_id))
        except ValueError as e:
            flash(str(e), "danger")
        except db.IntegrityError:
            flash("Código interno o código de barras duplicado.", "danger")
    return render_template("productos/form.html", p=p, variantes=productos.variantes(producto_id), **_filtros_ctx())


@bp.route("/<int:producto_id>")
@permiso_required("productos.ver")
def detalle(producto_id):
    p = productos.get(producto_id) or abort(404)
    scope = ubicacion_scope()
    if not p["activo"] and scope:
        abort(404)
    variantes = productos.variantes(producto_id, solo_activas=bool(scope))
    ubics = [ubicaciones.get(scope)] if scope else ubicaciones.listar()
    stock_rows = productos.stock_por_ubicacion(producto_id, scope)
    matriz = {(r["variante_id"], r["ubicacion_id"]): r["cantidad"] for r in stock_rows}
    for v in variantes:
        v["stock"] = {u["id"]: matriz.get((v["variante_id"], u["id"]), 0) for u in ubics}
        v["total"] = sum(v["stock"].values())
    totales = {u["id"]: sum(v["stock"][u["id"]] for v in variantes) for u in ubics}
    return render_template("productos/detalle.html", p=p, variantes=variantes, ubics=ubics, totales=totales,
                           total_general=sum(totales.values()))


@bp.route("/<int:producto_id>/estado", methods=["POST"])
@admin_required
def cambiar_estado(producto_id):
    p = productos.get(producto_id) or abort(404)
    nuevo_estado = 0 if p["activo"] else 1
    db.execute("UPDATE productos SET activo=%s WHERE id=%s", (nuevo_estado, producto_id))
    auditar(f"{g.user['nombre']} {'activó' if nuevo_estado else 'desactivó'} el producto {p['nombre']}", "productos", producto_id)
    flash("Producto " + ("activado." if nuevo_estado else "desactivado."), "success")
    return redirect(url_for("productos.detalle", producto_id=producto_id))


@bp.route("/variante/<int:variante_id>", methods=["POST"])
@admin_required
def editar_variante(variante_id):
    v = productos.get_variante(variante_id) or abort(404)
    accion = request.form.get("accion")
    if accion == "estado":
        db.execute("UPDATE variantes_producto SET activo=1-activo WHERE id=%s", (variante_id,))
        flash("Variante actualizada.", "success")
    elif accion == "codigo":
        codigo = clean(request.form.get("codigo_barras"), 40)
        if not codigo:
            flash("El código no puede quedar vacío.", "danger")
        else:
            try:
                db.execute("UPDATE variantes_producto SET codigo_barras=%s WHERE id=%s", (codigo, variante_id))
                auditar(f"{g.user['nombre']} cambió el código de barras de {v['producto']} T.{v['talle']} a {codigo}",
                        "productos", v["producto_id"])
                flash("Código de barras actualizado.", "success")
            except db.IntegrityError:
                flash("Ese código de barras ya está asignado a otra variante.", "danger")
    elif accion == "minimo":
        minimo = max(0, to_int(request.form.get("stock_minimo"), 0))
        db.execute("UPDATE stock SET stock_minimo=%s WHERE variante_id=%s", (minimo, variante_id))
        flash("Stock mínimo actualizado en todas las ubicaciones.", "success")
    return redirect(url_for("productos.detalle", producto_id=v["producto_id"]))


@bp.route("/<int:producto_id>/etiquetas")
@permiso_required("productos.ver")
def etiquetas(producto_id):
    p = productos.get(producto_id) or abort(404)
    variantes = productos.variantes(producto_id, solo_activas=True)
    cant = max(1, min(50, to_int(request.args.get("cant"), 1)))
    return render_template("productos/etiquetas.html", p=p, variantes=variantes, cant=cant)


# ------------------------------------------------------------------ carga rápida (varios productos a la vez)
TALLES_PRESET = {
    "Letras (S a XL)": "S, M, L, XL",
    "Letras (XS a XXL)": "XS, S, M, L, XL, XXL",
    "Jeans (36 a 46)": "36, 38, 40, 42, 44, 46",
    "Calzado (35 a 44)": "35, 36, 37, 38, 39, 40, 41, 42, 43, 44",
    "Talle único": "Único",
}


def _buscar_o_crear(tx, tabla, nombre, extra_sql="", extra_vals=()):
    """Busca por nombre (sin distinguir mayúsculas) y si no existe lo crea. Devuelve el id."""
    nombre = (nombre or "").strip()[:80]
    if not nombre:
        return None
    if tabla == "categorias":
        row = tx.query("SELECT id, activo FROM categorias WHERE LOWER(nombre)=LOWER(%s) AND parent_id IS NULL", (nombre,), one=True)
    else:
        row = tx.query(f"SELECT id, activo FROM {tabla} WHERE LOWER(nombre)=LOWER(%s)", (nombre,), one=True)
    if row:
        if not row["activo"]:
            tx.execute(f"UPDATE {tabla} SET activo=1 WHERE id=%s", (row["id"],))
        return row["id"]
    if tabla == "talles":
        orden = int(nombre) + 100 if nombre.isdigit() else {"XXS": 5, "XS": 10, "S": 20, "M": 30, "L": 40, "XL": 50,
                                                             "XXL": 60, "XXXL": 70}.get(nombre.upper(), 900)
        if nombre.upper() in ("XS", "S", "M", "L", "XL", "XXL", "XXXL", "XXS"):
            nombre = nombre.upper()
        return tx.execute("INSERT INTO talles (nombre, orden) VALUES (%s,%s)", (nombre, orden))
    nombre = nombre[:1].upper() + nombre[1:]
    return tx.execute(f"INSERT INTO {tabla} (nombre) VALUES (%s)", (nombre,))


def _separar_talles(txt):
    import re

    def rango(m):  # "38-42" / "38 al 42" / "38 a 42" -> 38 39 40 41 42
        a, b = int(m.group(1)), int(m.group(2))
        return " ".join(str(n) for n in range(a, b + 1)) if a < b <= a + 30 else m.group(0)
    txt = re.sub(r"(\d+)\s*(?:-|al|a)\s*(\d+)", rango, txt or "", flags=re.I)
    partes = [t.strip() for t in re.split(r"[,;/]|\s+", txt) if t.strip()]
    vistos, res = set(), []
    for t in partes:
        if t.lower() not in vistos:
            vistos.add(t.lower())
            res.append(t)
    return res or ["Único"]


@bp.route("/carga", methods=["GET", "POST"])
@admin_required
def carga():
    import json
    from ..services import stock_service
    from ..models import ubicaciones as ubic
    if request.method == "POST":
        try:
            filas = json.loads(request.form.get("filas") or "[]")
        except ValueError:
            filas = []
        filas = [f for f in filas if (f.get("nombre") or "").strip()]
        if not filas:
            flash("Cargá al menos un producto con nombre.", "danger")
            return redirect(url_for("productos.carga"))
        deposito = ubic.deposito_central()
        creados, ampliados, variantes_n, unidades = [], [], 0, 0
        try:
            with db.transaction() as tx:
                grupos = {}
                for i, f in enumerate(filas, start=1):
                    nombre = clean(f.get("nombre"), 150)
                    precio = to_decimal(f.get("precio_venta"), None)
                    costo = to_decimal(f.get("precio_compra"))
                    if precio is None or precio <= 0:
                        raise ValueError(f"Fila {i} ({nombre}): falta el precio de venta.")
                    if costo < 0:
                        raise ValueError(f"Fila {i} ({nombre}): el precio de compra no puede ser negativo.")
                    clave = (nombre.lower(), (f.get("marca") or "").strip().lower())
                    grupos.setdefault(clave, []).append(f)

                for (_, _), lista in grupos.items():
                    f0 = lista[0]
                    nombre = clean(f0.get("nombre"), 150)
                    marca_id = _buscar_o_crear(tx, "marcas", f0.get("marca"))
                    cat_id = _buscar_o_crear(tx, "categorias", f0.get("categoria"))
                    genero = f0.get("genero") if f0.get("genero") in GENEROS else "Unisex"
                    existente = tx.query("""SELECT id FROM productos WHERE LOWER(nombre)=LOWER(%s)
                                            AND (marca_id <=> %s)""", (nombre, marca_id), one=True)
                    if existente:
                        pid = existente["id"]
                        ampliados.append(pid)
                    else:
                        pid = tx.execute(
                            """INSERT INTO productos (codigo_interno, nombre, marca_id, categoria_id, precio_compra, precio_venta, genero)
                               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                            (f"TMP-{uuid.uuid4().hex[:20]}", nombre, marca_id, cat_id, to_decimal(f0.get("precio_compra")),
                             to_decimal(f0.get("precio_venta")), genero))
                        codigo = f"EXT-{pid:05d}"
                        if tx.scalar("SELECT COUNT(*) FROM productos WHERE codigo_interno=%s", (codigo,)):
                            codigo = f"EXT-{pid:05d}-{uuid.uuid4().hex[:3].upper()}"
                        tx.execute("UPDATE productos SET codigo_interno=%s WHERE id=%s", (codigo, pid))
                        creados.append(pid)
                    for f in lista:
                        color_id = _buscar_o_crear(tx, "colores", f.get("color") or "Único")
                        talle_ids = [_buscar_o_crear(tx, "talles", t) for t in _separar_talles(f.get("talles"))]
                        variantes_n += crear_variantes(tx, pid, talle_ids, [color_id])
                        cant = max(0, to_int(f.get("stock"), 0))
                        if cant and deposito:
                            for t in talle_ids:
                                vid = tx.scalar("""SELECT id FROM variantes_producto WHERE producto_id=%s AND talle_id=%s
                                                   AND color_id=%s""", (pid, t, color_id))
                                stock_service.mover(tx, vid, deposito["id"], cant)
                                stock_service.registrar_movimiento(tx, "ENTRADA", vid, cant, g.user["id"],
                                                                   destino_id=deposito["id"], motivo="Carga inicial del producto")
                                unidades += cant
                auditar(f"{g.user['nombre']} cargó {len(creados)} productos nuevos ({variantes_n} variantes, {unidades} prendas al depósito)",
                        "productos", None, tx)
        except ValueError as e:
            flash(str(e), "danger")
            return render_template("productos/carga.html", filas_json=json.dumps(filas), **_carga_ctx())
        msg = f"Listo: {len(creados)} productos nuevos, {variantes_n} combinaciones talle/color con su código de barras"
        if unidades:
            msg += f" y {unidades} prendas cargadas al depósito"
        if ampliados:
            msg += f". {len(ampliados)} ya existían y se les agregaron los talles/colores nuevos"
        flash(msg + ".", "success")
        ids = ",".join(str(i) for i in creados + ampliados)
        return redirect(url_for("productos.etiquetas_masivas", ids=ids))
    return render_template("productos/carga.html", filas_json="[]", **_carga_ctx())


def _carga_ctx():
    from ..models import ubicaciones as ubic
    return {
        "marcas": catalogos.listar("marcas"), "categorias": catalogos.categorias_principales(),
        "talles": catalogos.listar("talles"), "colores": catalogos.listar("colores"), "generos": GENEROS,
        "presets": TALLES_PRESET, "deposito": ubic.deposito_central(),
    }


# ------------------------------------------------------------------ etiquetas de varios productos
@bp.route("/etiquetas", methods=["GET", "POST"])
@permiso_required("productos.ver")
def etiquetas_masivas():
    from ..models import ubicaciones as ubic
    scope = ubicacion_scope()
    if request.method == "POST":
        ids = [int(x) for x in request.form.getlist("producto_id") if x.isdigit()]
        modo = request.form.get("modo", "fijo")
        cant = max(1, min(50, to_int(request.form.get("cant"), 1)))
        ub = scope or to_int(request.form.get("ubicacion_id"))
        if not ids:
            flash("Elegí al menos un producto.", "warning")
            return redirect(url_for("productos.etiquetas_masivas"))
        ph = ",".join(["%s"] * len(ids))
        filas = db.query(f"""SELECT v.id, v.codigo_barras, p.nombre AS producto, p.precio_venta, t.nombre AS talle, c.nombre AS color,
                                    COALESCE((SELECT SUM(s.cantidad) FROM stock s WHERE s.variante_id=v.id
                                              {'AND s.ubicacion_id=%s' if ub else ''}),0) AS stock
                             FROM variantes_producto v JOIN productos p ON p.id=v.producto_id
                             JOIN talles t ON t.id=v.talle_id JOIN colores c ON c.id=v.color_id
                             WHERE v.activo=1 AND p.id IN ({ph}) ORDER BY p.nombre, c.nombre, t.orden""",
                         ([ub] if ub else []) + ids)
        etiquetas = []
        for f in filas:
            n = max(0, int(f["stock"])) if modo == "stock" else cant
            etiquetas += [f] * min(n, 200)
        if not etiquetas:
            flash("No hay etiquetas para imprimir (¿los productos no tienen stock?).", "warning")
            return redirect(url_for("productos.etiquetas_masivas"))
        return render_template("productos/etiquetas_lote.html", etiquetas=etiquetas)
    q = clean(request.args.get("q"))
    preseleccion = {int(x) for x in (request.args.get("ids") or "").split(",") if x.isdigit()}
    where, params = ["p.activo=1"], []
    if q:
        where.append("(p.nombre LIKE %s OR p.codigo_interno=%s)")
        params += [f"%{q}%", q]
    cat = to_int(request.args.get("categoria_id"))
    if cat:
        where.append("p.categoria_id=%s")
        params.append(cat)
    prods = db.query(f"""SELECT p.id, p.nombre, p.codigo_interno, p.precio_venta, m.nombre AS marca, c.nombre AS categoria,
                                (SELECT COUNT(*) FROM variantes_producto v WHERE v.producto_id=p.id AND v.activo=1) AS n_var,
                                p.creado_en
                         FROM productos p LEFT JOIN marcas m ON m.id=p.marca_id LEFT JOIN categorias c ON c.id=p.categoria_id
                         WHERE {' AND '.join(where)} ORDER BY p.creado_en DESC, p.nombre LIMIT 500""", params)
    return render_template("productos/etiquetas_masivas.html", prods=prods, preseleccion=preseleccion,
                           categorias=catalogos.categorias_principales(),
                           ubics=ubic.listar() if not scope else [])
