"""Genera datos ficticios coherentes para ÉXTASIS simulando ~3 meses de operación.

Usa los mismos servicios que la aplicación (stock, ventas, cajas, cuentas corrientes),
así los números cierran exactamente. Luego "fecha" cada registro en el día simulado.
Sólo para demostración: NO ejecutar sobre una base con datos reales.
"""
import os
import random
import sys
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from flask import Flask  # noqa: E402

from extasis import db  # noqa: E402
from extasis.config import Config  # noqa: E402
from extasis.services import NegocioError, caja_service, cc_service, stock_service, venta_service  # noqa: E402

random.seed(2026)
HOY = date(2026, 10, 8)
INICIO = HOY - timedelta(days=92)
DEP, CON, L2 = 1, 2, 3
ADMIN = {"id": 1, "nombre": "Administrador"}
U_LOCAL = {CON: {"id": 2, "nombre": "Local Concepción"}, L2: {"id": 3, "nombre": "Segundo Local"}}

app = Flask(__name__)
app.config.from_object(Config)
db.init_pool(app)

# ------------------------------------------------------------------ "máquina del tiempo"
TABLAS_FECHA = {
    "ventas": "fecha", "movimientos_caja": "fecha", "movimientos_stock": "fecha",
    "movimientos_cuenta_corriente": "fecha", "auditoria": "fecha", "transferencias": "fecha",
    "devoluciones": "fecha", "solicitudes_stock": "fecha", "inventarios": "fecha",
    "compras": "creado_en", "pagos": "creado_en", "gastos": "creado_en", "clientes": "creado_en",
    "cajas": "fecha_apertura", "productos": "creado_en", "proveedores": "creado_en",
    "cuentas_corrientes": "creado_en",
}


def max_ids():
    return {t: db.scalar(f"SELECT COALESCE(MAX(id),0) FROM {t}") for t in TABLAS_FECHA}


def fechar(antes, dt):
    for t, col in TABLAS_FECHA.items():
        db.execute(f"UPDATE {t} SET {col}=%s WHERE id>%s", (dt, antes[t]))


def en(dt, fn, *a, **kw):
    antes = max_ids()
    r = fn(*a, **kw)
    fechar(antes, dt)
    return r


def hora(d, h1=10, h2=20):
    return datetime.combine(d, time(random.randint(h1, h2 - 1), random.randint(0, 59), random.randint(0, 59)))


# ------------------------------------------------------------------ catálogos
def setup_catalogos():
    db.execute("""UPDATE ubicaciones SET direccion='Av. Mitre 1450, Concepción', telefono='3865 42-1100',
                  responsable='Enzo Fernández', horarios='Lun a Vie 8:00 a 17:00' WHERE id=1""")
    db.execute("""UPDATE ubicaciones SET direccion='San Martín 245, Concepción', telefono='3865 42-2233',
                  responsable='Luciana Paz' WHERE id=2""")
    db.execute("""UPDATE ubicaciones SET direccion='Av. Sarmiento 812, Aguilares',
                  telefono='3865 48-7788', responsable='Matías Ruiz' WHERE id=3""")
    for m in ["Éxtasis Original", "Norte Denim", "Kalma", "Brava", "Ruta 40", "Urbano Sur", "Pampa Sport"]:
        db.execute("INSERT IGNORE INTO marcas (nombre) VALUES (%s)", (m,))
    for nombre, padre in [("Oversize", 1), ("Básicas", 1), ("Mom", 3), ("Slim", 3), ("Cargo", 2),
                          ("Canguro", 5), ("Puffer", 6), ("Zapatillas", 9), ("Gorras", 10), ("Cintos", 10)]:
        db.execute("INSERT IGNORE INTO categorias (nombre, parent_id) VALUES (%s,%s)", (nombre, padre))
    db.execute("INSERT IGNORE INTO colores (nombre, hex) VALUES ('Celeste','#8ec5ea'),('Bordó','#7b1e2c'),('Verde militar','#4b5320')")


def mid(tabla, nombre):
    return db.scalar(f"SELECT id FROM {tabla} WHERE nombre=%s", (nombre,))


PRODUCTOS = [
    # nombre, marca, categoria, sub, temporada, genero, costo, precio, talles, colores, dias_alta
    ("Remera Oversize Lobo", "Éxtasis Original", "Remeras", "Oversize", 1, "Unisex", 9500, 22000, ["S", "M", "L", "XL"], ["Negro", "Blanco"], 85),
    ("Remera Básica Algodón", "Kalma", "Remeras", "Básicas", 3, "Unisex", 6000, 14000, ["S", "M", "L", "XL"], ["Negro", "Blanco", "Gris", "Beige"], 120),
    ("Remera Estampada Smoke", "Éxtasis Original", "Remeras", "Oversize", 1, "Hombre", 10500, 24500, ["M", "L", "XL"], ["Negro"], 60),
    ("Musculosa Deportiva", "Pampa Sport", "Remeras", None, 1, "Mujer", 7000, 16500, ["XS", "S", "M"], ["Negro", "Blanco", "Rojo"], 45),
    ("Jean Slim Clásico", "Norte Denim", "Jeans", "Slim", 3, "Hombre", 28000, 62000, ["38", "40", "42", "44", "46"], ["Azul", "Negro"], 120),
    ("Jean Mom Tiro Alto", "Norte Denim", "Jeans", "Mom", 3, "Mujer", 29500, 65000, ["36", "38", "40", "42"], ["Celeste", "Azul"], 110),
    ("Pantalón Cargo", "Ruta 40", "Pantalones", "Cargo", 2, "Hombre", 24000, 54000, ["38", "40", "42", "44"], ["Verde militar", "Negro", "Beige"], 70),
    ("Jogger Frisa", "Pampa Sport", "Pantalones", None, 2, "Unisex", 15000, 34000, ["S", "M", "L", "XL"], ["Gris", "Negro"], 100),
    ("Camisa Lino", "Urbano Sur", "Camisas", None, 1, "Hombre", 21000, 47000, ["M", "L", "XL"], ["Blanco", "Beige", "Celeste"], 40),
    ("Camisa Oxford", "Urbano Sur", "Camisas", None, 3, "Hombre", 19000, 42000, ["S", "M", "L", "XL"], ["Celeste", "Blanco"], 260),
    ("Buzo Canguro Lobo", "Éxtasis Original", "Buzos", "Canguro", 2, "Unisex", 22000, 52000, ["S", "M", "L", "XL", "XXL"], ["Negro", "Gris", "Bordó"], 115),
    ("Buzo Cuello Redondo", "Kalma", "Buzos", None, 2, "Mujer", 17000, 39000, ["XS", "S", "M", "L"], ["Beige", "Negro"], 90),
    ("Campera Puffer", "Brava", "Camperas", "Puffer", 2, "Unisex", 52000, 118000, ["S", "M", "L", "XL"], ["Negro", "Verde militar"], 115),
    ("Campera de Jean", "Norte Denim", "Camperas", None, 3, "Mujer", 38000, 84000, ["S", "M", "L"], ["Celeste", "Azul"], 75),
    ("Vestido Midi Floral", "Kalma", "Vestidos", None, 1, "Mujer", 22000, 49000, ["XS", "S", "M", "L"], ["Rojo", "Negro"], 35),
    ("Vestido Negro Corto", "Brava", "Vestidos", None, 3, "Mujer", 20000, 45000, ["XS", "S", "M"], ["Negro"], 300),
    ("Falda Plisada", "Kalma", "Faldas", None, 1, "Mujer", 14000, 31000, ["S", "M", "L"], ["Negro", "Beige"], 50),
    ("Zapatillas Urbanas", "Pampa Sport", "Calzado", "Zapatillas", 3, "Unisex", 45000, 99000, ["36", "38", "40", "42", "44"], ["Blanco", "Negro"], 100),
    ("Gorra Trucker Éxtasis", "Éxtasis Original", "Accesorios", "Gorras", 3, "Unisex", 5000, 13500, ["Único"], ["Negro", "Blanco"], 120),
    ("Cinto de Cuero", "Urbano Sur", "Accesorios", "Cintos", 3, "Hombre", 7500, 17500, ["Único"], ["Negro", "Bordó"], 210),
    ("Medias Pack x3", "Pampa Sport", "Accesorios", None, 3, "Unisex", 3200, 8500, ["Único"], ["Blanco", "Negro"], 120),
]


def crear_productos():
    from extasis.routes.productos import crear_variantes
    ids = []
    for i, (nom, marca, cat, sub, temp, gen, costo, precio, talles, colores, dias) in enumerate(PRODUCTOS, start=1):
        t_ids = [mid("talles", t) for t in talles]
        c_ids = [mid("colores", c) for c in colores]
        with db.transaction() as tx:
            pid = tx.execute(
                """INSERT INTO productos (codigo_interno, nombre, marca_id, categoria_id, subcategoria_id, descripcion,
                   precio_compra, precio_venta, temporada_id, genero, creado_en) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (f"EXT-{i:05d}", nom, mid("marcas", marca), mid("categorias", cat),
                 db.scalar("SELECT id FROM categorias WHERE nombre=%s AND parent_id IS NOT NULL", (sub,)) if sub else None,
                 f"{nom} — artículo de demostración.", costo, precio, temp, gen,
                 datetime.combine(HOY - timedelta(days=dias), time(11, 0))))
            crear_variantes(tx, pid, t_ids, c_ids)
        ids.append(pid)
    return ids


def variantes():
    rows = db.query("""SELECT v.id, v.producto_id, p.precio_compra, p.precio_venta, t.nombre talle
                       FROM variantes_producto v JOIN productos p ON p.id=v.producto_id JOIN talles t ON t.id=v.talle_id""")
    # popularidad: talles centrales y productos baratos se venden más
    for r in rows:
        peso = 3 if r["talle"] in ("M", "L", "40", "42", "38", "Único") else 1.5
        peso *= 2.2 if r["precio_venta"] < 30000 else (1.2 if r["precio_venta"] < 70000 else 0.7)
        r["peso"] = peso
    return rows


# ------------------------------------------------------------------ personas
NOMBRES = ["Sofía", "Valentina", "Martina", "Camila", "Lucía", "Julieta", "Agustina", "Micaela", "Florencia", "Paula",
           "Mateo", "Santiago", "Benjamín", "Joaquín", "Tomás", "Lautaro", "Facundo", "Nicolás", "Franco", "Gonzalo"]
APELLIDOS = ["González", "Rodríguez", "Gómez", "Fernández", "López", "Díaz", "Martínez", "Pérez", "Romero", "Sosa",
             "Álvarez", "Torres", "Ruiz", "Ramírez", "Flores", "Acosta", "Medina", "Herrera", "Aguirre", "Juárez"]


def crear_clientes():
    ids = {CON: [], L2: []}
    usados = set()
    for i in range(46):
        n, a = random.choice(NOMBRES), random.choice(APELLIDOS)
        dni = str(random.randint(28_000_000, 46_000_000))
        if dni in usados:
            continue
        usados.add(dni)
        ub = CON if i % 3 else L2
        tel = f"3865 {random.randint(400000, 699999)}"
        dt = hora(INICIO + timedelta(days=random.randint(0, 40)))
        with db.transaction() as tx:
            cid = tx.execute("""INSERT INTO clientes (nombre, apellido, dni, telefono, whatsapp, email, direccion, ubicacion_id, creado_en)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                             (n, a, dni, tel, tel.replace(" ", ""), f"{n.lower()}.{a.lower()}{i}@mail.com".replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u"),
                              f"Calle {random.randint(1, 60)} N° {random.randint(10, 1500)}", ub, dt))
            cc_service.cuenta_de(tx, cid)
            if i % 7 == 0:
                tx.execute("UPDATE cuentas_corrientes SET limite_credito=%s WHERE cliente_id=%s", (300000, cid))
        ids[ub].append(cid)
    return ids


def crear_proveedores():
    datos = [("Textil Norte S.A.", "Textil Norte", "30-71234567-1", "Carlos Méndez"),
             ("Denim Factory SRL", "Denim Factory", "30-70987654-3", "Laura Ortiz"),
             ("Calzados del Sur S.A.", "Calzados Sur", "30-71122334-5", "Jorge Vera"),
             ("Confecciones Kalma SRL", "Kalma", "30-71555666-7", "Mariana Luna"),
             ("Accesorios Ruta SAS", "Ruta Acc.", "30-71888999-0", "Pablo Ibáñez")]
    ids = []
    for rs, nom, cuit, contacto in datos:
        ids.append(db.execute("""INSERT INTO proveedores (razon_social, nombre, cuit, telefono, email, direccion, contacto, creado_en)
                                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                              (rs, nom, cuit, f"381 4{random.randint(100000, 999999)}", f"ventas@{nom.split()[0].lower()}.com.ar",
                               "Parque Industrial, San Miguel de Tucumán", contacto, datetime.combine(INICIO - timedelta(days=30), time(9)))))
    return ids


def crear_empleados():
    datos = [("Luciana", "Paz", "Encargado", CON, 720000), ("Brenda", "Soria", "Vendedor", CON, 560000),
             ("Ezequiel", "Molina", "Cajero", CON, 580000), ("Matías", "Ruiz", "Encargado", L2, 720000),
             ("Rocío", "Gallardo", "Vendedor", L2, 560000), ("Hernán", "Quiroga", "Depósito", DEP, 600000),
             ("Carla", "Ledesma", "Administrativo", None, 650000)]
    ids = []
    for i, (n, a, p, ub, s) in enumerate(datos):
        ids.append(db.execute("""INSERT INTO empleados (nombre, apellido, dni, telefono, email, puesto, fecha_ingreso, sueldo, ubicacion_id)
                                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                              (n, a, str(30_000_000 + i * 1_234_567), f"3865 5{random.randint(10000, 99999)}",
                               f"{n.lower()}@extasis.com.ar".replace("í", "i"), p, date(2024 + i % 2, 1 + i, 10), s, ub)))
    return list(zip(ids, [d[4] for d in datos]))


# ------------------------------------------------------------------ operaciones
def compra(dt, prov, items, factura, pagado_ratio=0.5, metodo=4):
    total = sum(Decimal(str(p)) * c for _, c, p in items)
    antes = max_ids()
    with db.transaction() as tx:
        cid = tx.execute("""INSERT INTO compras (proveedor_id, ubicacion_id, numero_factura, fecha, total, metodo_pago_id,
                            monto_pagado, usuario_id) VALUES (%s,%s,%s,%s,%s,%s,%s,1)""",
                         (prov, DEP, factura, dt.date(), total, metodo, (total * Decimal(pagado_ratio)).quantize(Decimal("1"))))
        for vid, cant, precio in items:
            tx.execute("INSERT INTO detalle_compras (compra_id, variante_id, cantidad, precio_compra) VALUES (%s,%s,%s,%s)",
                       (cid, vid, cant, precio))
            stock_service.mover(tx, vid, DEP, cant)
            stock_service.registrar_movimiento(tx, "COMPRA", vid, cant, 1, destino_id=DEP, motivo=f"Compra N° {cid}",
                                               ref_tipo="compra", ref_id=cid)
        tx.execute("INSERT INTO auditoria (usuario_id, accion, modulo, registro_id) VALUES (1,%s,'compras',%s)",
                   (f"Administrador registró la compra N° {cid} por ${total:,.2f}", cid))
    fechar(antes, dt)
    return cid


def reponer_locales(dt, vars_, minimo=3, objetivo=6):
    """Transferencia del depósito a cada local de lo que esté bajo."""
    for ub in (CON, L2):
        items = []
        for v in vars_:
            loc = db.scalar("SELECT COALESCE(cantidad,0) FROM stock WHERE variante_id=%s AND ubicacion_id=%s", (v["id"], ub), 0)
            if loc < minimo:
                dep = db.scalar("SELECT COALESCE(cantidad,0) FROM stock WHERE variante_id=%s AND ubicacion_id=%s", (v["id"], DEP), 0)
                cant = min(objetivo - loc, dep // 2)
                if cant > 0:
                    items.append((v["id"], cant))
        if items:
            antes = max_ids()
            with db.transaction() as tx:
                tid = stock_service.transferir(tx, DEP, ub, items, 1, "Reposición semanal")
                tx.execute("INSERT INTO auditoria (usuario_id, accion, modulo, registro_id) VALUES (1,%s,'transferencias',%s)",
                           (f"Administrador transfirió {sum(c for _, c in items)} unidades del depósito al local", tid))
            fechar(antes, dt)


def elegir_metodo():
    r = random.random()
    for cod_id, acum in ((1, .36), (2, .56), (3, .70), (4, .82), (5, .95), (6, 1.0)):
        if r <= acum:
            return cod_id
    return 1


def un_dia_de_caja(d, ub, vars_, clientes, cerrar=True, n_ventas=None):
    user = U_LOCAL[ub]
    apertura = datetime.combine(d, time(9, random.randint(0, 25)))
    ultimo_cierre = db.scalar("SELECT efectivo_real FROM cajas WHERE ubicacion_id=%s AND estado='CERRADA' ORDER BY id DESC LIMIT 1", (ub,))
    inicial = Decimal(ultimo_cierre or 50000)
    if inicial > 150000:
        inicial = Decimal(80000)
    caja_id = en(apertura, caja_service.abrir, ub, user["id"], inicial)
    db.execute("INSERT INTO auditoria (usuario_id, accion, modulo, registro_id, fecha) VALUES (%s,%s,'cajas',%s,%s)",
               (user["id"], f"{user['nombre']} abrió la caja con ${inicial:,.2f}", caja_id, apertura))
    findesemana = d.weekday() >= 4
    n = n_ventas if n_ventas is not None else random.randint(5, 10) + (5 if findesemana else 0) - (2 if ub == L2 else 0)
    disponibles = [v for v in vars_]
    pesos = [v["peso"] for v in disponibles]
    horas = sorted(hora(d, 10, 21) for _ in range(n))
    for h in horas:
        cant_items = random.choices([1, 2, 3], [0.6, 0.3, 0.1])[0]
        items = []
        for v in random.choices(disponibles, pesos, k=cant_items):
            st = db.scalar("SELECT COALESCE(cantidad,0) FROM stock WHERE variante_id=%s AND ubicacion_id=%s", (v["id"], ub), 0)
            if st > 0 and v["id"] not in [i["variante_id"] for i in items]:
                items.append({"variante_id": v["id"], "cantidad": 1 if st < 3 or random.random() < .85 else 2})
        if not items:
            continue
        metodo = elegir_metodo()
        cli = None
        if metodo == 6 or random.random() < .3:
            cli = random.choice(clientes[ub])
        desc = {}
        if random.random() < .15:
            desc = {"descuento_tipo": "porc", "descuento_valor": random.choice([5, 10, 15])}
        data = {"items": items, "metodo_pago_id": metodo, "cliente_id": cli, **desc}
        try:
            en(h, venta_service.crear_venta, data, user, ub)
        except NegocioError:
            data["metodo_pago_id"] = 1
            try:
                en(h, venta_service.crear_venta, data, user, ub)
            except NegocioError:
                pass
    # anulación ocasional (mientras la caja sigue abierta)
    if random.random() < .04:
        ult = db.query("SELECT id, fecha FROM ventas WHERE caja_id=%s AND estado='Completada' ORDER BY id DESC LIMIT 1", (caja_id,))
        if ult:
            en(ult[0]["fecha"] + timedelta(minutes=8), venta_service.anular, ult[0]["id"], ADMIN, "Error de carga en el POS")
    # cobros de cuenta corriente
    if random.random() < .35:
        deudores = db.query("""SELECT s.cliente_id, s.saldo FROM v_saldos_cc s JOIN clientes c ON c.id=s.cliente_id
                               WHERE s.saldo>0 AND c.ubicacion_id=%s""", (ub,))
        if deudores:
            dd = random.choice(deudores)
            monto = min(Decimal(dd["saldo"]), Decimal(random.choice([10000, 20000, 30000, 50000])))
            en(hora(d, 11, 20), cc_service.registrar_pago, dd["cliente_id"], monto, random.choice([1, 4, 5]), user["id"], ub)
    # movimientos de caja
    if random.random() < .25:
        def gasto():
            with db.transaction() as tx:
                concepto = random.choice(["Artículos de limpieza", "Bolsas y etiquetas", "Café y yerba", "Cadete", "Ferretería"])
                monto = Decimal(random.choice([3500, 5000, 8000, 12000]))
                caja_service.registrar(tx, caja_id, "GASTO", concepto, monto, 1, user["id"])
                tx.execute("""INSERT INTO gastos (categoria_gasto_id, descripcion, monto, ubicacion_id, fecha, metodo_pago_id, usuario_id, caja_id)
                              VALUES (%s,%s,%s,%s,%s,1,%s,%s)""",
                           (mid("categorias_gasto", "Limpieza" if "limpieza" in concepto else "Otros"), concepto, monto, ub, d, user["id"], caja_id))
        en(hora(d, 12, 19), gasto)
    res = caja_service.resumen(caja_id)
    if res["esperado"] > 250000 and random.random() < .5:
        def retiro():
            with db.transaction() as tx:
                caja_service.registrar(tx, caja_id, "RETIRO", "Retiro para depósito bancario", Decimal(150000), 1, 1)
        en(datetime.combine(d, time(19, 30)), retiro)
    if not cerrar:
        return caja_id
    res = caja_service.resumen(caja_id)
    dif = random.choices([0, -500, -1000, -2500, 300, 1000], [.72, .08, .07, .04, .05, .04])[0]
    real = res["esperado"] + dif
    caja_service.cerrar(caja_id, user["id"], real, "Faltante menor" if dif < 0 else None)
    cierre = datetime.combine(d, time(21, random.randint(0, 40)))
    db.execute("UPDATE cajas SET fecha_cierre=%s WHERE id=%s", (cierre, caja_id))
    db.execute("INSERT INTO auditoria (usuario_id, accion, modulo, registro_id, fecha) VALUES (%s,%s,'cajas',%s,%s)",
               (user["id"], f"{user['nombre']} realizó el cierre de caja (diferencia ${dif:,.2f})", caja_id, cierre))
    return caja_id


def main():
    print("Catálogos...")
    setup_catalogos()
    prods = crear_productos()
    vars_ = variantes()
    clientes = crear_clientes()
    provs = crear_proveedores()
    empleados = crear_empleados()
    print(f"  {len(prods)} productos, {len(vars_)} variantes")

    prov_de = lambda pid: {1: provs[0], 2: provs[0], 3: provs[0], 4: provs[3], 5: provs[1], 6: provs[1], 7: provs[0], 8: provs[3],  # noqa: E731
                           9: provs[0], 10: provs[0], 11: provs[0], 12: provs[3], 13: provs[3], 14: provs[1], 15: provs[3],
                           16: provs[3], 17: provs[3], 18: provs[2], 19: provs[4], 20: provs[4], 21: provs[4]}[pid]

    def gran_compra(dt, nro, factor=1.0):
        por_prov = {}
        for v in vars_:
            cant = int(random.randint(8, 16) * factor)
            if v["precio_venta"] > 90000:
                cant = max(4, cant // 2)
            por_prov.setdefault(prov_de(v["producto_id"]), []).append((v["id"], cant, float(v["precio_compra"])))
        for i, (prov, items) in enumerate(por_prov.items()):
            compra(dt + timedelta(minutes=i * 7), prov, items, f"A-0003-{nro + i:08d}", pagado_ratio=random.choice([0.4, 0.6, 1.0]))

    gran_compra(datetime.combine(INICIO - timedelta(days=3), time(10)), 1500, 1.6)
    reponer_locales(datetime.combine(INICIO - timedelta(days=2), time(11)), vars_, minimo=5, objetivo=7)

    d = INICIO
    nro_compra = 1600
    while d <= HOY:
        if d.weekday() == 6:  # domingo cerrado
            d += timedelta(days=1)
            continue
        if d.weekday() == 0:
            reponer_locales(datetime.combine(d, time(8, 30)), vars_)
        if d in (INICIO + timedelta(days=30), INICIO + timedelta(days=62)):
            gran_compra(datetime.combine(d, time(8)), nro_compra, 1.0)
            nro_compra += 100
        hoy = d == HOY
        for ub in (CON, L2):
            un_dia_de_caja(d, ub, vars_, clientes, cerrar=not hoy, n_ventas=(random.randint(3, 5) if hoy else None))
        # gastos generales y sueldos a comienzo de mes
        if d.day <= 3 and not db.scalar("SELECT COUNT(*) FROM gastos WHERE fecha>=%s AND descripcion LIKE 'Alquiler%%'",
                                         (d.replace(day=1),)):
            mes = d.strftime("%m/%Y")
            for cat, desc, monto, ub in [("Alquiler", f"Alquiler local Concepción {mes}", 650000, CON),
                                         ("Alquiler", f"Alquiler local Aguilares {mes}", 480000, L2),
                                         ("Alquiler", f"Alquiler depósito {mes}", 320000, DEP),
                                         ("Luz", f"Factura de luz {mes}", 98000, CON),
                                         ("Luz", f"Factura de luz {mes}", 76000, L2),
                                         ("Internet", f"Internet y telefonía {mes}", 42000, None),
                                         ("Publicidad", f"Publicidad en redes {mes}", 150000, None),
                                         ("Seguridad", f"Monitoreo de alarmas {mes}", 35000, None),
                                         ("Alquiler", f"Alquiler oficina administrativa {mes}", 0, None)]:
                if monto:
                    db.execute("""INSERT INTO gastos (categoria_gasto_id, descripcion, monto, ubicacion_id, fecha, metodo_pago_id, usuario_id, creado_en)
                                  VALUES (%s,%s,%s,%s,%s,4,1,%s)""", (mid("categorias_gasto", cat), desc, monto, ub, d, datetime.combine(d, time(9))))
            prev = (d.replace(day=1) - timedelta(days=1))
            for eid, sueldo in empleados:
                db.execute("""INSERT INTO pagos_empleados (empleado_id, concepto, periodo, monto, fecha, metodo_pago_id, usuario_id)
                              VALUES (%s,%s,%s,%s,%s,4,1)""", (eid, f"Sueldo {prev.strftime('%m/%Y')}", prev.strftime("%Y-%m"), sueldo, d))
        if d.day == 15:
            for eid, sueldo in random.sample(empleados, 2):
                db.execute("""INSERT INTO pagos_empleados (empleado_id, concepto, periodo, monto, fecha, metodo_pago_id, usuario_id)
                              VALUES (%s,'Adelanto de sueldo',%s,%s,%s,1,1)""", (eid, d.strftime("%Y-%m"), sueldo // 4, d))
        if d.day in (10, 25):
            for p in provs:
                deuda = db.scalar("""SELECT (SELECT COALESCE(SUM(total-monto_pagado),0) FROM compras WHERE proveedor_id=%s)
                                     - (SELECT COALESCE(SUM(monto),0) FROM pagos WHERE proveedor_id=%s)""", (p, p))
                if deuda > 0 and random.random() < .7:
                    monto = (Decimal(deuda) * Decimal("0.4")).quantize(Decimal("1"))
                    db.execute("""INSERT INTO pagos (proveedor_id, fecha, monto, metodo_pago_id, usuario_id, observaciones, creado_en)
                                  VALUES (%s,%s,%s,4,1,'Pago a cuenta',%s)""", (p, d, monto, datetime.combine(d, time(10))))
        d += timedelta(days=1)
        if d.day == 1:
            print("  mes simulado:", d.strftime("%m/%Y"))

    print("Devoluciones y anulaciones...")
    ventas = db.query("SELECT id, fecha, ubicacion_id FROM ventas WHERE estado='Completada' AND fecha < %s ORDER BY RAND(7) LIMIT 14",
                      (datetime.combine(HOY - timedelta(days=3), time(0)),))
    for v in ventas[:10]:
        det = db.query("SELECT id FROM detalle_ventas WHERE venta_id=%s LIMIT 1", (v["id"],))
        dt = v["fecha"] + timedelta(days=random.randint(1, 3))
        if dt.date() >= HOY or dt.weekday() == 6:
            continue
        # devolución con "CAMBIO" (no mueve dinero de cajas ya cerradas)
        try:
            en(dt, venta_service.devolver, v["id"], {det[0]["id"]: 1}, random.choice(["Cambio de talle", "Cambio de color", "Falla en costura"]),
               U_LOCAL[v["ubicacion_id"]])
        except NegocioError:
            pass

    print("Solicitudes e inventarios...")
    v_rand = random.sample(vars_, 6)

    def solicitud(ub, items, dt, estado):
        with db.transaction() as tx:
            sid = tx.execute("INSERT INTO solicitudes_stock (ubicacion_id, usuario_id, observaciones) VALUES (%s,%s,%s)",
                             (ub, U_LOCAL[ub]["id"], random.choice(["Se están pidiendo mucho", "Para el fin de semana", None])))
            for v, c in items:
                tx.execute("INSERT INTO detalle_solicitudes (solicitud_id, variante_id, cantidad) VALUES (%s,%s,%s)", (sid, v["id"], c))
        db.execute("UPDATE solicitudes_stock SET fecha=%s WHERE id=%s", (dt, sid))
        if estado in ("Aprobada", "Enviada", "Recibida", "Rechazada"):
            db.execute("UPDATE solicitudes_stock SET estado=%s, actualizado_por=1, actualizado_en=%s, respuesta=%s WHERE id=%s",
                       ("Aprobada" if estado != "Rechazada" else "Rechazada", dt + timedelta(hours=2),
                        "Sin stock en depósito" if estado == "Rechazada" else "OK", sid))
        if estado in ("Enviada", "Recibida"):
            def enviar():
                with db.transaction() as tx:
                    stock_service.transferir(tx, DEP, ub, [(v["id"], c) for v, c in items], 1, f"Solicitud N° {sid}",
                                             solicitud_id=sid, en_transito=True)
                    tx.execute("UPDATE solicitudes_stock SET estado='Enviada' WHERE id=%s", (sid,))
            en(dt + timedelta(hours=20), enviar)
        if estado == "Recibida":
            def recibir():
                with db.transaction() as tx:
                    for t in tx.query("SELECT id FROM transferencias WHERE solicitud_id=%s", (sid,)):
                        stock_service.recibir(tx, t["id"], U_LOCAL[ub]["id"])
                    tx.execute("UPDATE solicitudes_stock SET estado='Recibida', actualizado_por=%s, actualizado_en=%s WHERE id=%s",
                               (U_LOCAL[ub]["id"], dt + timedelta(days=1, hours=3), sid))
            en(dt + timedelta(days=1, hours=3), recibir)

    solicitud(CON, [(v_rand[0], 4), (v_rand[1], 3)], datetime.combine(HOY - timedelta(days=20), time(12)), "Recibida")
    solicitud(L2, [(v_rand[2], 5)], datetime.combine(HOY - timedelta(days=12), time(16)), "Rechazada")
    solicitud(L2, [(v_rand[3], 3), (v_rand[4], 2)], datetime.combine(HOY - timedelta(days=2), time(11)), "Enviada")
    solicitud(CON, [(v_rand[5], 6)], datetime.combine(HOY - timedelta(days=1), time(18)), "Aprobada")
    solicitud(CON, [(v_rand[1], 2), (v_rand[3], 2)], datetime.combine(HOY, time(10, 15)), "Pendiente")

    # inventario aprobado (con un faltante) y uno pendiente
    for ub, estado, dias in ((CON, "Aprobado", 25), (L2, "Pendiente", 1)):
        dt = datetime.combine(HOY - timedelta(days=dias), time(20, 30))
        filas = db.query("""SELECT s.variante_id, s.cantidad FROM stock s WHERE s.ubicacion_id=%s AND s.cantidad>0
                            ORDER BY s.variante_id LIMIT 12""", (ub,))
        with db.transaction() as tx:
            iid = tx.execute("INSERT INTO inventarios (ubicacion_id, usuario_id, motivo, fecha) VALUES (%s,%s,%s,%s)",
                             (ub, U_LOCAL[ub]["id"], "Control mensual de remeras y jeans", dt))
            for k, f in enumerate(filas):
                real = f["cantidad"] - (1 if k in (2, 7) else 0)
                tx.execute("INSERT INTO detalle_inventarios (inventario_id, variante_id, stock_sistema, stock_real) VALUES (%s,%s,%s,%s)",
                           (iid, f["variante_id"], f["cantidad"], real))
                if estado == "Aprobado" and real != f["cantidad"]:
                    stock_service.establecer(tx, f["variante_id"], ub, real)
                    stock_service.registrar_movimiento(tx, "AJUSTE", f["variante_id"], real - f["cantidad"], 1, origen_id=ub,
                                                       motivo=f"Inventario N° {iid}: faltante", ref_tipo="inventario", ref_id=iid)
            if estado == "Aprobado":
                tx.execute("UPDATE inventarios SET estado='Aprobado', aprobado_por=1, fecha_aprobacion=%s WHERE id=%s",
                           (dt + timedelta(hours=14), iid))
        db.execute("UPDATE movimientos_stock SET fecha=%s WHERE referencia_tipo='inventario' AND referencia_id=%s", (dt + timedelta(hours=14), iid))

    # un poco de stock bajo / agotado para que se vean las alertas
    for v in random.sample(vars_, 5):
        with db.transaction() as tx:
            stock_service.establecer(tx, v["id"], L2, 0)
    db.execute("UPDATE stock SET stock_minimo=3")

    print("Listo.")
    for t in ["ventas", "detalle_ventas", "cajas", "movimientos_caja", "movimientos_stock", "transferencias", "compras",
              "clientes", "devoluciones", "gastos", "pagos_empleados", "auditoria"]:
        print(f"  {t}: {db.scalar(f'SELECT COUNT(*) FROM {t}')}")


if __name__ == "__main__":
    main()
