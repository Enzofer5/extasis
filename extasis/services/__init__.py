"""Servicios: reglas de negocio transaccionales (stock, ventas, cajas, cuentas corrientes)."""


class NegocioError(Exception):
    """Error de regla de negocio (se muestra al usuario)."""
