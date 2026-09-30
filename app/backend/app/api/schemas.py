"""DTOs HTTP del MVP.

No reemplazan a los modelos de dominio ni los sustituyen adentro: son la
forma en que la Orden sale y entra POR HTTP. Por eso pueden incluir
cosas que el dominio deriva y la persistencia no guarda -``total``,
``saldo``, ``estado_pago``, ``puntaje_total``, ``pagado``-: persistir y
representar son dos cosas distintas, y al frontend le sirve recibirlas
calculadas.

Lo que NO exponen es la persistencia: ninguna ruta de archivo, ningun
detalle del storage JSON, ningun nombre de repository.

Los ``Decimal`` viajan como string en el JSON (comportamiento de
Pydantic v2 en modo JSON) para no perder precision en el camino; el
frontend los convierte a numero solo para mostrarlos.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.application import (
    AccionDisponible,
    InsumoPrevisto,
    PasoProgreso,
)
from app.domain.models import (
    Cliente,
    EjecucionReparacion,
    Equipo,
    EstacionTrabajo,
    EstadoControl,
    EstadoEjecucion,
    EstadoPago,
    EstadoReparacionDetail,
    EstadoTomaOrden,
    EstadoWorkflow,
    HistorialWorkflow,
    InsumoUtilizado,
    OrdenReparacion,
    OrigenOrden,
    ReparacionDetail,
    RolUsuario,
    TipoPago,
    TipoReferenciaHistorial,
    TipoReparacion,
    TomaOrden,
    Usuario,
)
from app.services import nuevo_id

# --- Catalogos ---------------------------------------------------------


class TipoReparacionOut(BaseModel):
    """Tipo de Reparacion ofrecido."""

    id: str
    nombre: str
    precio: Decimal
    puntaje: int
    garantia_dias: int
    activo: bool

    @classmethod
    def desde_dominio(cls, tipo: TipoReparacion) -> "TipoReparacionOut":
        return cls(**tipo.model_dump())


class EstacionOut(BaseModel):
    """Estacion de trabajo."""

    id: str
    nombre: str
    activa: bool

    @classmethod
    def desde_dominio(cls, estacion: EstacionTrabajo) -> "EstacionOut":
        return cls(**estacion.model_dump())


class UsuarioOut(BaseModel):
    """Usuario operativo. Alimenta el selector de actor DEMO."""

    id: str
    nombre: str
    rol: RolUsuario
    activo: bool

    @classmethod
    def desde_dominio(cls, usuario: Usuario) -> "UsuarioOut":
        return cls(**usuario.model_dump())


# --- Entrada de comandos ------------------------------------------------


class ClienteIn(BaseModel):
    """Datos minimos del cliente que deja el equipo."""

    nombre: str = Field(min_length=1)
    telefono: str = Field(min_length=1)
    email: str | None = None
    id: str | None = None

    def a_dominio(self) -> Cliente:
        """El MVP no tiene padron de clientes: si no viene ID, se crea."""
        return Cliente(
            id=self.id or nuevo_id("CLI"),
            nombre=self.nombre,
            telefono=self.telefono,
            email=self.email,
        )


class EquipoIn(BaseModel):
    """Datos minimos del equipo recibido."""

    marca: str = Field(min_length=1)
    modelo: str = Field(min_length=1)
    falla_reportada: str = Field(min_length=1)
    imei: str | None = None
    numero_serie: str | None = None
    id: str | None = None

    def a_dominio(self) -> Equipo:
        return Equipo(
            id=self.id or nuevo_id("EQP"),
            marca=self.marca,
            modelo=self.modelo,
            falla_reportada=self.falla_reportada,
            imei=self.imei,
            numero_serie=self.numero_serie,
        )


class CrearOrdenIn(BaseModel):
    """``POST /api/orders`` (ACT-RECEP)."""

    usuario_id: str = Field(min_length=1)
    cliente: ClienteIn
    equipo: EquipoIn


class DefinirReparacionIn(BaseModel):
    """``POST /api/orders/{id}/details`` (ACT-RECEP)."""

    usuario_id: str = Field(min_length=1)
    tipo_reparacion_id: str = Field(min_length=1)
    observaciones: str | None = None


class EncolarIn(BaseModel):
    """``POST /api/orders/{id}/queue`` (ACT-COORD)."""

    usuario_id: str = Field(min_length=1)
    prioridad: int = Field(ge=0)


class TomarIn(BaseModel):
    """``POST /api/orders/{id}/take`` (ACT-TECH)."""

    usuario_id: str = Field(min_length=1)
    estacion_id: str = Field(min_length=1)


class IniciarDetalleIn(BaseModel):
    """``POST /api/orders/{id}/details/{detalle_id}/start`` (ACT-TECH)."""

    usuario_id: str = Field(min_length=1)


class InsumoUtilizadoIn(BaseModel):
    """Insumo realmente usado, confirmado por el tecnico."""

    insumo_id: str = Field(min_length=1)
    cantidad: Decimal = Field(gt=0)

    def a_dominio(self) -> InsumoUtilizado:
        return InsumoUtilizado(
            insumo_id=self.insumo_id, cantidad=self.cantidad
        )


class CompletarEjecucionIn(BaseModel):
    """``POST /api/orders/{id}/executions/{ejecucion_id}/complete``."""

    usuario_id: str = Field(min_length=1)
    insumos_utilizados: list[InsumoUtilizadoIn] = Field(default_factory=list)
    observaciones: str | None = None


class AprobarControlIn(BaseModel):
    """``POST /api/orders/{id}/control/approve`` (ACT-RECEP)."""

    usuario_id: str = Field(min_length=1)
    observaciones: str | None = None


class NotificarIn(BaseModel):
    """``POST /api/orders/{id}/notify`` (ACT-RECEP)."""

    usuario_id: str = Field(min_length=1)


class PagoIn(BaseModel):
    """``POST /api/orders/{id}/payments`` (capacidad transversal)."""

    usuario_id: str = Field(min_length=1)
    monto: Decimal = Field(gt=0)
    metodo: str = Field(min_length=1)


class EntregarIn(BaseModel):
    """``POST /api/orders/{id}/deliver`` (ACT-ADMIN)."""

    usuario_id: str = Field(min_length=1)


# --- Salida ------------------------------------------------------------


class ClienteOut(BaseModel):
    id: str
    nombre: str
    telefono: str
    email: str | None = None


class EquipoOut(BaseModel):
    id: str
    marca: str
    modelo: str
    falla_reportada: str
    imei: str | None = None
    numero_serie: str | None = None


class InsumoPrevistoOut(BaseModel):
    """Insumo que el Tipo de Reparacion del Detalle preve consumir.

    Es informacion de presentacion resuelta al leer, no un campo del
    dominio: ``ReparacionDetail`` guarda solo ``tipo_reparacion_id``. La
    UI la necesita para proponerle al tecnico que confirmar en
    PROC-REP-200 sin tener que conocer ningun ID de catalogo.
    """

    insumo_id: str
    codigo: str
    nombre: str
    cantidad_prevista: Decimal

    @classmethod
    def desde_aplicacion(
        cls,
        previsto: InsumoPrevisto,
    ) -> "InsumoPrevistoOut":
        return cls(
            insumo_id=previsto.insumo_id,
            codigo=previsto.codigo,
            nombre=previsto.nombre,
            cantidad_prevista=previsto.cantidad_prevista,
        )


class DetalleOut(BaseModel):
    """Detalle de Reparacion con su snapshot comercial."""

    id: str
    tipo_reparacion_id: str
    tipo_reparacion_nombre: str
    precio: Decimal
    puntaje: int
    garantia_dias: int
    estado: EstadoReparacionDetail
    control_estado: EstadoControl
    control_usuario_id: str | None = None
    control_fecha: datetime | None = None
    control_observaciones: str | None = None
    observaciones: str | None = None
    insumos_previstos: list[InsumoPrevistoOut] = Field(default_factory=list)

    @classmethod
    def desde_dominio(
        cls,
        detalle: ReparacionDetail,
        previstos: Sequence[InsumoPrevisto] = (),
        tipo_reparacion_nombre: str | None = None,
    ) -> "DetalleOut":
        return cls(
            **detalle.model_dump(),
            tipo_reparacion_nombre=(
                tipo_reparacion_nombre or detalle.tipo_reparacion_id
            ),
            insumos_previstos=[
                InsumoPrevistoOut.desde_aplicacion(previsto)
                for previsto in previstos
            ],
        )


class TomaOut(BaseModel):
    id: str
    usuario_id: str
    estacion_id: str
    estado: EstadoTomaOrden
    inicio: datetime
    fin: datetime | None = None

    @classmethod
    def desde_dominio(cls, toma: TomaOrden) -> "TomaOut":
        return cls(**toma.model_dump())


class InsumoUtilizadoOut(BaseModel):
    insumo_id: str
    cantidad: Decimal


class EjecucionOut(BaseModel):
    id: str
    reparacion_detail_id: str
    toma_orden_id: str
    usuario_id: str
    estado: EstadoEjecucion
    inicio: datetime
    fin: datetime | None = None
    insumos_utilizados: list[InsumoUtilizadoOut] = Field(
        default_factory=list
    )
    observaciones: str | None = None

    @classmethod
    def desde_dominio(cls, ejecucion: EjecucionReparacion) -> "EjecucionOut":
        return cls(**ejecucion.model_dump())


class PagoOut(BaseModel):
    """Pago registrado.

    ``tipo_pago`` (ANTICIPO / PAGO) y ``metodo`` (EFECTIVO,
    TRANSFERENCIA, ...) son dimensiones distintas.
    """

    id: str
    monto: Decimal
    tipo_pago: TipoPago
    metodo: str
    usuario_id: str
    fecha: datetime


class DocumentoOut(BaseModel):
    generado: bool
    fecha_generacion: datetime | None = None


class DocumentosOut(BaseModel):
    comprobante_recepcion: DocumentoOut
    comprobante_final: DocumentoOut
    garantia_reparacion: DocumentoOut


class ResumenComercialOut(BaseModel):
    """Situacion comercial derivada. Nunca se persiste: se calcula."""

    total: Decimal
    pagado: Decimal
    saldo: Decimal
    estado_pago: EstadoPago
    puntaje_total: int


class HistorialOut(BaseModel):
    """Un evento registrado de la Orden.

    ``tipo_referencia`` distingue las dos clases que conviven en el
    historial:

        PROCESS_NODE      -> PROC-REP-*, paso del recorrido
        FUNCTIONAL_ACTION -> ACC-REP-*, capacidad transversal

    ``process_id`` se mantiene por compatibilidad con los consumidores
    que solo entienden nodos, y llega en ``null`` cuando la entrada es
    una accion transversal. Lo que siempre viene es ``referencia_id``.
    """

    tipo_referencia: TipoReferenciaHistorial
    referencia_id: str
    accion: str
    fecha: datetime
    usuario_id: str | None = None
    reparacion_detail_id: str | None = None
    ejecucion_id: str | None = None
    pago_id: str | None = None
    observacion: str | None = None
    process_id: str | None = None

    @classmethod
    def desde_dominio(cls, paso: HistorialWorkflow) -> "HistorialOut":
        return cls(
            **paso.model_dump(),
            process_id=paso.process_id,
        )


class PasoProgresoOut(BaseModel):
    """Nodo de HP-REP-001 y si la Orden ya paso por el."""

    process_id: str
    etiqueta: str
    alcanzado: bool

    @classmethod
    def desde_dominio(cls, paso: PasoProgreso) -> "PasoProgresoOut":
        return cls(
            process_id=paso.process_id,
            etiqueta=paso.etiqueta,
            alcanzado=paso.alcanzado,
        )


class AccionOut(BaseModel):
    """Accion humana que la Orden admite ahora.

    ``roles`` lista TODOS los actores autorizados; puede haber mas de uno
    cuando el nodo declara ``actores_alternativos`` en PROC-REP V1.3.

    Una lista vacia significa que el negocio todavia no definio el actor
    (Registrar Pago, BR-REP-017), no que cualquiera pueda: el backend
    igual exige usuario activo.
    """

    codigo: str
    etiqueta: str
    roles: list[RolUsuario] = Field(default_factory=list)
    detalle_id: str | None = None
    ejecucion_id: str | None = None

    @classmethod
    def desde_dominio(cls, accion: AccionDisponible) -> "AccionOut":
        return cls(
            codigo=accion.codigo,
            etiqueta=accion.etiqueta,
            roles=list(accion.roles),
            detalle_id=accion.detalle_id,
            ejecucion_id=accion.ejecucion_id,
        )


class OrdenResumenOut(BaseModel):
    """Fila del listado de Ordenes."""

    id: str
    origen: OrigenOrden
    estado_workflow: EstadoWorkflow
    current_process: str
    prioridad: int
    cliente_nombre: str
    equipo: str
    total: Decimal
    saldo: Decimal
    estado_pago: EstadoPago
    created_at: datetime
    updated_at: datetime

    @classmethod
    def desde_dominio(cls, orden: OrdenReparacion) -> "OrdenResumenOut":
        return cls(
            id=orden.id,
            origen=orden.origen,
            estado_workflow=orden.estado_workflow,
            current_process=orden.current_process,
            prioridad=orden.prioridad,
            cliente_nombre=orden.cliente.nombre,
            equipo=f"{orden.equipo.marca} {orden.equipo.modelo}",
            total=orden.total,
            saldo=orden.saldo,
            estado_pago=orden.estado_pago,
            created_at=orden.created_at,
            updated_at=orden.updated_at,
        )


class OrdenOut(BaseModel):
    """La Orden completa tal como la consume el frontend."""

    id: str
    origen: OrigenOrden
    estado_workflow: EstadoWorkflow
    current_process: str
    prioridad: int
    cliente: ClienteOut
    equipo: EquipoOut
    reparaciones_detail: list[DetalleOut]
    tomas: list[TomaOut]
    ejecuciones: list[EjecucionOut]
    pagos: list[PagoOut]
    documentos: DocumentosOut
    resumen: ResumenComercialOut
    historial: list[HistorialOut]
    progreso: list[PasoProgresoOut]
    acciones_disponibles: list[AccionOut]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def desde_dominio(
        cls,
        orden: OrdenReparacion,
        *,
        progreso: list[PasoProgreso],
        acciones: list[AccionDisponible],
        insumos_previstos: Mapping[str, Sequence[InsumoPrevisto]]
        | None = None,
        nombres_de_tipo: Mapping[str, str] | None = None,
    ) -> "OrdenOut":
        return cls(
            id=orden.id,
            origen=orden.origen,
            estado_workflow=orden.estado_workflow,
            current_process=orden.current_process,
            prioridad=orden.prioridad,
            cliente=ClienteOut(**orden.cliente.model_dump()),
            equipo=EquipoOut(**orden.equipo.model_dump()),
            reparaciones_detail=[
                DetalleOut.desde_dominio(
                    detalle,
                    (insumos_previstos or {}).get(detalle.id, ()),
                    (nombres_de_tipo or {}).get(detalle.id),
                )
                for detalle in orden.reparaciones_detail
            ],
            tomas=[TomaOut.desde_dominio(toma) for toma in orden.tomas],
            ejecuciones=[
                EjecucionOut.desde_dominio(ejecucion)
                for ejecucion in orden.ejecuciones
            ],
            pagos=[
                PagoOut(**pago.model_dump())
                for pago in orden.resumen_pago.pagos
            ],
            documentos=DocumentosOut(
                **orden.documentos.model_dump()
            ),
            resumen=ResumenComercialOut(
                total=orden.total,
                pagado=orden.resumen_pago.pagado,
                saldo=orden.saldo,
                estado_pago=orden.estado_pago,
                puntaje_total=orden.puntaje_total,
            ),
            historial=[
                HistorialOut.desde_dominio(paso) for paso in orden.historial
            ],
            progreso=[
                PasoProgresoOut.desde_dominio(paso) for paso in progreso
            ],
            acciones_disponibles=[
                AccionOut.desde_dominio(accion) for accion in acciones
            ],
            created_at=orden.created_at,
            updated_at=orden.updated_at,
        )


class OrdenConEntregaOut(OrdenOut):
    """La Orden mas el resultado de PROC-REP-265.

    Lo devuelven los dos comandos que evaluan la condicion de entrega:
    la notificacion y el registro de un Pago.
    """

    puede_entregar: bool


class ErrorOut(BaseModel):
    """Forma unica de los errores de la API."""

    codigo: str
    mensaje: str


class RespuestaErrorOut(BaseModel):
    """Envoltorio del error. Nunca incluye stack traces."""

    error: ErrorOut
