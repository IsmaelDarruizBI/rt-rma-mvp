"""Persistencia de Ordenes de Reparacion en archivos JSON.

Una Orden por archivo: ``<directorio>/<orden_id>.json``. La Orden es el
aggregate raiz, asi que su archivo es autocontenido -Detalles, tomas,
ejecuciones, movimientos, pagos, documentos e historial-, salvo los
catalogos, que se referencian por ID.

Solo se persisten los campos almacenados. Los derivados se excluyen
y vuelven a calcularse al cargar.

ESCRITURAS OBSOLETAS (E4)
-------------------------
El historial de la Orden es append-only: cada comando le agrega pasos y
nunca le quita. Eso lo vuelve un control de version que ya esta en el
JSON -sin campo nuevo ni migracion-: una Orden solo se guarda si el
historial persistido es un prefijo del que llega. Si otra operacion
guardo entre la lectura y esta escritura, el persistido tiene pasos que
la version que llega no conoce, y se rechaza con
``ConflictoDeEscrituraError`` en vez de pisarlos. Una Orden ya cerrada
en el almacenamiento (entregada o devuelta a Gestion RT) tampoco se
sobrescribe con otra cosa. La comprobacion y el reemplazo ocurren dentro
del mismo ``acceso_exclusivo``.
"""

from pathlib import Path

from pydantic import ValidationError

from app.domain.models import OrdenReparacion
from app.repositories.exceptions import (
    ConflictoDeEscrituraError,
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
)

from .base import (
    acceso_exclusivo,
    asegurar_directorio,
    escribir_json_atomico,
    leer_json,
)


class JsonOrdenReparacionRepository:
    """Implementa ``OrdenReparacionRepository`` sobre el filesystem."""

    def __init__(self, directorio: Path) -> None:
        self._directorio = asegurar_directorio(Path(directorio))

    @property
    def directorio(self) -> Path:
        """Directorio donde viven los archivos de Orden."""
        return self._directorio

    def _ruta_de(self, orden_id: str) -> Path:
        return self._directorio / f"{orden_id}.json"

    def obtener(self, orden_id: str) -> OrdenReparacion:
        """Carga la Orden desde su archivo."""
        ruta = self._ruta_de(orden_id)
        if not ruta.is_file():
            raise EntidadPersistidaNoEncontradaError(
                f"No existe la Orden {orden_id}"
            )
        return self._validar(leer_json(ruta), ruta)

    def guardar(self, orden: OrdenReparacion) -> None:
        """Crea o reemplaza el archivo de la Orden.

        Idempotente: la ruta depende solo del ID, asi que guardar dos
        veces la misma Orden nunca duplica archivos.

        Los campos derivados (``total``, ``saldo``, ``estado_pago``,
        ``puntaje_total``, ``resumen_pago.pagado``) NO se escriben: no
        son fuente de verdad y persistirlos crearia una segunda copia
        que podria quedar desincronizada de los Detalles y los Pagos.
        Se recalculan solos al reconstruir el modelo.

        Rechaza una version obsoleta (ver el docstring del modulo).
        """
        ruta = self._ruta_de(orden.id)
        with acceso_exclusivo():
            self._exigir_sin_escrituras_intermedias(ruta, orden)
            escribir_json_atomico(
                ruta,
                orden.model_dump(mode="json", exclude_computed_fields=True),
            )

    def _exigir_sin_escrituras_intermedias(
        self,
        ruta: Path,
        orden: OrdenReparacion,
    ) -> None:
        """La version persistida es la que esta Orden extiende."""
        if not ruta.is_file():
            return
        persistida = self._validar(leer_json(ruta), ruta)
        if persistida.esta_cerrada and persistida != orden:
            raise ConflictoDeEscrituraError(
                f"La Orden {orden.id} ya esta cerrada: no se sobrescribe. "
                "Recarga la Orden para ver su estado actual."
            )
        previo = persistida.historial
        if orden.historial[: len(previo)] != previo:
            raise ConflictoDeEscrituraError(
                f"La Orden {orden.id} cambio mientras se procesaba esta "
                "operacion: no se guardo para no pisar el cambio. Recarga "
                "la Orden y volve a intentarlo."
            )

    def listar(self) -> list[OrdenReparacion]:
        """Carga todas las Ordenes, ordenadas por ID."""
        ordenes = [
            self._validar(leer_json(ruta), ruta)
            for ruta in sorted(self._directorio.glob("*.json"))
        ]
        return sorted(ordenes, key=lambda orden: orden.id)

    @staticmethod
    def _validar(datos: object, ruta: Path) -> OrdenReparacion:
        """Reconstruye la Orden con el contrato Pydantic del dominio."""
        try:
            return OrdenReparacion.model_validate(datos)
        except ValidationError as error:
            raise PersistenciaError(
                f"El archivo {ruta} no representa una Orden valida: {error}"
            ) from error
