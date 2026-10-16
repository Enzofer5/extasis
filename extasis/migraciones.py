"""Actualizaciones de la base de datos que se aplican solas al iniciar app.py.

Cada paso verifica si ya está aplicado (no borra ni pisa datos), así se puede
ejecutar todas las veces que haga falta.
"""


def _hay_columna(cur, db, tabla, columna):
    cur.execute("""SELECT COUNT(*) FROM information_schema.columns
                   WHERE table_schema=%s AND table_name=%s AND column_name=%s""", (db, tabla, columna))
    return cur.fetchone()[0] > 0


def _hay_tabla(cur, db, tabla):
    cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s AND table_name=%s", (db, tabla))
    return cur.fetchone()[0] > 0


def _col(cur, db, tabla, columna, definicion, hechos):
    if not _hay_columna(cur, db, tabla, columna):
        cur.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}")
        hechos.append(f"{tabla}.{columna}")


def aplicar(conn, db):
    cur = conn.cursor()
    cur.execute(f"USE `{db}`")
    hechos = []

    # ---------------- 1) Tarjetas de crédito y créditos personales (MC Cred) ----------------
    if not _hay_tabla(cur, db, "entidades_financieras"):
        cur.execute("""CREATE TABLE entidades_financieras (
            id      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            nombre  VARCHAR(60) NOT NULL,
            tipo    ENUM('TARJETA','CREDITO_PERSONAL') NOT NULL DEFAULT 'TARJETA',
            activo  TINYINT(1) NOT NULL DEFAULT 1,
            UNIQUE KEY uq_entidad (nombre, tipo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        hechos.append("entidades_financieras")
    if not _hay_tabla(cur, db, "planes_cuotas"):
        cur.execute("""CREATE TABLE planes_cuotas (
            id           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            entidad_id   INT UNSIGNED NOT NULL,
            cuotas       INT NOT NULL CHECK (cuotas > 0),
            interes_pct  DECIMAL(6,2) NOT NULL DEFAULT 0 CHECK (interes_pct >= 0),
            activo       TINYINT(1) NOT NULL DEFAULT 1,
            UNIQUE KEY uq_plan (entidad_id, cuotas),
            CONSTRAINT fk_plan_entidad FOREIGN KEY (entidad_id) REFERENCES entidades_financieras(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        hechos.append("planes_cuotas")
        # Valores de ejemplo: se editan en Configuración → Tarjetas y créditos
        ejemplos = [("Visa", "TARJETA", [(1, 0), (3, 12), (6, 25)]),
                    ("Mastercard", "TARJETA", [(1, 0), (3, 12), (6, 25)]),
                    ("Naranja", "TARJETA", [(1, 0), (3, 15)]),
                    ("MC Cred", "CREDITO_PERSONAL", [(3, 20), (6, 40), (12, 80)])]
        for nombre, tipo, planes in ejemplos:
            cur.execute("INSERT IGNORE INTO entidades_financieras (nombre, tipo) VALUES (%s,%s)", (nombre, tipo))
            cur.execute("SELECT id FROM entidades_financieras WHERE nombre=%s AND tipo=%s", (nombre, tipo))
            eid = cur.fetchone()[0]
            for cuotas, interes in planes:
                cur.execute("INSERT IGNORE INTO planes_cuotas (entidad_id, cuotas, interes_pct) VALUES (%s,%s,%s)",
                            (eid, cuotas, interes))
    cur.execute("SELECT COUNT(*) FROM metodos_pago WHERE codigo='CREDPERS'")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO metodos_pago (codigo, nombre) VALUES ('CREDPERS','Crédito personal')")
        hechos.append("método Crédito personal")
    cur.execute("UPDATE metodos_pago SET nombre='Tarjeta de crédito' WHERE codigo='CREDITO' AND nombre='Crédito'")
    cur.execute("UPDATE metodos_pago SET nombre='Tarjeta de débito' WHERE codigo='DEBITO' AND nombre='Débito'")

    # Datos de financiación guardados en cada venta (copia histórica del plan usado)
    _col(cur, db, "ventas", "plan_id", "INT UNSIGNED NULL", hechos)
    _col(cur, db, "ventas", "entidad", "VARCHAR(60) NULL", hechos)
    _col(cur, db, "ventas", "cuotas", "INT NULL", hechos)
    _col(cur, db, "ventas", "interes_pct", "DECIMAL(6,2) NOT NULL DEFAULT 0", hechos)
    _col(cur, db, "ventas", "recargo", "DECIMAL(14,2) NOT NULL DEFAULT 0", hechos)

    # ---------------- 2) Cambios: venta nueva pagada en parte con lo devuelto ----------------
    _col(cur, db, "ventas", "credito_cambio", "DECIMAL(14,2) NOT NULL DEFAULT 0", hechos)
    _col(cur, db, "ventas", "devolucion_origen_id", "INT UNSIGNED NULL", hechos)
    _col(cur, db, "devoluciones", "metodo_pago_id", "INT UNSIGNED NULL", hechos)
    _col(cur, db, "devoluciones", "venta_cambio_id", "INT UNSIGNED NULL", hechos)
    _col(cur, db, "devoluciones", "diferencia", "DECIMAL(14,2) NOT NULL DEFAULT 0", hechos)

    # ---------------- 3) Gastos: servicios (fijos) y diarios (de caja) ----------------
    if not _hay_columna(cur, db, "categorias_gasto", "tipo"):
        cur.execute("ALTER TABLE categorias_gasto ADD COLUMN tipo ENUM('SERVICIO','DIARIO') NOT NULL DEFAULT 'SERVICIO'")
        cur.execute("""UPDATE categorias_gasto SET tipo='DIARIO'
                       WHERE nombre IN ('Limpieza','Transporte','Reparaciones','Mantenimiento','Otros')""")
        for nombre, tipo in [("Gas", "SERVICIO"), ("Teléfono", "SERVICIO"), ("Contador", "SERVICIO"),
                             ("Bolsas y etiquetas", "DIARIO"), ("Cadete / envíos", "DIARIO"), ("Café y comida", "DIARIO")]:
            cur.execute("INSERT IGNORE INTO categorias_gasto (nombre, tipo) VALUES (%s,%s)", (nombre, tipo))
        cur.execute("UPDATE categorias_gasto SET nombre='Internet / WiFi' WHERE nombre='Internet'")
        hechos.append("categorias_gasto.tipo")
    _col(cur, db, "gastos", "periodo", "CHAR(7) NULL", hechos)

    conn.commit()
    cur.close()
    return hechos
