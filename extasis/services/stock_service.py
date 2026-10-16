"""Stock por ubicación.

Regla de oro: el stock NUNCA se modifica directamente desde una ruta. Siempre se usa
`mover()` dentro de una transacción, que:
  1. bloquea la fila (SELECT ... FOR UPDATE) para evitar ventas simultáneas del mismo artículo,
  2. valida que no quede negativo (salvo que se permita),
  3. actualiza la cantidad.
Y `registrar_movimiento()` deja la traza en movimientos_stock.
"""
from ..models import configuracion
from . import NegocioError


def _stock_minimo_default():
    return configuracion.get_int("stock_minimo_default", 2)


def cantidad(tx, variante_id, ubicacion_id, lock=False):
    sql = "SELECT cantidad FROM stock WHERE variante_id=%s AND ubicacion_id=%s"
    if lock:
        sql += " FOR UPDATE"
    row = tx.query(sql, (variante_id, ubicacion_id), one=True)
    return row["cantidad"] if row else 0


def mover(tx, variante_id, ubicacion_id, delta, permitir_negativo=False, etiqueta=None):
    """Suma (delta>0) o resta (delta<0) stock de una variante en una ubicación."""
    row = tx.query("SELECT cantidad FROM stock WHERE variante_id=%s AND ubicacion_id=%s FOR UPDATE",
                   (variante_id, ubicacion_id), one=True)
    if row is None:
        tx.execute("INSERT INTO stock (variante_id, ubicacion_id, cantidad, stock_minimo) VALUES (%s,%s,0,%s)",
                   (variante_id, ubicacion_id, _stock_minimo_default()))
        actual = 0
    else:
        actual = row["cantidad"]
    nuevo = actual + int(delta)
    if nuevo < 0 and not permitir_negativo:
        nombre = etiqueta or f"variante #{variante_id}"
        raise NegocioError(f"Stock insuficiente de {nombre}: disponible {actual}, se requieren {abs(int(delta))}.")
    tx.execute("UPDATE stock SET cantidad=%s WHERE variante_id=%s AND ubicacion_id=%s",
               (nuevo, variante_id, ubicacion_id))
    return nuevo


def establecer(tx, variante_id, ubicacion_id, nueva_cantidad):
    """Fija el stock (inventario/ajuste). Devuelve la diferencia aplicada."""
    actual = cantidad(tx, variante_id, ubicacion_id, lock=True)
    diff = int(nueva_cantidad) - actual
    if diff:
        mover(tx, variante_id, ubicacion_id, diff, permitir_negativo=True)
    return diff


def registrar_movimiento(tx, tipo, variante_id, cant, usuario_id, origen_id=None, destino_id=None,
                         motivo=None, ref_tipo=None, ref_id=None):
    tx.execute(
        """INSERT INTO movimientos_stock
           (tipo, variante_id, cantidad, origen_id, destino_id, usuario_id, motivo, referencia_tipo, referencia_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (tipo, variante_id, int(cant), origen_id, destino_id, usuario_id,
         (motivo or None) and str(motivo)[:255], ref_tipo, ref_id))


def etiqueta_variante(tx, variante_id):
    r = tx.query("""SELECT p.nombre, t.nombre AS talle, c.nombre AS color
                    FROM variantes_producto v JOIN productos p ON p.id=v.producto_id
                    JOIN talles t ON t.id=v.talle_id JOIN colores c ON c.id=v.color_id
                    WHERE v.id=%s""", (variante_id,), one=True)
    if not r:
        return f"variante #{variante_id}"
    partes = [r["nombre"], f"T.{r['talle']}"]
    if r["color"] != "Único":
        partes.append(r["color"])
    return " ".join(partes)


def transferir(tx, origen_id, destino_id, items, usuario_id, observaciones=None, solicitud_id=None,
               en_transito=False):
    """Crea una transferencia. items = [(variante_id, cantidad), ...].

    en_transito=False: descuenta del origen y suma en destino en el mismo acto.
    en_transito=True : sólo descuenta del origen (la mercadería viaja). Se acredita con `recibir()`.
    """
    if int(origen_id) == int(destino_id):
        raise NegocioError("El origen y el destino deben ser distintos.")
    items = [(int(v), int(c)) for v, c in items if int(c) > 0]
    if not items:
        raise NegocioError("La transferencia no tiene productos.")
    estado = "En tránsito" if en_transito else "Completada"
    tid = tx.execute(
        """INSERT INTO transferencias (origen_id, destino_id, usuario_id, estado, solicitud_id, observaciones)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (origen_id, destino_id, usuario_id, estado, solicitud_id, observaciones))
    for variante_id, cant in items:
        mover(tx, variante_id, origen_id, -cant, etiqueta=etiqueta_variante(tx, variante_id))
        if not en_transito:
            mover(tx, variante_id, destino_id, cant)
        tx.execute("INSERT INTO detalle_transferencias (transferencia_id, variante_id, cantidad) VALUES (%s,%s,%s)",
                   (tid, variante_id, cant))
        registrar_movimiento(tx, "TRANSFERENCIA", variante_id, cant, usuario_id, origen_id, destino_id,
                             "Enviada (en tránsito)" if en_transito else "Transferencia",
                             "transferencia", tid)
    return tid


def recibir(tx, transferencia_id, usuario_id):
    t = tx.query("SELECT * FROM transferencias WHERE id=%s FOR UPDATE", (transferencia_id,), one=True)
    if not t:
        raise NegocioError("Transferencia inexistente.")
    if t["estado"] != "En tránsito":
        raise NegocioError("La transferencia ya fue recibida.")
    det = tx.query("SELECT variante_id, cantidad FROM detalle_transferencias WHERE transferencia_id=%s",
                   (transferencia_id,))
    for d in det:
        mover(tx, d["variante_id"], t["destino_id"], d["cantidad"])
        registrar_movimiento(tx, "ENTRADA", d["variante_id"], d["cantidad"], usuario_id, t["origen_id"],
                             t["destino_id"], "Recepción de transferencia", "transferencia", transferencia_id)
    tx.execute("UPDATE transferencias SET estado='Completada' WHERE id=%s", (transferencia_id,))
