"""Exporta los datos de demostración a database/demo_datos.sql (no toca usuarios ni permisos)."""
import os
import sys
from datetime import date, datetime
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import mysql.connector  # noqa: E402

from extasis.config import Config  # noqa: E402

TABLAS = ["ubicaciones", "marcas", "categorias", "temporadas", "talles", "colores", "categorias_gasto",
          "proveedores", "clientes", "cuentas_corrientes", "empleados", "productos", "variantes_producto", "stock",
          "compras", "detalle_compras", "pagos", "cajas", "ventas", "detalle_ventas", "movimientos_caja",
          "movimientos_cuenta_corriente", "devoluciones", "detalle_devoluciones", "solicitudes_stock",
          "detalle_solicitudes", "transferencias", "detalle_transferencias", "movimientos_stock",
          "inventarios", "detalle_inventarios", "gastos", "pagos_empleados", "auditoria"]
EXCLUIR_COLS = {"cajas": {"abierta_flag"}}


def lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float, Decimal)):
        return str(v)
    if isinstance(v, (datetime, date)):
        return f"'{v.isoformat(sep=' ') if isinstance(v, datetime) else v.isoformat()}'"
    if isinstance(v, (bytes, bytearray)):
        v = v.decode("utf-8")
    s = str(v).replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "")
    return f"'{s}'"


def main():
    conn = mysql.connector.connect(host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
                                   password=Config.DB_PASSWORD, database=Config.DB_NAME, charset="utf8mb4")
    cur = conn.cursor()
    out = os.path.join(os.path.dirname(__file__), "demo_datos.sql")
    with open(out, "w", encoding="utf-8") as f:
        f.write("-- ÉXTASIS — DATOS DE DEMOSTRACIÓN (ficticios)\n")
        f.write("-- Reemplaza catálogo, stock y movimientos. NO modifica usuarios, contraseñas ni permisos.\n")
        f.write("-- ATENCIÓN: borra cualquier dato cargado antes en esas tablas.\n\n")
        f.write("SET SQL_SAFE_UPDATES = 0;\nUSE extasis;\nSET NAMES utf8mb4;\nSET FOREIGN_KEY_CHECKS = 0;\nSET UNIQUE_CHECKS = 0;\n\n")
        for t in TABLAS:
            f.write(f"DELETE FROM {t};\n")
        f.write("\n")
        for t in TABLAS:
            cur.execute(f"SHOW COLUMNS FROM {t}")
            cols = [c[0] for c in cur.fetchall() if c[0] not in EXCLUIR_COLS.get(t, set())]
            cur.execute(f"SELECT {', '.join('`'+c+'`' for c in cols)} FROM {t} ORDER BY 1")
            rows = cur.fetchall()
            for i in range(0, len(rows), 250):
                chunk = rows[i:i + 250]
                vals = ",\n".join("(" + ",".join(lit(v) for v in r) + ")" for r in chunk)
                f.write(f"INSERT INTO {t} ({', '.join('`'+c+'`' for c in cols)}) VALUES\n{vals};\n")
            f.write("\n")
        f.write("SET UNIQUE_CHECKS = 1;\nSET FOREIGN_KEY_CHECKS = 1;\n")
        f.write("SELECT 'Datos de demostración cargados' AS resultado, (SELECT COUNT(*) FROM ventas) AS ventas, "
                "(SELECT COUNT(*) FROM productos) AS productos;\n")
    print("Generado", out, os.path.getsize(out) // 1024, "KB")


if __name__ == "__main__":
    main()
