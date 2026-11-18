"""Errores comunes de los origenes externos de solo lectura.

Cada copia de un origen externo (el catalogo de Ventas hoy; los Productos
de Gestion RT despues) tiene sus propios errores, que heredan de estos. El
motor de sincronizacion (``application/sincronizacion_origen.py``) solo
conoce estos dos: no sabe de que origen se trata.

El mensaje es apto para mostrar: nunca incluye tokens, credenciales ni el
contenido de la respuesta del origen.
"""


class OrigenExternoError(Exception):
    """El origen no pudo dar un resultado confiable."""


class OrigenNoDisponibleError(OrigenExternoError):
    """No se pudo leer: red, permisos, credencial o servicio caido."""


class OrigenInvalidoError(OrigenExternoError):
    """Se leyo, pero la estructura no es la esperada."""
