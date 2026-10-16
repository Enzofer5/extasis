import os
from datetime import timedelta

from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# Se usa ".env" si existe; si no, "config.env" (misma sintaxis).
for _nombre in (".env", "config.env"):
    _ruta = os.path.join(BASE_DIR, _nombre)
    if os.path.exists(_ruta):
        load_dotenv(_ruta)
        break


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "cambiar-esta-clave-en-el-env")

    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "extasis")
    DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))

    # Sesiones seguras
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("USAR_HTTPS", "0") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.getenv("SESION_HORAS", "12")))

    # CSRF
    WTF_CSRF_TIME_LIMIT = None

    # Archivos
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "extasis", "static", "uploads")
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "webp", "gif"}

    PER_PAGE = 20
