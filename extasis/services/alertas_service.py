"""Alertas del sistema (calculadas en el momento)."""
from .. import db
from ..models import configuracion


def obtener(scope=None):
    """scope=None => todas las ubicaciones (dueño). scope=id => sólo ese local."""
    alertas = []
    f_ub, p_ub = ("", [])
    if scope:
        f_ub, p_ub = (" AND s.ubicacion_id=%s", [scope])

    bajo = db.scalar(f"""SELECT COUNT(*) FROM stock s JOIN variantes_producto v ON v.id=s.variante_id
                         JOIN productos p ON p.id=v.producto_id
                         WHERE p.activo=1 AND v.activo=1 AND s.cantidad>0 AND s.cantidad<=s.stock_minimo {f_ub}""", p_ub)
    if bajo:
        alertas.append({"tipo": "warning", "icono": "trending-down", "titulo": "Stock bajo",
                        "texto": f"{bajo} variantes con stock bajo", "url": "stock.bajo_stock"})
    agot = db.scalar(f"""SELECT COUNT(*) FROM stock s JOIN variantes_producto v ON v.id=s.variante_id
                         JOIN productos p ON p.id=v.producto_id
                         WHERE p.activo=1 AND v.activo=1 AND s.cantidad<=0 {f_ub}""", p_ub)
    if agot:
        alertas.append({"tipo": "danger", "icono": "x-circle", "titulo": "Productos agotados",
                        "texto": f"{agot} variantes agotadas", "url": "stock.bajo_stock"})

    sql_cajas = """SELECT ub.id, ub.nombre FROM ubicaciones ub
                   WHERE ub.tipo='LOCAL' AND ub.activo=1
                   AND NOT EXISTS (SELECT 1 FROM cajas c WHERE c.ubicacion_id=ub.id AND c.estado='ABIERTA')"""
    p_c = []
    if scope:
        sql_cajas += " AND ub.id=%s"
        p_c = [scope]
    for c in db.query(sql_cajas, p_c):
        alertas.append({"tipo": "info", "icono": "lock", "titulo": "Caja sin abrir",
                        "texto": f"{c['nombre']}: la caja está cerrada", "url": "cajas.index"})

    dias_cc = configuracion.get_int("dias_vencimiento_cc", 30)
    sql_cc = """SELECT COUNT(*) FROM v_saldos_cc s JOIN clientes c ON c.id=s.cliente_id
                WHERE s.saldo>0 AND s.ultimo_movimiento < (NOW() - INTERVAL %s DAY)"""
    p_cc = [dias_cc]
    if scope:
        sql_cc += " AND c.ubicacion_id=%s"
        p_cc.append(scope)
    venc = db.scalar(sql_cc, p_cc)
    if venc:
        alertas.append({"tipo": "danger", "icono": "credit-card", "titulo": "Cuentas corrientes vencidas",
                        "texto": f"{venc} clientes sin movimientos hace más de {dias_cc} días", "url": "clientes.cuentas"})

    if scope is None:
        dias_ant = configuracion.get_int("dias_antiguedad_producto", 180)
        ant = db.scalar("""SELECT COUNT(DISTINCT p.id) FROM productos p
                           JOIN variantes_producto v ON v.producto_id=p.id
                           JOIN stock s ON s.variante_id=v.id AND s.cantidad>0
                           WHERE p.activo=1 AND p.creado_en < (NOW() - INTERVAL %s DAY)""", (dias_ant,))
        if ant:
            alertas.append({"tipo": "info", "icono": "clock", "titulo": "Mercadería antigua",
                            "texto": f"{ant} productos con más de {dias_ant} días en stock", "url": "reportes.stock"})
        pend = db.scalar("SELECT COUNT(*) FROM solicitudes_stock WHERE estado IN ('Pendiente','Aprobada','Preparando')")
        if pend:
            alertas.append({"tipo": "warning", "icono": "inbox", "titulo": "Solicitudes de stock",
                            "texto": f"{pend} solicitudes por atender", "url": "solicitudes.index"})
        inv = db.scalar("SELECT COUNT(*) FROM inventarios WHERE estado='Pendiente'")
        if inv:
            alertas.append({"tipo": "warning", "icono": "clipboard", "titulo": "Inventarios a aprobar",
                            "texto": f"{inv} inventarios esperan autorización", "url": "inventarios.index"})
    else:
        transito = db.scalar("SELECT COUNT(*) FROM transferencias WHERE destino_id=%s AND estado='En tránsito'", (scope,))
        if transito:
            alertas.append({"tipo": "info", "icono": "truck", "titulo": "Mercadería en camino",
                            "texto": f"{transito} envíos para recibir", "url": "solicitudes.index"})
    return alertas
