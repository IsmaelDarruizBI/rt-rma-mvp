"""Traduccion centralizada de errores a respuestas HTTP.

Los routers no atrapan excepciones: las dejan subir. Aqui, en un unico
lugar, cada familia de error se traduce a su status y a un cuerpo con la
misma forma:

    {"error": {"codigo": "...", "mensaje": "..."}}

Correspondencia:

    EntidadPersistidaNoEncontradaError -> 404  (no existe lo pedido)
    EntidadNoEncontradaError           -> 404  (no existe dentro de la Orden)
    PrecondicionInvalidaError          -> 409  (la Orden no admite esto ahora)
    RecursoNoDisponibleError           -> 409  (no alcanza el stock)
    RequestValidationError             -> 422  (el request esta mal formado)
    ConflictoDeEscrituraError          -> 409  (la Orden cambio: recargar)
    ClaveReutilizadaError              -> 422  (clave de idempotencia de
                                               otra operacion, E6)
    PersistenciaNoDisponibleError      -> 503  (sin conexion libre a la base)
    PersistenciaError / RepositoryError-> 500  (fallo de infraestructura)
    AlmacenFotosError                  -> 503  (almacenamiento de fotos)
    CatalogoOrigenNoDisponibleError    -> 503  (no se pudo leer el origen
                                                del catalogo de Ventas)

Las especializaciones de ``PrecondicionInvalidaError`` (Orden cerrada,
toma de otro tecnico, confirmacion requerida) siguen siendo 409, pero
viajan con su propio ``codigo`` para que la UI pueda reaccionar sin
interpretar el mensaje.

El 500 nunca incluye el mensaje original: un fallo de E/S puede filtrar
rutas del servidor, y un catalogo inconsistente puede filtrar IDs y
contenido de catalogos. Se registra el detalle real en el log y al
cliente le llega un texto generico. Los 4xx si llevan el mensaje
funcional del service, porque es exactamente lo que el usuario necesita
leer.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.integraciones.catalogo import CatalogoOrigenNoDisponibleError
from app.repositories import (
    ClaveReutilizadaError,
    ConflictoDeEscrituraError,
    EntidadPersistidaNoEncontradaError,
    PersistenciaNoDisponibleError,
    PersistenciaResultadoInciertoError,
    RepositoryError,
)
from app.services import (
    DomainError,
    EntidadNoEncontradaError,
    PrecondicionInvalidaError,
    RecursoNoDisponibleError,
)
from app.storage import AlmacenFotosError

logger = logging.getLogger(__name__)

CODIGO_PERSISTENCIA = "PERSISTENCIA_ERROR"

MENSAJE_ERROR_INTERNO = "Ocurrió un error interno al procesar los datos."


def _respuesta(codigo: str, mensaje: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"codigo": codigo, "mensaje": mensaje}},
    )


def registrar_manejadores_de_error(application: FastAPI) -> None:
    """Instala los manejadores en la app FastAPI."""

    @application.exception_handler(EntidadPersistidaNoEncontradaError)
    async def _no_encontrada_en_persistencia(
        _: Request,
        error: EntidadPersistidaNoEncontradaError,
    ) -> JSONResponse:
        return _respuesta(
            "NO_ENCONTRADO", str(error), status.HTTP_404_NOT_FOUND
        )

    @application.exception_handler(EntidadNoEncontradaError)
    async def _no_encontrada_en_dominio(
        _: Request,
        error: EntidadNoEncontradaError,
    ) -> JSONResponse:
        return _respuesta(
            "NO_ENCONTRADO", str(error), status.HTTP_404_NOT_FOUND
        )

    @application.exception_handler(PrecondicionInvalidaError)
    async def _precondicion(
        _: Request,
        error: PrecondicionInvalidaError,
    ) -> JSONResponse:
        return _respuesta(error.codigo, str(error), status.HTTP_409_CONFLICT)

    @application.exception_handler(RecursoNoDisponibleError)
    async def _sin_recurso(
        _: Request,
        error: RecursoNoDisponibleError,
    ) -> JSONResponse:
        return _respuesta(
            "RECURSO_NO_DISPONIBLE", str(error), status.HTTP_409_CONFLICT
        )

    @application.exception_handler(DomainError)
    async def _dominio(_: Request, error: DomainError) -> JSONResponse:
        """Cualquier otro error de negocio: tambien es un conflicto."""
        return _respuesta(
            "CONFLICTO_FUNCIONAL", str(error), status.HTTP_409_CONFLICT
        )

    @application.exception_handler(RequestValidationError)
    async def _request_invalido(
        _: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        detalles = "; ".join(
            f"{'.'.join(str(parte) for parte in fallo['loc'][1:])}: "
            f"{fallo['msg']}"
            for fallo in error.errors()
        )
        return _respuesta(
            "REQUEST_INVALIDO",
            f"Los datos enviados no son validos. {detalles}".strip(),
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    @application.exception_handler(AlmacenFotosError)
    async def _almacen_fotos(
        _: Request,
        error: AlmacenFotosError,
    ) -> JSONResponse:
        """El almacenamiento de fotos fallo: se reintenta, no es un 500."""
        logger.warning("Almacenamiento de fotos: %s", error)
        return _respuesta(
            "ALMACENAMIENTO_NO_DISPONIBLE",
            "No se pudo acceder al almacenamiento de fotos. Probá de nuevo.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @application.exception_handler(CatalogoOrigenNoDisponibleError)
    async def _origen_catalogo(
        _: Request,
        error: CatalogoOrigenNoDisponibleError,
    ) -> JSONResponse:
        """El origen del catalogo no respondio: el intento ya quedo
        registrado y la copia no cambio. El mensaje no tiene secretos."""
        logger.warning("Origen del catalogo de equipos: %s", error)
        return _respuesta(
            "CATALOGO_ORIGEN_NO_DISPONIBLE",
            f"{error} Se conserva el catálogo anterior.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @application.exception_handler(PersistenciaResultadoInciertoError)
    async def _resultado_incierto(
        _: Request,
        error: PersistenciaResultadoInciertoError,
    ) -> JSONResponse:
        """M4 (DE6-5): no se sabe si se guardo. No se afirma nada."""
        logger.warning("Resultado incierto: %s", error)
        return _respuesta(
            error.codigo,
            "No se pudo confirmar si la operación se guardó. Reintentala "
            "tal cual (no se duplica) o revisá la Orden antes de hacer otra.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @application.exception_handler(ClaveReutilizadaError)
    async def _clave_reutilizada(
        _: Request,
        error: ClaveReutilizadaError,
    ) -> JSONResponse:
        """E6 (DE6-3): la clave de idempotencia es de otra operacion."""
        return _respuesta(
            error.codigo, str(error), status.HTTP_422_UNPROCESSABLE_ENTITY
        )

    @application.exception_handler(ConflictoDeEscrituraError)
    async def _conflicto_de_escritura(
        _: Request,
        error: ConflictoDeEscrituraError,
    ) -> JSONResponse:
        """E4: una version obsoleta no se guardo. No es un 500."""
        return _respuesta(error.codigo, str(error), status.HTTP_409_CONFLICT)

    @application.exception_handler(PersistenciaNoDisponibleError)
    async def _persistencia_no_disponible(
        _: Request,
        error: PersistenciaNoDisponibleError,
    ) -> JSONResponse:
        """Pool agotado: transitorio, no se hizo nada. No es un conflicto
        de datos (409) ni un fallo interno (500)."""
        logger.warning("Persistencia no disponible: %s", error)
        return _respuesta(
            error.codigo,
            "El servicio está ocupado y no se guardó nada. Probá de nuevo "
            "en unos segundos.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @application.exception_handler(RepositoryError)
    async def _persistencia(
        _: Request,
        error: RepositoryError,
    ) -> JSONResponse:
        logger.exception("Fallo de persistencia: %s", error)
        return _respuesta(
            CODIGO_PERSISTENCIA,
            MENSAJE_ERROR_INTERNO,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
