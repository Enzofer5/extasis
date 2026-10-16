"""Productos, variantes (producto + talle + color) y consultas de stock."""
from .. import db

VARIANTE_SELECT = """
    SELECT v.id AS variante_id, v.codigo_barras, v.activo AS variante_activa,
           p.id AS producto_id, p.nombre AS producto, p.codigo_interno, p.precio_venta, p.precio_compra,
           p.imagen, p.activo AS producto_activo,
           t.id AS talle_id, t.nombre AS talle, t.orden AS talle_orden,
           c.id AS color_id, c.nombre AS color, c.hex AS color_hex,
           m.nombre AS marca, cat.nombre AS categoria
    FROM variantes_producto v
    JOIN productos p ON p.id = v.producto_id
    JOIN talles t ON t.id = v.talle_id
    JOIN colores c ON c.id = v.color_id
    LEFT JOIN marcas m ON m.id = p.marca_id
    LEFT JOIN categorias cat ON cat.id = p.categoria_id
"""


def get(producto_id):
    return db.query(
        """SELECT p.*, m.nombre AS marca, c.nombre AS categoria, sc.nombre AS subcategoria,
                  t.nombre AS temporada
           FROM productos p
           LEFT JOIN marcas m ON m.id=p.marca_id
           LEFT JOIN categorias c ON c.id=p.categoria_id
           LEFT JOIN categorias sc ON sc.id=p.subcategoria_id
           LEFT JOIN temporadas t ON t.id=p.temporada_id
           WHERE p.id=%s""", (producto_id,), one=True)


def variantes(producto_id, solo_activas=False):
    sql = VARIANTE_SELECT + " WHERE v.producto_id=%s"
    if solo_activas:
        sql += " AND v.activo=1"
    sql += " ORDER BY c.nombre, t.orden"
    return db.query(sql, (producto_id,))


def get_variante(variante_id):
    return db.query(VARIANTE_SELECT + " WHERE v.id=%s", (variante_id,), one=True)


def stock_por_ubicacion(producto_id, ubicacion_id=None):
    """Matriz variante x ubicación para el detalle del producto."""
    sql = """SELECT s.variante_id, s.ubicacion_id, s.cantidad, s.stock_minimo
             FROM stock s JOIN variantes_producto v ON v.id=s.variante_id
             WHERE v.producto_id=%s"""
    params = [producto_id]
    if ubicacion_id:
        sql += " AND s.ubicacion_id=%s"
        params.append(ubicacion_id)
    return db.query(sql, params)


def _stock_expr(ubicacion_id):
    if ubicacion_id:
        return ("COALESCE((SELECT s.cantidad FROM stock s WHERE s.variante_id=v.id AND s.ubicacion_id=%s),0)",
                [ubicacion_id])
    return ("COALESCE((SELECT SUM(s.cantidad) FROM stock s WHERE s.variante_id=v.id),0)", [])


def buscar_variantes(term, ubicacion_id=None, limit=25, solo_activos=True):
    """Búsqueda para POS / transferencias / compras por código o nombre."""
    term = (term or "").strip()
    if not term:
        return []
    expr, p_expr = _stock_expr(ubicacion_id)
    sql = VARIANTE_SELECT.replace("SELECT v.id AS variante_id", f"SELECT {expr} AS stock, v.id AS variante_id", 1)
    sql += " WHERE (v.codigo_barras=%s OR p.codigo_barras=%s OR p.codigo_interno=%s OR p.nombre LIKE %s OR m.nombre LIKE %s)"
    params = p_expr + [term, term, term, f"%{term}%", f"%{term}%"]
    if solo_activos:
        sql += " AND v.activo=1 AND p.activo=1"
    sql += " ORDER BY (v.codigo_barras=%s) DESC, p.nombre, c.nombre, t.orden LIMIT %s"
    params += [term, limit]
    return db.query(sql, params)


def variantes_por_codigo(codigo, ubicacion_id=None):
    """Código escaneado: primero código de variante; si no, código del producto (todas sus variantes)."""
    codigo = (codigo or "").strip()
    if not codigo:
        return []
    expr, p_expr = _stock_expr(ubicacion_id)
    base = VARIANTE_SELECT.replace("SELECT v.id AS variante_id", f"SELECT {expr} AS stock, v.id AS variante_id", 1)
    rows = db.query(base + " WHERE v.codigo_barras=%s AND v.activo=1 AND p.activo=1", p_expr + [codigo])
    if rows:
        return rows
    return db.query(base + " WHERE (p.codigo_barras=%s OR p.codigo_interno=%s) AND v.activo=1 AND p.activo=1"
                    " ORDER BY c.nombre, t.orden", p_expr + [codigo, codigo])


def siguiente_codigo_interno():
    n = db.scalar("SELECT COALESCE(MAX(id),0)+1 AS n FROM productos")
    return f"EXT-{int(n):05d}"
