"""Motor comun de sincronizacion de copias de origenes externos (bloque C).

Lo usa la copia del catalogo de Ventas y lo usara la de los Productos de
Gestion RT. Cada copia aporta una ``CopiaSincronizable``: como reservar,
leer, validar, aplicar y finalizar. El motor fija el ciclo, igual para
todas:

1. RESERVAR: una sola sincronizacion por copia entre todas las instancias.
   Con otra en curso: ``SincronizacionEnCursoError`` (409), sin leer nada.
   La reserva lleva un secreto aleatorio (``propietario``): solo esta
   sincronizacion puede escribir la copia y finalizar el intento (M3).
2. LEER el origen FUERA de toda transaccion y validarlo.
   - No responde (``OrigenNoDisponibleError``): FALLIDA y el mismo error.
   - Datos no confiables (``OrigenInvalidoError`` o un rechazo propio de
     la copia): RECHAZADA y el rechazo de la copia (409).
   - Cualquier otro error: FALLIDA y el mismo error.
3. APLICAR en una sola operacion atomica (la copia y el intento EXITOSA).
   Si falla: nada cambio; se finaliza FALLIDA en otra operacion y el error
   sigue.

En todos los casos la ultima copia valida se conserva: solo la aplicacion
exitosa la cambia. Si finalizar un intento fallido tambien falla (la base
no responde), se registra en el log y sigue el error original: la reserva
vence sola y la sincronizacion siguiente la marca INTERRUMPIDA.
"""

import logging
import secrets
from datetime import timedelta
from typing import Protocol, TypeVar

from app.domain.models import ReservaSincronizacion, ResultadoSincronizacion
from app.integraciones.origen import (
    OrigenInvalidoError,
    OrigenNoDisponibleError,
)
from app.repositories import ReservaOcupadaError, ReservaPerdidaError
from app.services import SincronizacionEnCursoError, nuevo_id

logger = logging.getLogger(__name__)

L = TypeVar("L")
R = TypeVar("R", covariant=True)

MENSAJE_LECTURA = "Falló la lectura del origen: se conserva la copia anterior."
MENSAJE_RESERVA_PERDIDA = (
    "La sincronización tardó más que su reserva y otra la tomó: no se "
    "aplicó nada y se conserva la copia vigente."
)
MENSAJE_APLICACION = (
    "No se pudo aplicar la sincronización: se conserva la copia anterior."
)


class CopiaSincronizable(Protocol[L, R]):
    """Lo que el motor necesita de una copia."""

    # Para el 409 de una sincronizacion en curso.
    mensaje_en_curso: str
    # Errores propios de la copia que significan «datos no confiables».
    rechazos: tuple[type[Exception], ...]

    def rechazo(self, mensaje: str) -> Exception:
        """El error de la copia para datos no confiables (409)."""
        ...

    def reservar(
        self, *, id: str, propietario: str, duracion: timedelta
    ) -> ReservaSincronizacion: ...

    def leer(self) -> L: ...

    def validar(self, lectura: L) -> None: ...

    def aplicar(self, reserva: ReservaSincronizacion, lectura: L) -> R:
        """La copia y el intento EXITOSA, atomicamente; devuelve el
        intento."""
        ...

    def finalizar(
        self,
        reserva: ReservaSincronizacion,
        resultado: ResultadoSincronizacion,
        mensaje: str,
        lectura: L | None,
    ) -> None:
        """El intento FALLIDA o RECHAZADA, sin tocar la copia."""
        ...


def ejecutar_sincronizacion(
    copia: CopiaSincronizable[L, R], *, duracion: timedelta
) -> R:
    """Sincroniza ``copia`` con su origen (ciclo del modulo)."""
    try:
        reserva = copia.reservar(
            id=nuevo_id("SINC"),
            propietario=secrets.token_hex(32),
            duracion=duracion,
        )
    except ReservaOcupadaError:
        raise SincronizacionEnCursoError(copia.mensaje_en_curso) from None

    lectura: L | None = None
    try:
        lectura = copia.leer()
        copia.validar(lectura)
    except OrigenNoDisponibleError as error:
        _finalizar(
            copia,
            reserva,
            ResultadoSincronizacion.FALLIDA,
            str(error),
            lectura,
        )
        raise
    except (OrigenInvalidoError, *copia.rechazos) as error:
        _finalizar(
            copia,
            reserva,
            ResultadoSincronizacion.RECHAZADA,
            str(error),
            lectura,
        )
        raise copia.rechazo(str(error)) from error
    except BaseException:
        _finalizar(
            copia,
            reserva,
            ResultadoSincronizacion.FALLIDA,
            MENSAJE_LECTURA,
            lectura,
        )
        raise

    try:
        return copia.aplicar(reserva, lectura)
    except ReservaPerdidaError:
        # Tardo mas que su reserva y otra sincronizacion la tomo: no se
        # aplico nada y el intento ya no es nuestro (quedo INTERRUMPIDA).
        raise SincronizacionEnCursoError(MENSAJE_RESERVA_PERDIDA) from None
    except BaseException:
        _finalizar(
            copia,
            reserva,
            ResultadoSincronizacion.FALLIDA,
            MENSAJE_APLICACION,
            lectura,
        )
        raise


def _finalizar(
    copia: CopiaSincronizable[L, R],
    reserva: ReservaSincronizacion,
    resultado: ResultadoSincronizacion,
    mensaje: str,
    lectura: L | None,
) -> None:
    """Finaliza un intento fallido sin tapar el error que lo causo."""
    try:
        copia.finalizar(reserva, resultado, mensaje, lectura)
    except ReservaPerdidaError:
        logger.warning(
            "El intento %s ya no es de esta sincronizacion (su reserva vencio "
            "y otra la tomo): no se registra como %s.",
            reserva.id,
            resultado.value,
        )
    except Exception:
        logger.exception(
            "No se pudo registrar el intento %s como %s: la reserva vence "
            "sola y la sincronizacion siguiente la marca INTERRUMPIDA.",
            reserva.id,
            resultado.value,
        )
