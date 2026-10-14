"""Errores de dominio de los casos de uso del MVP.

Cuando una precondicion del proceso no se cumple, los services fallan de
forma explicita en vez de inventar un comportamiento. Los caminos de
PROC-REP V1.3 que el MVP todavia no implementa (retrabajo, cancelacion)
tampoco tienen un atajo: simplemente no hay comando que los dispare.

Cada error declara su ``codigo``: la API lo devuelve tal cual en
``{"error": {"codigo": ...}}`` para que la UI distinga, por ejemplo, una
Orden cerrada de una toma ajena sin interpretar el mensaje.
"""


class DomainError(Exception):
    """Error de negocio del dominio RMA."""

    codigo = "CONFLICTO_FUNCIONAL"


class PrecondicionInvalidaError(DomainError):
    """La Orden no esta en condiciones de recibir esta operacion."""

    codigo = "PRECONDICION_INVALIDA"


class OrdenCerradaError(PrecondicionInvalidaError):
    """La Orden ya termino su proceso: solo se puede consultar (E1)."""

    codigo = "ORDEN_CERRADA"


class TomaDeOtroTecnicoError(PrecondicionInvalidaError):
    """La toma activa pertenece a otro tecnico (E2, BR-REP-018)."""

    codigo = "TOMA_DE_OTRO_TECNICO"


class ConfirmacionRequeridaError(PrecondicionInvalidaError):
    """La operacion exige una confirmacion explicita que no llego (E3)."""

    codigo = "CONFIRMACION_REQUERIDA"


class RecursoNoDisponibleError(DomainError):
    """No hay disponibilidad suficiente para completar la operacion."""

    codigo = "RECURSO_NO_DISPONIBLE"


class EntidadNoEncontradaError(DomainError):
    """La entidad referenciada no existe en la Orden o en el catalogo."""

    codigo = "NO_ENCONTRADO"
