"""Contrato de persistencia de Ordenes de Reparacion.

Define QUE necesita la aplicacion, nunca COMO se guarda. La
implementacion JSON vive en ``app.storage.json``; manana puede ser
Cloud Storage o una base de datos sin que el dominio ni los services se
enteren.

Consultas dedicadas (E2, ``docs/postgresql/e2-consultas-dedicadas.md``):
el repository filtra por datos persistidos; las reglas (situacion,
autorizacion, reservas pendientes) siguen en los services. Toda lista se
devuelve ordenada por numero de Orden ascendente, como ``listar()``.
"""

from collections.abc import Collection
from typing import Protocol, runtime_checkable

from app.domain.models import OrdenReparacion

# Numero de Orden: ``OR-000001``. Es el que una persona lee y dicta,
# distinto de los IDs tecnicos de las entidades internas.
PREFIJO_CODIGO_ORDEN = "OR"
DIGITOS_CODIGO_ORDEN = 6


@runtime_checkable
class OrdenReparacionRepository(Protocol):
    """Acceso a las Ordenes persistidas."""

    def obtener(self, orden_id: str) -> OrdenReparacion:
        """Devuelve la Orden.

        Lanza ``EntidadPersistidaNoEncontradaError`` si no existe.
        """
        ...

    def guardar(self, orden: OrdenReparacion) -> None:
        """Crea la Orden o reemplaza la version guardada.

        Es idempotente: guardar dos veces la misma Orden deja una sola
        copia.

        Nunca pisa en silencio otra escritura (E4): si la version guardada
        cambio desde que se leyo la que llega -o ya esta cerrada-, lanza
        ``ConflictoDeEscrituraError`` y no escribe nada.

        PostgreSQL es mas estricto (QA-A2-H1): una Orden que ya existe solo
        se guarda si viene de ``obtener_para_modificar`` en esta misma
        transaccion; si no, ``PersistenciaError``. JSON lo exigira en B4.
        """
        ...

    def listar(self) -> list[OrdenReparacion]:
        """Todas las Ordenes, por numero de Orden ascendente.

        Solo para el listado general, las evidencias de faltante y las
        pruebas: los demas casos de uso usan una consulta dedicada.
        """
        ...

    # --- Consultas dedicadas (E2) ---------------------------------------

    def obtener_para_modificar(self, orden_id: str) -> OrdenReparacion:
        """La Orden que el comando va a modificar, sin que nadie mas la
        modifique hasta el final de la transaccion.

        Exige una transaccion en curso: sin ella lanza
        ``PersistenciaError`` y no lee nada. Si no existe:
        ``EntidadPersistidaNoEncontradaError``. No verifica que la Orden
        este abierta: esa regla es del caso de uso.
        """
        ...

    def reservar_codigo(self) -> str:
        """Numero de una Orden nueva (``OR-NNNNNN``).

        Exige una transaccion en curso, y quien lo pide guarda la Orden
        con ese numero dentro de la misma transaccion. Nunca devuelve un
        numero ya guardado; no garantiza correlatividad (un alta revertida
        puede dejar un hueco). Los IDs que no siguen el patron no cuentan.
        """
        ...

    def listar_abiertas(self) -> list[OrdenReparacion]:
        """Las Ordenes no cerradas (``not esta_cerrada``): ni ENTREGADAS
        ni devueltas a Gestion RT. Las CANCELADAS se incluyen."""
        ...

    def listar_por_dni_cliente(self, dni: str) -> list[OrdenReparacion]:
        """Las Ordenes cuyo cliente tiene exactamente ese DNI, ya
        normalizado por quien llama. No agrupa ni elige clientes.

        ``dni`` no puede ser ``None``: ``ValueError``.
        """
        ...

    def listar_con_reservas(
        self, insumo_ids: Collection[str] | None = None
    ) -> list[OrdenReparacion]:
        """Ordenes candidatas para calcular reservas pendientes (de esos
        insumos, si se indican).

        Garantiza:
        - toda Orden con alguna RESERVA pendiente esta incluida;
        - ninguna Orden sin RESERVA (de esos insumos) esta incluida.

        Puede incluir Ordenes cuyas reservas ya se consumieron o
        liberaron: cuales siguen pendientes lo decide el service
        (``cantidad_pendiente``), nunca el repository. Asi JSON devuelve
        toda Orden con alguna RESERVA y PostgreSQL puede limitarse a las
        pendientes del libro de inventario.

        Una coleccion vacia no devuelve nada. ``insumo_ids`` como ``str``
        (un solo id, no una coleccion): ``ValueError``.
        """
        ...

    def listar_con_movimientos(
        self, insumo_id: str | None = None
    ) -> list[OrdenReparacion]:
        """Las Ordenes con algun movimiento de insumo (de ese insumo, si
        se indica). El orden por numero es parte del contrato: el
        historial desempata fechas iguales por el orden de llegada."""
        ...

    def claves_de_fotos(self) -> frozenset[str]:
        """Las claves de objeto de todas las fotos registradas, de
        cualquier Orden (abierta o cerrada)."""
        ...
