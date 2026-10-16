"""Tablas maestras simples (categorías, marcas, talles, colores, etc.)."""
from .. import db

# Lista blanca: nunca se interpola un nombre de tabla que venga del usuario.
CATALOGOS = {
    "categorias": {"titulo": "Categorías", "orden": "COALESCE(parent_id, id), parent_id IS NOT NULL, nombre",
                   "campos": ["nombre", "parent_id"]},
    "marcas": {"titulo": "Marcas", "orden": "nombre", "campos": ["nombre"]},
    "temporadas": {"titulo": "Temporadas", "orden": "id", "campos": ["nombre"]},
    "talles": {"titulo": "Talles", "orden": "orden, nombre", "campos": ["nombre", "orden"]},
    "colores": {"titulo": "Colores", "orden": "nombre", "campos": ["nombre", "hex"]},
    "categorias_gasto": {"titulo": "Tipos de gasto", "orden": "tipo, nombre", "campos": ["nombre", "tipo"]},
    "metodos_pago": {"titulo": "Métodos de pago", "orden": "id", "campos": ["nombre"]},
}


def listar(tabla, solo_activos=True):
    meta = CATALOGOS[tabla]
    where = "WHERE activo=1" if solo_activos else ""
    return db.query(f"SELECT * FROM {tabla} {where} ORDER BY {meta['orden']}")


def categorias_principales(solo_activos=True):
    w = "AND activo=1" if solo_activos else ""
    return db.query(f"SELECT * FROM categorias WHERE parent_id IS NULL {w} ORDER BY nombre")


def subcategorias(solo_activos=True):
    w = "AND activo=1" if solo_activos else ""
    return db.query(f"SELECT * FROM categorias WHERE parent_id IS NOT NULL {w} ORDER BY nombre")


def metodos_pago():
    return db.query("SELECT * FROM metodos_pago WHERE activo=1 ORDER BY id")


def metodo_por_codigo(codigo):
    return db.query("SELECT * FROM metodos_pago WHERE codigo=%s", (codigo,), one=True)


def id_metodo(codigo):
    m = metodo_por_codigo(codigo)
    return m["id"] if m else None
