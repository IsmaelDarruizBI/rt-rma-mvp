"""Traza de lo que le fue pasando a la Orden.

Dos cosas distintas dejan huella y no deben confundirse:

- el recorrido SECUENCIAL por los nodos del Business Process
  (``PROC-REP-*``), que avanza el flujo;
- las capacidades TRANSVERSALES que se ejecutan sobre la Orden sin
  ocupar un nodo del proceso (``ACC-REP-*``), como Registrar Pago
  (BR-REP-017). Ocurren en cualquier momento y no mueven el flujo.

Por eso cada entrada declara que clase de referencia guarda.
"""

from datetime import datetime

from pydantic import AliasChoices, BaseModel, Field

from .enums import RolUsuario, TipoReferenciaHistorial


class HistorialWorkflow(BaseModel):
    """Un evento registrado de la Orden.

    ``referencia_id`` conserva el ID funcional tal como esta definido en
    ``business/`` o en la trazabilidad (``PROC-REP-185``,
    ``ACC-REP-020``), sin enum ni renombramiento, para no duplicar esa
    fuente de verdad.

    RETROCOMPATIBILIDAD: el campo acepta tambien el nombre historico
    ``process_id`` al construirse y al validar JSON, asi que las Ordenes
    ya persistidas se cargan sin migracion y quedan como PROCESS_NODE
    (el default). La propiedad ``process_id`` sigue disponible para leer,
    y devuelve ``None`` cuando la entrada es una accion transversal: un
    consumidor que solo entienda nodos no confunde una cosa con la otra.
    Al serializar se escribe siempre ``referencia_id``.
    """

    tipo_referencia: TipoReferenciaHistorial = (
        TipoReferenciaHistorial.PROCESS_NODE
    )
    referencia_id: str = Field(
        validation_alias=AliasChoices("referencia_id", "process_id"),
    )
    accion: str
    fecha: datetime

    usuario_id: str | None = None
    # Rol con el que el usuario quedo habilitado para la accion (DC27A,
    # DEC-MI-12). Vacio en lo anterior y en los pasos del sistema.
    rol: RolUsuario | None = None
    reparacion_detail_id: str | None = None
    ejecucion_id: str | None = None
    pago_id: str | None = None
    observacion: str | None = None

    @property
    def process_id(self) -> str | None:
        """El ID solo cuando la entrada es un nodo del proceso."""
        if self.tipo_referencia is TipoReferenciaHistorial.PROCESS_NODE:
            return self.referencia_id
        return None

    @property
    def es_accion_funcional(self) -> bool:
        """True si es una capacidad transversal, no un paso del flujo."""
        return (
            self.tipo_referencia is TipoReferenciaHistorial.FUNCTIONAL_ACTION
        )
