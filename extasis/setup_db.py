"""Verifica que la base de datos exista; si no, la crea con database/schema.sql."""
import os
import re
import sys

import mysql.connector

from .config import BASE_DIR, Config

SCHEMA = os.path.join(BASE_DIR, "database", "schema.sql")


def _sentencias(sql_text):
    lineas = [ln for ln in sql_text.splitlines() if not ln.strip().startswith("--")]
    texto = "\n".join(lineas)
    partes = re.split(r";\s*(?:\n|$)", texto)
    return [p.strip() for p in partes if p.strip()]


def verificar_o_crear_bd():
    try:
        conn = mysql.connector.connect(
            host=Config.DB_HOST, port=Config.DB_PORT,
            user=Config.DB_USER, password=Config.DB_PASSWORD, charset="utf8mb4",
        )
    except mysql.connector.Error as e:
        print("\n[ÉXTASIS] ERROR: no se pudo conectar a MySQL.")
        print(f"          Detalle: {e}")
        print("          Revisá DB_HOST / DB_USER / DB_PASSWORD en el archivo .env")
        print("          y que el servicio MySQL80 esté iniciado.\n")
        sys.exit(1)

    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s AND table_name='usuarios'",
        (Config.DB_NAME,),
    )
    existe = cur.fetchone()[0] > 0
    if existe:
        print("[ÉXTASIS] Base de datos OK.")
    else:
        print("[ÉXTASIS] Creando base de datos y datos iniciales...")
        with open(SCHEMA, encoding="utf-8") as f:
            sql_text = f.read()
        if Config.DB_NAME != "extasis":
            sql_text = sql_text.replace("CREATE DATABASE IF NOT EXISTS extasis",
                                        f"CREATE DATABASE IF NOT EXISTS `{Config.DB_NAME}`")
            sql_text = sql_text.replace("USE extasis;", f"USE `{Config.DB_NAME}`;")
        for stmt in _sentencias(sql_text):
            cur.execute(stmt)
        conn.commit()
        print("[ÉXTASIS] Base de datos creada.")
    cur.close()
    from .migraciones import aplicar
    try:
        hechos = aplicar(conn, Config.DB_NAME)
        if hechos:
            print("[ÉXTASIS] Base de datos actualizada: " + ", ".join(hechos))
    except mysql.connector.Error as e:
        print(f"\n[ÉXTASIS] ERROR al actualizar la base de datos: {e}\n")
        sys.exit(1)
    conn.close()
