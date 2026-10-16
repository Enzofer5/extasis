"""Consultas de reportes y dashboard.

Las ventas se miden NETAS de devoluciones y anulaciones, prorrateando el descuento
de cada venta entre sus renglones.
"""
from decimal import Decimal

from .. import db


def _lineas_netas(desde, hasta_ex, ubicacion_id=None):
    sql = """
      SELECT v.id AS venta_id, v.fecha, v.ubicacion_id, v.usuario_id, v.metodo_pago_id,
             dv.variante_id, p.id AS producto_id, p.nombre AS producto, p.categoria_id, p.temporada_id,
             (dv.cantidad - COALESCE(dd.dev,0)) AS cant,
             dv.precio_unitario * (dv.cantidad - COALESCE(dd.dev,0)) * IF(v.subtotal>0, v.total/v.subtotal, 1) AS ingreso,
             dv.costo_unitario * (dv.cantidad - COALESCE(dd.dev,0)) AS costo
      FROM ventas v
      JOIN detalle_ventas dv ON dv.venta_id = v.id
      JOIN variantes_producto vp ON vp.id = dv.variante_id
      JOIN productos p ON p.id = vp.producto_id
      LEFT JOIN (SELECT detalle_venta_id, SUM(cantidad) AS dev FROM detalle_devoluciones GROUP BY detalle_venta_id) dd
             ON dd.detalle_venta_id = dv.id
      WHERE v.estado IN ('Completada','Devuelta') AND v.fecha >= %s AND v.fecha < %s"""
    params = [desde, hasta_ex]
    if ubicacion_id:
        sql += " AND v.ubicacion_id = %s"
        params.append(ubicacion_id)
    return sql, params


def totales_ventas(desde, hasta_ex, ubicacion_id=None):
    sub, p = _lineas_netas(desde, hasta_ex, ubicacion_id)
    r = db.query(f"""SELECT COALESCE(SUM(ingreso),0) AS ventas, COALESCE(SUM(costo),0) AS costo,
                            COALESCE(SUM(cant),0) AS unidades, COUNT(DISTINCT venta_id) AS operaciones
                     FROM ({sub}) x""", p, one=True)
    r["ticket_promedio"] = (Decimal(r["ventas"]) / r["operaciones"]) if r["operaciones"] else Decimal(0)
    return r


def ventas_agrupadas(desde, hasta_ex, por, ubicacion_id=None, limite=None):
    sub, p = _lineas_netas(desde, hasta_ex, ubicacion_id)
    grupos = {
        "dia": ("DATE(x.fecha)", "DATE(x.fecha)", "", "etiqueta"),
        "mes": ("DATE_FORMAT(x.fecha,'%Y-%m')", "DATE_FORMAT(x.fecha,'%Y-%m')", "", "etiqueta"),
        "local": ("ub.nombre", "ub.nombre", "JOIN ubicaciones ub ON ub.id=x.ubicacion_id", "total DESC"),
        "vendedor": ("u.nombre", "u.nombre", "JOIN usuarios u ON u.id=x.usuario_id", "total DESC"),
        "producto": ("x.producto", "x.producto_id, x.producto", "", "total DESC"),
        "categoria": ("COALESCE(c.nombre,'Sin categoría')", "COALESCE(c.nombre,'Sin categoría')",
                      "LEFT JOIN categorias c ON c.id=x.categoria_id", "total DESC"),
        "temporada": ("COALESCE(t.nombre,'Sin temporada')", "COALESCE(t.nombre,'Sin temporada')",
                      "LEFT JOIN temporadas t ON t.id=x.temporada_id", "total DESC"),
        "metodo": ("mp.nombre", "mp.nombre", "JOIN metodos_pago mp ON mp.id=x.metodo_pago_id", "total DESC"),
    }
    etq, group, join, orden = grupos[por]
    sql = f"""SELECT {etq} AS etiqueta, COALESCE(SUM(x.ingreso),0) AS total, COALESCE(SUM(x.costo),0) AS costo,
                     COALESCE(SUM(x.cant),0) AS unidades, COUNT(DISTINCT x.venta_id) AS operaciones
              FROM ({sub}) x {join} GROUP BY {group} HAVING unidades > 0 ORDER BY {orden}"""
    if limite:
        sql += f" LIMIT {int(limite)}"
    rows = db.query(sql, p)
    for r in rows:
        r["ganancia_bruta"] = Decimal(r["total"]) - Decimal(r["costo"])
    return rows


def gastos_total(desde, hasta_ex, ubicacion_id=None):
    sql = "SELECT COALESCE(SUM(monto),0) FROM gastos WHERE fecha >= %s AND fecha < %s"
    p = [desde, hasta_ex]
    if ubicacion_id:
        sql += " AND ubicacion_id=%s"
        p.append(ubicacion_id)
    return Decimal(db.scalar(sql, p))


def sueldos_total(desde, hasta_ex, ubicacion_id=None):
    sql = """SELECT COALESCE(SUM(pe.monto),0) FROM pagos_empleados pe JOIN empleados e ON e.id=pe.empleado_id
             WHERE pe.fecha >= %s AND pe.fecha < %s"""
    p = [desde, hasta_ex]
    if ubicacion_id:
        sql += " AND e.ubicacion_id=%s"
        p.append(ubicacion_id)
    return Decimal(db.scalar(sql, p))


def ganancia(desde, hasta_ex, ubicacion_id=None):
    t = totales_ventas(desde, hasta_ex, ubicacion_id)
    g = gastos_total(desde, hasta_ex, ubicacion_id)
    s = sueldos_total(desde, hasta_ex, ubicacion_id)
    ventas = Decimal(t["ventas"])
    costo = Decimal(t["costo"])
    return {"ventas": ventas, "costo": costo, "bruta": ventas - costo, "gastos": g, "sueldos": s,
            "neta": ventas - costo - g - s, "unidades": t["unidades"], "operaciones": t["operaciones"]}


def ganancia_por_local(desde, hasta_ex):
    filas = []
    for ub in db.query("SELECT id, nombre FROM ubicaciones WHERE activo=1 ORDER BY tipo='LOCAL', id"):
        g = ganancia(desde, hasta_ex, ub["id"])
        g["etiqueta"] = ub["nombre"]
        filas.append(g)
    generales = Decimal(db.scalar("SELECT COALESCE(SUM(monto),0) FROM gastos WHERE ubicacion_id IS NULL AND fecha>=%s AND fecha<%s",
                                  (desde, hasta_ex)))
    sueldos_gen = Decimal(db.scalar("""SELECT COALESCE(SUM(pe.monto),0) FROM pagos_empleados pe JOIN empleados e ON e.id=pe.empleado_id
                                       WHERE e.ubicacion_id IS NULL AND pe.fecha>=%s AND pe.fecha<%s""", (desde, hasta_ex)))
    filas.append({"etiqueta": "Negocio general", "ventas": Decimal(0), "costo": Decimal(0), "bruta": Decimal(0),
                  "gastos": generales, "sueldos": sueldos_gen, "neta": -(generales + sueldos_gen),
                  "unidades": 0, "operaciones": 0})
    return filas


def ganancia_mensual(meses=6, ubicacion_id=None):
    from datetime import date
    hoy = date.today()
    res = []
    y, m = hoy.year, hoy.month
    lista = []
    for _ in range(meses):
        lista.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    for y, m in reversed(lista):
        desde = date(y, m, 1)
        hasta = date(y + (m // 12), (m % 12) + 1, 1)
        g = ganancia(desde, hasta, ubicacion_id)
        g["etiqueta"] = f"{m:02d}/{y}"
        res.append(g)
    return res


def stock_por_ubicacion():
    return db.query("""SELECT ub.nombre AS etiqueta, ub.tipo, COALESCE(SUM(s.cantidad),0) AS unidades,
                              COALESCE(SUM(s.cantidad * p.precio_compra),0) AS valor_costo,
                              COALESCE(SUM(s.cantidad * p.precio_venta),0) AS valor_venta
                       FROM ubicaciones ub
                       LEFT JOIN stock s ON s.ubicacion_id=ub.id AND s.cantidad>0
                       LEFT JOIN variantes_producto v ON v.id=s.variante_id
                       LEFT JOIN productos p ON p.id=v.producto_id
                       WHERE ub.activo=1 GROUP BY ub.id, ub.nombre, ub.tipo ORDER BY ub.tipo, ub.id""")


def resumen_stock(ubicacion_id=None):
    """Unidades, valor (a costo y a precio de venta) y renglones por agotarse; de una ubicación o de todas."""
    sql = """SELECT COALESCE(SUM(GREATEST(s.cantidad,0)),0) AS unidades,
                    COALESCE(SUM(GREATEST(s.cantidad,0) * p.precio_compra),0) AS valor_costo,
                    COALESCE(SUM(GREATEST(s.cantidad,0) * p.precio_venta),0) AS valor_venta,
                    COALESCE(SUM(s.cantidad <= s.stock_minimo),0) AS por_agotarse,
                    COALESCE(SUM(s.cantidad <= 0),0) AS agotados,
                    COUNT(DISTINCT IF(s.cantidad > 0, v.producto_id, NULL)) AS productos
             FROM stock s JOIN variantes_producto v ON v.id=s.variante_id
             JOIN productos p ON p.id=v.producto_id
             JOIN ubicaciones ub ON ub.id=s.ubicacion_id
             WHERE p.activo=1 AND v.activo=1 AND ub.activo=1"""
    params = []
    if ubicacion_id:
        sql += " AND s.ubicacion_id=%s"
        params.append(ubicacion_id)
    return db.query(sql, params, one=True)


def lineas_sin_costo(desde, hasta_ex, ubicacion_id=None):
    """Renglones vendidos sin costo registrado: si hay, la ganancia de esas ventas no es confiable."""
    sub, p = _lineas_netas(desde, hasta_ex, ubicacion_id)
    return db.query(f"""SELECT COUNT(*) AS renglones, COALESCE(SUM(cant),0) AS unidades
                        FROM ({sub}) x WHERE cant > 0 AND costo <= 0""", p, one=True)


def resumen_movimientos(desde, hasta_ex, ubicacion_id=None):
    """Unidades movidas por tipo de movimiento en el período (entradas, envíos, ventas, ajustes...)."""
    sql = """SELECT tipo, COUNT(*) AS registros, COALESCE(SUM(ABS(cantidad)),0) AS unidades
             FROM movimientos_stock WHERE fecha >= %s AND fecha < %s"""
    p = [desde, hasta_ex]
    if ubicacion_id:
        sql += " AND (origen_id=%s OR destino_id=%s)"
        p += [ubicacion_id, ubicacion_id]
    sql += " GROUP BY tipo"
    return {r["tipo"]: r for r in db.query(sql, p)}


def comparativa_locales(desde, hasta_ex):
    """Una fila por local con ventas, costo, ganancia, gastos, stock y faltantes, para comparar."""
    filas = []
    for ub in db.query("SELECT id, nombre FROM ubicaciones WHERE tipo='LOCAL' AND activo=1 ORDER BY id"):
        g = ganancia(desde, hasta_ex, ub["id"])
        g.update(id=ub["id"], nombre=ub["nombre"], stock=resumen_stock(ub["id"]))
        g["margen"] = (g["bruta"] / g["ventas"] * 100) if g["ventas"] else Decimal(0)
        filas.append(g)
    return filas


def caja_resumen(desde, hasta_ex, ubicacion_id=None):
    sql = """SELECT c.*, ub.nombre AS ubicacion, ua.nombre AS usuario_apertura, uc.nombre AS usuario_cierre
             FROM cajas c JOIN ubicaciones ub ON ub.id=c.ubicacion_id
             JOIN usuarios ua ON ua.id=c.usuario_apertura_id LEFT JOIN usuarios uc ON uc.id=c.usuario_cierre_id
             WHERE c.fecha_apertura >= %s AND c.fecha_apertura < %s"""
    p = [desde, hasta_ex]
    if ubicacion_id:
        sql += " AND c.ubicacion_id=%s"
        p.append(ubicacion_id)
    sql += " ORDER BY c.fecha_apertura DESC"
    cajas = db.query(sql, p)
    sql_m = """SELECT mc.tipo, mp.nombre AS metodo, SUM(mc.monto) AS total
               FROM movimientos_caja mc JOIN cajas c ON c.id=mc.caja_id
               JOIN metodos_pago mp ON mp.id=mc.metodo_pago_id
               WHERE mc.fecha >= %s AND mc.fecha < %s"""
    pm = [desde, hasta_ex]
    if ubicacion_id:
        sql_m += " AND c.ubicacion_id=%s"
        pm.append(ubicacion_id)
    sql_m += " GROUP BY mc.tipo, mp.nombre ORDER BY mc.tipo, mp.nombre"
    movs = db.query(sql_m, pm)
    return cajas, movs
