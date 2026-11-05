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

CONSULTAS DEDICADAS (E2)
------------------------
Cada consulta lee todas las Ordenes y filtra por datos persistidos, en el
orden de ``listar()``: el objetivo es el contrato, no el rendimiento
(DE-4). ``obtener_para_modificar`` y ``reservar_codigo`` exigen la
transaccion de la unidad de trabajo que el contexto vincula con
``exigir_transaccion_con``; sin vinculo, fallan en vez de leer sin
proteccion. La exclusion la da el lock de proceso que retiene esa
transaccion.
"""

import re
from collections.abc import Callable, Collection
from pathlib import Path

from pydantic import ValidationError

from app.domain.models import OrdenReparacion, TipoMovimientoInsumo
from app.repositories.exceptions import (
    ConflictoDeEscrituraError,
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
)
from app.repositories.ordenes import (
    DIGITOS_CODIGO_ORDEN,
    PREFIJO_CODIGO_ORDEN,
)

from .base import (
    acceso_exclusivo,
    asegurar_directorio,
    escribir_json_atomico,
    leer_json,
)

_PATRON_CODIGO = re.compile(rf"^{PREFIJO_CODIGO_ORDEN}-(\d+)$")


class JsonOrdenReparacionRepository:
    """Implementa ``OrdenReparacionRepository`` sobre el filesystem."""

    def __init__(
        self,
        directorio: Path,
        en_transaccion: Callable[[], bool] | None = None,
    ) -> None:
        self._directorio = asegurar_directorio(Path(directorio))
        self._en_transaccion = en_transaccion

    def exigir_transaccion_con(
        self, en_transaccion: Callable[[], bool]
    ) -> None:
        """Vincula la unidad de trabajo cuya transaccion exigen las
        lecturas para modificar (lo hace el contexto, DE-2)."""
        self._en_transaccion = en_transaccion

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

    # --- Consultas dedicadas (E2) ---------------------------------------

    def obtener_para_modificar(self, orden_id: str) -> OrdenReparacion:
        """``obtener`` dentro de la transaccion en curso."""
        self._exigir_transaccion("Leer una Orden para modificarla")
        return self.obtener(orden_id)

    def reservar_codigo(self) -> str:
        """El maximo numero persistido mas uno (sin huecos en JSON)."""
        self._exigir_transaccion("Reservar un numero de Orden")
        maximo = 0
        for orden in self.listar():
            encontrado = _PATRON_CODIGO.match(orden.id)
            if encontrado:
                maximo = max(maximo, int(encontrado.group(1)))
        numero = f"{maximo + 1:0{DIGITOS_CODIGO_ORDEN}d}"
        return f"{PREFIJO_CODIGO_ORDEN}-{numero}"

    def listar_abiertas(self) -> list[OrdenReparacion]:
        return [orden for orden in self.listar() if not orden.esta_cerrada]

    def listar_por_dni_cliente(self, dni: str) -> list[OrdenReparacion]:
        # Con None coincidirian los clientes sin DNI (en SQL, ninguno).
        if dni is None:
            raise ValueError("El DNI a buscar no puede ser None.")
        return [
            orden
            for orden in self.listar()
            if orden.cliente is not None and orden.cliente.dni == dni
        ]

    def listar_con_reservas(
        self, insumo_ids: Collection[str] | None = None
    ) -> list[OrdenReparacion]:
        """Toda Orden con alguna RESERVA (de esos insumos): el conjunto
        candidato mas amplio que admite el contrato."""
        if isinstance(insumo_ids, str):
            # Un str tambien es Collection[str]: se tomaria letra por letra.
            raise ValueError(
                "insumo_ids es una coleccion de IDs, no un str: "
                f"usar [{insumo_ids!r}]."
            )
        buscados = None if insumo_ids is None else frozenset(insumo_ids)
        return [
            orden
            for orden in self.listar()
            if any(
                movimiento.tipo is TipoMovimientoInsumo.RESERVA
                and (buscados is None or movimiento.insumo_id in buscados)
                for movimiento in orden.movimientos_insumo
            )
        ]

    def listar_con_movimientos(
        self, insumo_id: str | None = None
    ) -> list[OrdenReparacion]:
        return [
            orden
            for orden in self.listar()
            if any(
                insumo_id is None or movimiento.insumo_id == insumo_id
                for movimiento in orden.movimientos_insumo
            )
        ]

    def claves_de_fotos(self) -> frozenset[str]:
        return frozenset(
            foto.objeto for orden in self.listar() for foto in orden.fotos
        )

    def _exigir_transaccion(self, operacion: str) -> None:
        if self._en_transaccion is None or not self._en_transaccion():
            raise PersistenciaError(
                f"{operacion} exige una transaccion en curso: el caso de "
                "uso debe abrirla con contexto.transaccion()."
            )

    @staticmethod
    def _validar(datos: object, ruta: Path) -> OrdenReparacion:
        """Reconstruye la Orden con el contrato Pydantic del dominio."""
        try:
            return OrdenReparacion.model_validate(datos)
        except ValidationError as error:
            raise PersistenciaError(
                f"El archivo {ruta} no representa una Orden valida: {error}"
            ) from error
