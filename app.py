"""
ÉXTASIS — Sistema de Gestión de Indumentaria
=============================================
Punto de entrada. En VS Code: abrí este archivo y apretá ▶ (Run Python File).

La primera vez:
  1. Instala automáticamente las dependencias de requirements.txt (si faltan).
  2. Verifica la base de datos MySQL y, si no existe, la crea con database/schema.sql.
  3. Levanta el servidor en http://localhost:5000 y muestra la IP para entrar desde el celular.
"""
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

REQUIRED_MODULES = ["flask", "flask_wtf", "mysql.connector", "dotenv"]
VENV_DIR = os.path.join(BASE_DIR, ".venv")
VENV_PYTHON = os.path.join(VENV_DIR, "Scripts" if os.name == "nt" else "bin",
                           "python.exe" if os.name == "nt" else "python")


def _faltantes():
    faltantes = []
    for mod in REQUIRED_MODULES:
        try:
            __import__(mod)
        except ImportError:
            faltantes.append(mod)
    return faltantes


def _asegurar_dependencias():
    faltantes = _faltantes()
    if not faltantes:
        return

    # Ya estamos dentro de un entorno virtual: instalar ahí directamente.
    if sys.prefix != sys.base_prefix:
        print(f"[ÉXTASIS] Instalando dependencias faltantes ({', '.join(faltantes)})...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r",
                               os.path.join(BASE_DIR, "requirements.txt")])
        print("[ÉXTASIS] Dependencias instaladas.\n")
        return

    # Python del sistema (p. ej. administrado por uv, que no permite pip install):
    # crear .venv en la carpeta del proyecto y relanzar app.py con ese Python.
    if not os.path.exists(VENV_PYTHON):
        print("[ÉXTASIS] Creando entorno virtual en .venv ...")
        subprocess.check_call([sys.executable, "-m", "venv", VENV_DIR])
    subprocess.check_call([VENV_PYTHON, "-m", "pip", "install", "-q", "-r",
                           os.path.join(BASE_DIR, "requirements.txt")])
    print("[ÉXTASIS] Dependencias listas. Iniciando con .venv ...\n")
    try:
        codigo = subprocess.call([VENV_PYTHON, os.path.abspath(__file__)] + sys.argv[1:])
    except KeyboardInterrupt:  # Ctrl+C: el servidor ya se cerró, salir sin mostrar error
        codigo = 0
    sys.exit(codigo)


def _ip_local():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    _asegurar_dependencias()

    from extasis import create_app
    from extasis.setup_db import verificar_o_crear_bd

    verificar_o_crear_bd()
    app = create_app()

    port = int(os.getenv("PORT", "5000"))
    https = os.getenv("USAR_HTTPS", "0") == "1"
    esquema = "https" if https else "http"
    print("\n" + "=" * 60)
    print("  ÉXTASIS — Sistema de Gestión de Indumentaria")
    print(f"  PC:       {esquema}://localhost:{port}")
    print(f"  Celular:  {esquema}://{_ip_local()}:{port}  (misma red Wi-Fi)")
    print("=" * 60 + "\n")

    ssl_ctx = None
    if https:
        try:
            import cryptography  # noqa: F401
            ssl_ctx = "adhoc"
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "cryptography"])
            ssl_ctx = "adhoc"

    app.run(host="0.0.0.0", port=port,
            debug=os.getenv("FLASK_DEBUG", "0") == "1",
            ssl_context=ssl_ctx, use_reloader=False)
