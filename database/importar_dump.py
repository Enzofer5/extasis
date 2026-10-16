"""
Importa un dump de MySQL en la base de ÉXTASIS usando el usuario de config.env.

Uso (desde la carpeta Extasis, con el Python de .venv):
    .venv\\Scripts\\python.exe database\\importar_dump.py <dump.sql> [respaldo.sql]

Si se indica [respaldo.sql], antes de importar guarda una copia de la base actual
(si la base todavía no existe, se saltea el respaldo).

Quita las cláusulas DEFINER de vistas/rutinas para que el usuario de la app
(sin permisos de root) pueda crearlas.
"""
import glob
import os
import re
import shutil
import subprocess
import sys

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BASE_DIR)
from extasis.config import Config  # noqa: E402


def _bin(nombre):
    """Busca mysql.exe / mysqldump.exe en el PATH o en las instalaciones de MySQL Server."""
    en_path = shutil.which(nombre)
    if en_path:
        return en_path
    candidatos = sorted(glob.glob(rf"C:\Program Files\MySQL\MySQL Server *\bin\{nombre}.exe"), reverse=True)
    if not candidatos:
        sys.exit(f"No encontré {nombre}. Instalá MySQL Server o agregá su carpeta bin al PATH.")
    return candidatos[0]


def main(dump, respaldo=None):
    env = dict(os.environ, MYSQL_PWD=Config.DB_PASSWORD)
    base = ["-h", Config.DB_HOST, "-P", str(Config.DB_PORT), "-u", Config.DB_USER]

    if respaldo:
        with open(respaldo, "wb") as out:
            r = subprocess.run([_bin("mysqldump"), *base, "--no-tablespaces", "--single-transaction",
                                "--databases", Config.DB_NAME], stdout=out, stderr=subprocess.PIPE, env=env)
        if r.returncode == 0:
            print("Respaldo guardado en", respaldo)
        else:
            os.remove(respaldo)
            print("No se hizo respaldo (la base todavía no existe o está vacía).")

    with open(dump, encoding="utf-8") as f:
        sql = f.read()
    sql = re.sub(r"/\*!50013 DEFINER=`[^`]*`@`[^`]*` SQL SECURITY DEFINER \*/", "", sql)
    sql = re.sub(r"DEFINER=`[^`]*`@`[^`]*`\s*", "", sql)
    r = subprocess.run([_bin("mysql"), *base, "--default-character-set=utf8mb4"],
                       input=sql.encode("utf-8"), env=env)
    if r.returncode:
        sys.exit(f"La importación falló (código {r.returncode}). Revisá DB_USER / DB_PASSWORD en config.env.")
    print("Importación completa.")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    main(*sys.argv[1:])
