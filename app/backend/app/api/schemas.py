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

from pydantic import AliasChoices, BaseModel, Field

from app.application import (
    AccionDisponible,
    AutorizacionDetalle,
    AutorizacionesOrden,
    DetalleOrigen,
    ImpactoOverride,
    InsumoPrevisto,
    MovimientoFinanciero,
    PasoProgreso,
    PendienteAutorizacion,
    SituacionAutorizacion,
    SituacionFinanciera,
    SituacionOperativa,
    movimientos_financieros,
    situacion_autorizacion,
    situacion_financiera,
)
from app.domain.garantia import GARANTIA_MAXIMA_DIAS
from app.domain.models import (
    AjusteGarantia,
    CanalComunicacion,
    Cliente,
    CondicionReparacionDetail,
    ContenidoDocumento,
    DatosRecepcion,
    DocumentoEmitido,
    EjecucionReparacion,
    Equipo,
    EstacionTrabajo,
    EstadoControl,
    EstadoCustodia,
    EstadoEjecucion,
    EstadoPago,
    EstadoReparacionDetail,
    EstadoTomaOrden,
    EstadoWorkflow,
    HistorialWorkflow,
    InsumoUtilizado,
    MedioPago,
    OrdenReparacion,
    OrigenCancelacion,
    OrigenOrden,
    RecepcionEquipo,
    RegistroAutorizacionCliente,
    RegistroDescuento,
    RegistroRecepcion,
    ReparacionDetail,
    ResultadoAutorizacion,
    ResultadoControl,
    RolUsuario,
    TipoDescuento,
    TipoDocumento,
    TipoEntrega,
    TipoPago,
    TipoReferenciaHistorial,
    TipoReparacion,
    TomaOrden,
    Usuario,
)
from app.domain.politicas import CondicionComercial, politica_de
from app.domain.prioridad import (
    NOMBRES_DE_PRIORIDAD,
    PRIORIDAD_NORMAL,
    PRIORIDAD_PREDETERMINADA,
    PRIORIDAD_URGENTE,
    prioridad_vigente,
    texto_de_prioridad,
)
from app.services import (
    AnalisisDesistimiento,
    EstadoAutorizacion,
    PrecondicionInvalidaError,
    analizar_desistimiento,
    autorizados_en_el_ingreso,
    descripcion_de_descuento,
    devolucion_pendiente,
    devolvible_de,
    dni_opcional,
    es_ingreso_inicial,
    estado_autorizacion,
    estado_custodia,
    finalizada_sin_reparacion,
    nuevo_id,
    pendiente_de_retrabajo,
    pendientes_para_cerrar,
    requiere_autorizacion_cliente,
    toma_activa,
)

# --- Catalogos ---------------------------------------------------------------


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


class PrioridadOut(BaseModel):
    """Una prioridad del catalogo (``app.domain.prioridad``)."""

    valor: int
    nombre: str
    predeterminada: bool

    @classmethod
    def catalogo(cls) -> list["PrioridadOut"]:
        """1 Urgente ... 4 Normal, de la mas a la menos prioritaria."""
        return [
            cls(
                valor=valor,
                nombre=nombre,
                predeterminada=valor == PRIORIDAD_PREDETERMINADA,
            )
            for valor, nombre in sorted(NOMBRES_DE_PRIORIDAD.items())
        ]


class MedioPagoOut(BaseModel):
    """Medio de pago o de devolucion de dinero (catalogo)."""

    id: str
    nombre: str
    activo: bool
    admite_devolucion: bool

    @classmethod
    def desde_dominio(cls, medio: MedioPago) -> "MedioPagoOut":
        return cls(**medio.model_dump())


class UsuarioOut(BaseModel):
    """Usuario operativo. Alimenta el selector de actor DEMO."""

    id: str
    nombre: str
    rol: RolUsuario
    activo: bool

    @classmethod
    def desde_dominio(cls, usuario: Usuario) -> "UsuarioOut":
        return cls(**usuario.model_dump())


# --- Entrada de comandos -----------------------------------------------------


def _texto_o_none(texto: str | None) -> str | None:
    return (texto or "").strip() or None


class ClienteIn(BaseModel):
    """Datos del cliente que deja el equipo.

    ``nombre_apellido``: el nombre completo tal como lo carga Recepcion (no
    se separa). Compatibilidad de escritura: se acepta tambien la clave
    anterior ``nombre`` con el mismo significado; ``nombre_apellido``
    tiene prioridad si vienen las dos. ``dni`` es opcional (se valida y
    normaliza si viene). ``id``: el de un cliente conocido que se reutiliza
    (lo devuelve la busqueda por DNI); sin ``id`` se crea uno, salvo que
    ese DNI ya sea de otro cliente (409 ``CLIENTE_EXISTENTE``: no se
    duplica).
    """

    nombre_apellido: str = Field(
        min_length=1,
        max_length=200,
        validation_alias=AliasChoices("nombre_apellido", "nombre"),
    )
    telefono: str = Field(min_length=1, max_length=40)
    email: str | None = Field(default=None, max_length=200)
    dni: str | None = Field(default=None, max_length=20)
    id: str | None = None

    @property
    def reutilizado(self) -> bool:
        return bool(self.id)

    def a_dominio(self) -> Cliente:
        """El MVP no tiene padron de clientes: si no viene ID, se crea."""
        nombre_apellido = self.nombre_apellido.strip()
        if not nombre_apellido:
            raise PrecondicionInvalidaError(
                "Falta el nombre y apellido del cliente."
            )
        return Cliente(
            id=self.id or nuevo_id("CLI"),
            dni=dni_opcional(self.dni),
            nombre_apellido=nombre_apellido,
            telefono=self.telefono.strip(),
            email=_texto_o_none(self.email),
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


class DatosRecepcionIn(BaseModel):
    """Condiciones en que se recibe el equipo (todas opcionales al alta).

    ``accesorios``: lo que se recibe junto con el equipo (vacio: ninguno).
    ``observaciones``: observaciones visibles del equipo (salen en el
    comprobante). ``notas_internas``: solo para el personal, nunca en un
    documento. El check-in no va aca: se registra antes de la entrega
    (``POST .../checkin``).
    """

    estado_fisico: str | None = None
    accesorios: list[str] = Field(default_factory=list)
    observaciones: str | None = None
    notas_internas: str | None = None

    def a_dominio(self) -> DatosRecepcion:
        return DatosRecepcion(
            estado_fisico=self.estado_fisico,
            accesorios=list(self.accesorios),
            observaciones=self.observaciones,
            notas_internas=self.notas_internas,
        )


class CrearOrdenIn(BaseModel):
    """``POST /api/orders`` (ACT-RECEP).

    ``recepcion`` registra las condiciones del ingreso; la recepcion
    fisica queda pendiente de confirmar (``POST .../reception/confirm``).
    """

    usuario_id: str = Field(min_length=1)
    cliente: ClienteIn
    equipo: EquipoIn
    recepcion: DatosRecepcionIn | None = None


class CrearOrdenRtIn(BaseModel):
    """``POST /api/orders/rt-interno`` (ACT-RECEP, HP-REP-002).

    Sin ``cliente``: el equipo es de Rosario Tecno. ``referencia_rt`` es
    el contexto minimo que PROC-REP-020 recibe de Gestion RT.
    """

    usuario_id: str = Field(min_length=1)
    equipo: EquipoIn
    referencia_rt: str = Field(min_length=1)
    recepcion: DatosRecepcionIn | None = None


class DefinirReparacionIn(BaseModel):
    """``POST /api/orders/{id}/details`` (ACT-RECEP).

    Agrega UN Detalle (PROC-REP-070). No finaliza la definicion: eso es
    otra intencion, ``POST /api/orders/{id}/definition/finalize``.
    ``descripcion`` y ``precio`` son solo de "Otros" (``TR-OTROS``): una
    reparacion no tipificada, con su descripcion y su precio manual.
    """

    usuario_id: str = Field(min_length=1)
    tipo_reparacion_id: str = Field(min_length=1)
    observaciones: str | None = None
    descripcion: str | None = None
    precio: Decimal | None = Field(default=None, ge=0, decimal_places=2)


class FinalizarDefinicionIn(BaseModel):
    """``POST /api/orders/{id}/definition/finalize`` (ACT-RECEP).

    Cierra la carga de Detalles: [050 -> 060] -> 080 -> 090 -> 140 | 100.
    """

    usuario_id: str = Field(min_length=1)


class EncolarIn(BaseModel):
    """``POST /api/orders/{id}/queue`` (ACT-COORD).

    ``prioridad``: 1 Urgente ... 4 Normal (``app.domain.prioridad``). Sin
    valor se registra la predeterminada, 4, recien al priorizar.
    """

    usuario_id: str = Field(min_length=1)
    prioridad: int = Field(
        default=PRIORIDAD_PREDETERMINADA,
        ge=PRIORIDAD_URGENTE,
        le=PRIORIDAD_NORMAL,
    )


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


class InterrumpirEjecucionIn(BaseModel):
    """``POST /api/orders/{id}/executions/{ejecucion_id}/interrupt``.

    ``insumos_utilizados`` es lo realmente usado hasta la interrupcion.
    ``motivo`` es obligatorio (VAR-REP-003): vacio o solo espacios se
    rechaza sin efectos.
    """

    usuario_id: str = Field(min_length=1)
    insumos_utilizados: list[InsumoUtilizadoIn] = Field(default_factory=list)
    motivo: str = Field(min_length=1)
    observaciones: str | None = None


class RequiereRedefinicionIn(BaseModel):
    """``POST .../executions/{ejecucion_id}/requires-redefinition``.

    Tercer resultado de PROC-REP-200 (EXC-REP-004). Misma forma que
    ``InterrumpirEjecucionIn`` mas el ``motivo`` obligatorio.
    """

    usuario_id: str = Field(min_length=1)
    insumos_utilizados: list[InsumoUtilizadoIn] = Field(default_factory=list)
    motivo: str = Field(min_length=1)
    observaciones: str | None = None


class RevisionDetalleIn(BaseModel):
    """``POST /api/orders/{id}/details/{detalle_id}/technical-review``.

    PROC-REP-126 (ACT-TECH, EXC-REP-004): revision de UN Detalle
    existente que requiere redefinicion.
    """

    usuario_id: str = Field(min_length=1)
    resultado: str = Field(min_length=1)


class RedefinirDetalleIn(BaseModel):
    """``POST /api/orders/{id}/details/{detalle_id}/redefine``.

    PROC-REP-127 (ACT-RECEP, EXC-REP-004): nueva definicion del MISMO
    Detalle; despues se revalida la factibilidad (080).
    """

    usuario_id: str = Field(min_length=1)
    tipo_reparacion_id: str = Field(min_length=1)


class AprobarControlIn(BaseModel):
    """``POST /api/orders/{id}/control/approve`` (ACT-RECEP).

    ``detalle_id`` (opcional, aditivo) aprueba un unico Detalle -control
    tecnico granular, Multi-Detalle-. Sin ``detalle_id`` preserva el
    comportamiento anterior: aprueba todos los Detalles de la Orden de
    una vez.
    """

    usuario_id: str = Field(min_length=1)
    detalle_id: str | None = None
    observaciones: str | None = None


class LiberarOrdenIn(BaseModel):
    """``POST /api/orders/{id}/release`` (ACT-TECH).

    PROC-REP-212 ("No") -> PROC-REP-213: el tecnico libera la Orden sin
    terminarla, con la toma activa todavia sobre ella.

    Liberar la de OTRO tecnico (o Coordinacion) exige ``motivo`` y
    ``confirmado: true`` (sin confirmar: 409 CONFIRMACION_REQUERIDA, con
    el aviso de quien la tiene). Si hay una reparacion en curso se
    interrumpe: ``insumos_utilizados`` es lo usado hasta ahi.
    """

    usuario_id: str = Field(min_length=1)
    motivo: str | None = None
    confirmado: bool = False
    insumos_utilizados: list[InsumoUtilizadoIn] = Field(default_factory=list)


class CambiarPrioridadIn(BaseModel):
    """``POST /api/orders/{id}/priority`` (Tecnico, Coordinacion o Recepcion).

    Cambia la prioridad de una Orden que ya esta en el taller (en cola o
    en reparacion). Es distinto de ingresarla a la cola.
    """

    usuario_id: str = Field(min_length=1)
    prioridad: int = Field(ge=PRIORIDAD_URGENTE, le=PRIORIDAD_NORMAL)
    motivo: str | None = None


class GenerarComprobanteIngresoIn(BaseModel):
    """``POST .../documents/intake-receipt`` (Recepcion).

    Ingreso inicial de CLIENTE_EXTERNO: confirma la recepcion, finaliza la
    definicion, autoriza los trabajos cargados y emite el comprobante de
    ingreso y autorizacion. ``canal``: por donde autorizo el cliente.
    """

    usuario_id: str = Field(min_length=1)
    canal: CanalComunicacion = CanalComunicacion.PRESENCIAL


class DescuentoIn(BaseModel):
    """``POST /api/orders/{id}/discount`` (Recepcion o Administracion).

    ``tipo``: PORCENTAJE (``valor`` de 0 a 100) o IMPORTE (``valor`` en
    pesos). ``tipo: null`` quita el descuento vigente. ``motivo`` es
    obligatorio siempre. El precio de cada trabajo no cambia.
    """

    usuario_id: str = Field(min_length=1)
    tipo: TipoDescuento | None = None
    valor: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    motivo: str = Field(min_length=1)


class AjustarGarantiaIn(BaseModel):
    """``POST .../details/{detalle_id}/warranty`` (Recepcion o Coordinacion).

    Plazo definitivo de garantia del trabajo, en dias desde la entrega. La
    sugerida (90 con check-in, 30 sin) se conserva.
    """

    usuario_id: str = Field(min_length=1)
    dias: int = Field(ge=0, le=GARANTIA_MAXIMA_DIAS)
    motivo: str = Field(min_length=1)


class RegistrarCheckinIn(BaseModel):
    """``POST /api/orders/{id}/checkin`` (Recepcion o Administracion).

    Antes de entregar, con la reparacion lista: ``realizado`` dice si se
    pudieron verificar las funciones basicas del equipo. Define la garantia
    de cada trabajo (90 o 30 dias) sin pisar los ajustes manuales.
    """

    usuario_id: str = Field(min_length=1)
    realizado: bool


class NotificarIn(BaseModel):
    """``POST /api/orders/{id}/notify`` (ACT-RECEP)."""

    usuario_id: str = Field(min_length=1)


class PagoIn(BaseModel):
    """``POST /api/orders/{id}/payments`` (capacidad transversal).

    ``metodo``: ID del catalogo de medios de pago. ``referencia``: dato
    opcional de la operacion. ``operacion_id``: clave del envio (la UI la
    genera por formulario) para que un reintento no duplique el Pago.
    """

    usuario_id: str = Field(min_length=1)
    monto: Decimal = Field(gt=0)
    metodo: str = Field(min_length=1)
    referencia: str | None = None
    operacion_id: str | None = None


class AnularPagoIn(BaseModel):
    """``POST /api/orders/{id}/payments/{pago_id}/void`` (Administracion)."""

    usuario_id: str = Field(min_length=1)
    motivo: str = Field(min_length=1)


class DevolucionDineroIn(BaseModel):
    """``POST /api/orders/{id}/refunds``: devolucion de dinero al cliente.

    Vinculada a un Pago (``pago_id``), con medio del catalogo y motivo
    obligatorio. ``operacion_id`` evita duplicarla ante un reintento.
    """

    usuario_id: str = Field(min_length=1)
    pago_id: str = Field(min_length=1)
    monto: Decimal = Field(gt=0)
    medio: str = Field(min_length=1)
    motivo: str = Field(min_length=1)
    referencia: str | None = None
    operacion_id: str | None = None


class EntregarIn(BaseModel):
    """``POST /api/orders/{id}/deliver`` (ACT-ADMIN).

    ``recibido_por`` (quien retira) es obligatorio para entregar: el
    backend lo exige despues de la condicion comercial y de la custodia,
    asi que una Orden que todavia no puede entregarse responde por ese
    motivo. ``identificacion_receptor``: DNI u otro, si corresponde.
    """

    usuario_id: str = Field(min_length=1)
    recibido_por: str | None = None
    identificacion_receptor: str | None = None
    observaciones: str | None = None


class IniciarGarantiaRmaIn(BaseModel):
    """``POST /api/orders/{orden_origen_id}/warranty-rma`` (ACT-RECEP).

    Recepcion inicia UNA garantia RMA de una Orden ENTREGADA eligiendo
    1..N de sus Detalles (HP-REP-003). La unicidad y la pertenencia de los
    IDs las valida el dominio (409), no el DTO.
    """

    usuario_id: str = Field(min_length=1)
    detalle_origen_ids: list[str] = Field(min_length=1)
    recepcion: DatosRecepcionIn | None = None


class OverrideRecursosIn(BaseModel):
    """``POST /api/orders/{id}/details/{detalle_id}/resources/override``.

    Override de factibilidad por recursos (ACT-COORD, BR-REP-003): el
    motivo es obligatorio. ``confirmado`` (E3) es la confirmacion
    explicita del impacto en el stock que la UI muestra antes
    (``GET .../resources/override-preview``): sin ella el backend no
    aplica nada y responde 409 CONFIRMACION_REQUERIDA.
    """

    usuario_id: str = Field(min_length=1)
    motivo: str = Field(min_length=1)
    confirmado: bool = False


class EnviarARevisionIn(BaseModel):
    """``POST /api/orders/{id}/send-to-review`` (ACT-RECEP, VAR-REP-001)."""

    usuario_id: str = Field(min_length=1)


class RevisionTecnicaIn(BaseModel):
    """``POST /api/orders/{id}/technical-review`` (ACT-TECH, PROC-REP-065)."""

    usuario_id: str = Field(min_length=1)
    resultado: str = Field(min_length=1)


class DefinirReparacionDesdeRevisionIn(BaseModel):
    """``POST /api/orders/{id}/review/details`` (ACT-RECEP, PROC-REP-075).

    Agrega UN Detalle luego de la revision. ``detalle_origen_id`` elige,
    en una garantia RMA, a cual de sus Detalles origen corresponde
    (obligatorio si hay mas de uno). ``descripcion`` y ``precio``: solo
    "Otros", como en ``DefinirReparacionIn``.
    """

    usuario_id: str = Field(min_length=1)
    tipo_reparacion_id: str = Field(min_length=1)
    observaciones: str | None = None
    detalle_origen_id: str | None = None
    descripcion: str | None = None
    precio: Decimal | None = Field(default=None, ge=0, decimal_places=2)


class FinalizarSinReparacionIn(BaseModel):
    """``POST /api/orders/{id}/review/without-repair`` (ACT-RECEP).

    PROC-REP-068 (No) -> 069: la revision concluye SIN_REPARACION. El
    motivo es obligatorio (BR-REP-010); las observaciones, opcionales.
    """

    usuario_id: str = Field(min_length=1)
    motivo: str = Field(min_length=1)
    observaciones: str | None = None


class DevolverRtIn(BaseModel):
    """``POST /api/orders/{id}/return-rt`` (PROC-REP-270, HP-REP-002)."""

    usuario_id: str = Field(min_length=1)


class RechazarControlIn(BaseModel):
    """``POST /api/orders/{id}/control/reject`` (ACT-RECEP, PROC-REP-235).

    Rechaza el control de UN Detalle: ``detalle_id`` y ``motivo`` son
    obligatorios.
    """

    usuario_id: str = Field(min_length=1)
    detalle_id: str = Field(min_length=1)
    motivo: str = Field(min_length=1)


class CancelarDetalleIn(BaseModel):
    """``POST /api/orders/{id}/details/{detalle_id}/cancel`` (PROC-REP-300)."""

    usuario_id: str = Field(min_length=1)
    motivo: str = Field(min_length=1)


class CancelarOrdenIn(BaseModel):
    """``POST /api/orders/{id}/cancel`` (PROC-REP-305 / 306)."""

    usuario_id: str = Field(min_length=1)
    motivo: str = Field(min_length=1)


class RegistrarDevolucionIn(BaseModel):
    """``POST /api/orders/{id}/return-equipment`` (PROC-REP-270, CANCELADA).

    ``recibido_por``: quien recibe el equipo (el cliente o Gestion RT).
    """

    usuario_id: str = Field(min_length=1)
    recibido_por: str = Field(min_length=1)
    observaciones: str | None = None
    identificacion_receptor: str | None = None


class RegistrarRecepcionIn(BaseModel):
    """``PUT /api/orders/{id}/reception``: datos del ingreso.

    Registra o corrige (antes de confirmar la recepcion) el estado fisico,
    los accesorios y las observaciones; ``equipo`` corrige tambien marca,
    modelo, identificadores o falla declarada. La version anterior se
    conserva.
    """

    usuario_id: str = Field(min_length=1)
    estado_fisico: str | None = None
    accesorios: list[str] = Field(default_factory=list)
    observaciones: str | None = None
    notas_internas: str | None = None
    equipo: EquipoIn | None = None

    def datos(self) -> DatosRecepcion:
        return DatosRecepcion(
            estado_fisico=self.estado_fisico,
            accesorios=list(self.accesorios),
            observaciones=self.observaciones,
            notas_internas=self.notas_internas,
        )


class ConfirmarRecepcionIn(BaseModel):
    """``POST .../reception/confirm``: el equipo quedo en el local.

    ``observaciones`` es obligatoria si la confirmacion regulariza una
    Orden anterior al registro de recepcion (lo valida el dominio).
    """

    usuario_id: str = Field(min_length=1)
    observaciones: str | None = None


class EquipoNoRecibidoIn(BaseModel):
    """``POST .../reception/not-received``: el equipo nunca ingreso.

    Motivo obligatorio. Solo en una Orden cancelada y sin evidencias de que
    el equipo estuvo en el local (lo valida el dominio).
    """

    usuario_id: str = Field(min_length=1)
    motivo: str = Field(min_length=1)


class ObservacionRecepcionIn(BaseModel):
    """``POST .../reception/notes``: observacion complementaria.

    ``interna``: solo para el personal; nunca sale en un documento.
    """

    usuario_id: str = Field(min_length=1)
    texto: str = Field(min_length=1)
    interna: bool = False


class EmitirDocumentoIn(BaseModel):
    """``POST .../documents/reception-receipt``: version nueva, con motivo."""

    usuario_id: str = Field(min_length=1)
    motivo: str | None = None


class EmitirComprobanteAutorizacionIn(BaseModel):
    """``POST .../documents/authorization-receipt`` (Recepcion).

    Sin motivo: si es una version nueva, el motivo es lo que cambio en los
    trabajos autorizados y lo calcula el backend.
    """

    usuario_id: str = Field(min_length=1)


class DecisionDetalleIn(BaseModel):
    """La respuesta del cliente sobre UN Detalle.

    ``version_definicion`` es la definicion que se le presento: si ya no
    es la vigente, la respuesta se rechaza (409).
    """

    detalle_id: str = Field(min_length=1)
    version_definicion: int = Field(ge=1)
    resultado: ResultadoAutorizacion


class RegistrarDecisionClienteIn(BaseModel):
    """``POST /api/orders/{id}/authorizations`` (ACT-RECEP, PROC-REP-046).

    Uno o varios Detalles en una sola operacion. Un Detalle sin respuesta
    del cliente simplemente no se incluye: sigue pendiente.
    ``observaciones`` es la referencia o evidencia de la respuesta.
    """

    usuario_id: str = Field(min_length=1)
    canal: CanalComunicacion
    observaciones: str | None = None
    decisiones: list[DecisionDetalleIn]


class DesistimientoIn(BaseModel):
    """``POST .../withdrawal`` y ``.../details/{detalle_id}/withdrawal``.

    El cliente desiste de trabajos ya autorizados (o de todos los
    cancelables). El motivo es obligatorio.
    """

    usuario_id: str = Field(min_length=1)
    canal: CanalComunicacion
    motivo: str = Field(min_length=1)


# --- Salida ------------------------------------------------------------------


class ClienteOut(BaseModel):
    """El cliente; ``nombre_apellido`` es su nombre completo (en una Orden
    anterior, el que se guardo como ``nombre``)."""

    id: str
    dni: str | None = None
    nombre_apellido: str
    telefono: str
    email: str | None = None


class FotoOut(BaseModel):
    """Una foto del equipo: sus datos (la imagen se pide aparte)."""

    id: str
    tipo_contenido: str
    tamano_bytes: int
    usuario_id: str
    fecha: datetime
    nombre_original: str | None = None


class ClienteConocidoOut(BaseModel):
    """Un cliente que ya tiene Ordenes con ese DNI (sus datos mas
    recientes)."""

    cliente_id: str
    nombre_apellido: str
    telefono: str
    email: str | None = None
    ultima_orden_id: str
    ultima_fecha: datetime
    ordenes: int


class PersonaExternaOut(BaseModel):
    """Lo que devuelve una fuente externa: solo el nombre completo, tal
    cual (no se separa)."""

    nombre_apellido: str


class BusquedaClienteOut(BaseModel):
    """``GET /api/clients/lookup``: para revisar, nunca se guarda solo.

    ``estado``: ENCONTRADO, AMBIGUO, SIN_RESULTADOS, NO_DISPONIBLE, LIMITE
    o NO_HABILITADA (sin fuente externa autorizada). ``origen``: BASE (ya
    es cliente) o EXTERNO.
    """

    dni: str
    estado: str
    mensaje: str
    origen: str | None = None
    fuente: str | None = None
    conocidos: list[ClienteConocidoOut] = Field(default_factory=list)
    externos: list[PersonaExternaOut] = Field(default_factory=list)

    @classmethod
    def desde_aplicacion(cls, busqueda) -> "BusquedaClienteOut":
        return cls(
            dni=busqueda.dni,
            estado=busqueda.estado,
            mensaje=busqueda.mensaje,
            origen=busqueda.origen,
            fuente=busqueda.fuente,
            conocidos=[
                ClienteConocidoOut(**conocido.__dict__)
                for conocido in busqueda.conocidos
            ],
            externos=[
                PersonaExternaOut(**persona.__dict__)
                for persona in busqueda.externos
            ],
        )


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


class DefinicionAnteriorOut(BaseModel):
    """Definicion reemplazada por PROC-REP-127 (BR-REP-015)."""

    tipo_reparacion_id: str
    precio: Decimal
    puntaje: int
    garantia_dias: int
    reemplazada_en: datetime
    usuario_id: str


class ControlTecnicoOut(BaseModel):
    """Un control tecnico registrado: aprobacion o rechazo (E14)."""

    resultado: ResultadoControl
    usuario_id: str
    fecha: datetime
    observaciones: str | None = None
    ejecucion_id: str | None = None


class CancelacionOut(BaseModel):
    """Quien cancelo el Detalle, cuando y por que (PROC-REP-300/305).

    ``origen``: ``INTERNA`` o ``RECHAZO_CLIENTE``.
    """

    usuario_id: str
    fecha: datetime
    motivo: str
    origen: OrigenCancelacion = OrigenCancelacion.INTERNA


class AutorizacionClienteOut(BaseModel):
    """Una decision del cliente registrada sobre un Detalle (046)."""

    version_definicion: int
    resultado: ResultadoAutorizacion
    usuario_id: str
    fecha: datetime
    canal: CanalComunicacion
    observaciones: str | None = None

    @classmethod
    def desde_dominio(
        cls, registro: RegistroAutorizacionCliente
    ) -> "AutorizacionClienteOut":
        return cls(**registro.model_dump())


class DetalleOut(BaseModel):
    """Detalle de Reparacion con su snapshot comercial.

    ``definiciones_anteriores`` (EXC-REP-004) son las definiciones que
    PROC-REP-127 reemplazo, de la mas antigua a la mas reciente.
    ``controles`` son todos los controles tecnicos registrados, en orden;
    ``pendiente_de_retrabajo`` indica un Detalle reabierto por un rechazo
    que todavia no se rehizo. ``cancelacion`` solo viene en un CANCELADO.

    Autorizacion del cliente (BR-REP-028): ``version_definicion`` es la
    definicion vigente, ``autorizaciones`` todas las decisiones registradas
    (de cualquier version) y ``estado_autorizacion`` /
    ``situacion_autorizacion`` lo derivado para la definicion vigente.
    """

    id: str
    tipo_reparacion_id: str
    tipo_reparacion_nombre: str
    precio: Decimal
    puntaje: int
    garantia_dias: int
    estado: EstadoReparacionDetail
    condicion: CondicionReparacionDetail
    control_estado: EstadoControl
    control_usuario_id: str | None = None
    control_fecha: datetime | None = None
    control_observaciones: str | None = None
    observaciones: str | None = None
    detalle_origen_id: str | None = None
    definiciones_anteriores: list[DefinicionAnteriorOut] = Field(
        default_factory=list
    )
    controles: list[ControlTecnicoOut] = Field(default_factory=list)
    pendiente_de_retrabajo: bool = False
    cancelacion: CancelacionOut | None = None
    insumos_previstos: list[InsumoPrevistoOut] = Field(default_factory=list)
    version_definicion: int = 1
    autorizaciones: list[AutorizacionClienteOut] = Field(default_factory=list)
    estado_autorizacion: EstadoAutorizacion = EstadoAutorizacion.NO_REQUERIDA
    situacion_autorizacion: SituacionAutorizacion = (
        SituacionAutorizacion.NO_REQUERIDA
    )
    # "Otros": la descripcion manual del trabajo.
    descripcion: str | None = None
    # Garantia: la sugerida (check-in) y los ajustes manuales; el plazo
    # definitivo es ``garantia_dias``.
    garantia_dias_sugerida: int | None = None
    ajustes_garantia: list[AjusteGarantia] = Field(default_factory=list)
    # Presentacion del ingreso inicial (derivada, no es un estado nuevo):
    # el trabajo espera el comprobante de ingreso, o lo autorizo ese
    # comprobante (su definicion vigente es la que figura en el).
    pendiente_comprobante_ingreso: bool = False
    autorizado_en_ingreso: bool = False

    @classmethod
    def desde_dominio(
        cls,
        detalle: ReparacionDetail,
        previstos: Sequence[InsumoPrevisto] = (),
        tipo_reparacion_nombre: str | None = None,
        *,
        estado_autorizacion: EstadoAutorizacion = (
            EstadoAutorizacion.NO_REQUERIDA
        ),
        situacion_autorizacion: SituacionAutorizacion = (
            SituacionAutorizacion.NO_REQUERIDA
        ),
        pendiente_comprobante_ingreso: bool = False,
        autorizado_en_ingreso: bool = False,
    ) -> "DetalleOut":
        return cls(
            **detalle.model_dump(),
            version_definicion=detalle.version_definicion,
            estado_autorizacion=estado_autorizacion,
            situacion_autorizacion=situacion_autorizacion,
            pendiente_comprobante_ingreso=pendiente_comprobante_ingreso,
            autorizado_en_ingreso=autorizado_en_ingreso,
            pendiente_de_retrabajo=pendiente_de_retrabajo(detalle),
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
    # Liberada por otro tecnico (MVP v2): quien y por que.
    liberada_por: str | None = None
    motivo_liberacion: str | None = None

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
    insumos_utilizados: list[InsumoUtilizadoOut] = Field(default_factory=list)
    observaciones: str | None = None
    motivo_interrupcion: str | None = None
    motivo_redefinicion: str | None = None

    @classmethod
    def desde_dominio(cls, ejecucion: EjecucionReparacion) -> "EjecucionOut":
        return cls(**ejecucion.model_dump())


class AnulacionPagoOut(BaseModel):
    usuario_id: str
    fecha: datetime
    motivo: str


class PagoOut(BaseModel):
    """Pago registrado.

    ``tipo_pago`` (ANTICIPO / PARCIAL / FINAL) y ``metodo`` (ID del medio:
    EFECTIVO, TRANSFERENCIA, ...) son dimensiones distintas. ``monto`` es
    siempre el original; un Pago anulado trae ``anulacion`` y no cuenta como
    pagado. ``devuelto``: lo devuelto desde este Pago; ``devolvible``: lo que
    todavia puede devolverse desde el.
    """

    id: str
    monto: Decimal
    tipo_pago: TipoPago
    metodo: str
    usuario_id: str
    fecha: datetime
    referencia: str | None = None
    vigente: bool = True
    anulacion: AnulacionPagoOut | None = None
    devuelto: Decimal = Decimal("0")
    devolvible: Decimal = Decimal("0")


class DevolucionDineroOut(BaseModel):
    """Dinero devuelto al cliente desde un Pago (V1.4 PROC-REP-267)."""

    id: str
    pago_id: str
    monto: Decimal
    medio: str
    usuario_id: str
    fecha: datetime
    motivo: str
    referencia: str | None = None


class DocumentoOut(BaseModel):
    generado: bool
    fecha_generacion: datetime | None = None


class DocumentosOut(BaseModel):
    comprobante_recepcion: DocumentoOut
    comprobante_final: DocumentoOut
    garantia_reparacion: DocumentoOut


class DevolucionOut(BaseModel):
    """Salida fisica del equipo (PROC-REP-270): entrega o devolucion."""

    tipo: TipoEntrega = TipoEntrega.DEVOLUCION_SIN_REPARACION
    entregado_por: str
    recibido_por: str
    identificacion_receptor: str | None = None
    fecha: datetime
    observaciones: str | None = None


class DatosRecepcionOut(BaseModel):
    estado_fisico: str | None = None
    accesorios: list[str] = Field(default_factory=list)
    observaciones: str | None = None
    notas_internas: str | None = None
    checkin: bool | None = None


class VersionRecepcionOut(BaseModel):
    """Datos del ingreso reemplazados por una correccion."""

    equipo: EquipoOut
    datos: DatosRecepcionOut
    registrado_por: str
    registrado_en: datetime
    reemplazado_por: str
    reemplazado_en: datetime


class ConfirmacionRecepcionOut(BaseModel):
    usuario_id: str
    fecha: datetime
    observaciones: str | None = None


class NoRecepcionOut(BaseModel):
    usuario_id: str
    fecha: datetime
    motivo: str


class NotaRecepcionOut(BaseModel):
    usuario_id: str
    fecha: datetime
    texto: str
    interna: bool = False


class RegistroCheckinOut(BaseModel):
    """Un registro del check-in antes de la entrega."""

    realizado: bool
    usuario_id: str
    fecha: datetime


class RecepcionOut(BaseModel):
    """Datos del ingreso fisico del equipo, versiones y confirmacion.

    ``datos.checkin`` es el check-in vigente; ``registros_checkin``, quien
    lo registro y cuando (antes de la entrega).
    """

    registro: RegistroRecepcion
    datos: DatosRecepcionOut
    registrado_por: str
    registrado_en: datetime
    versiones_anteriores: list[VersionRecepcionOut] = Field(
        default_factory=list
    )
    confirmacion: ConfirmacionRecepcionOut | None = None
    no_recibido: NoRecepcionOut | None = None
    notas: list[NotaRecepcionOut] = Field(default_factory=list)
    registros_checkin: list[RegistroCheckinOut] = Field(default_factory=list)

    @classmethod
    def desde_dominio(cls, recepcion: RecepcionEquipo) -> "RecepcionOut":
        return cls.model_validate(recepcion.model_dump())


class CustodiaOut(BaseModel):
    """Donde esta el equipo, independiente del comprobante de recepcion.

    ``confirmacion_requerida``: el Origen exige confirmar la recepcion
    (RT_INTERNO no). ``comprobante_recepcion_emitido`` es otro hecho y se
    informa aparte: no prueba la custodia.
    """

    estado: EstadoCustodia
    confirmacion_requerida: bool
    confirmada_por: str | None = None
    confirmada_en: datetime | None = None
    comprobante_recepcion_emitido: bool = False
    salida: DevolucionOut | None = None

    @classmethod
    def desde_dominio(cls, orden: OrdenReparacion) -> "CustodiaOut":
        confirmacion = (
            orden.recepcion.confirmacion if orden.recepcion else None
        )
        salida = orden.entrega or orden.devolucion
        return cls(
            estado=estado_custodia(orden),
            confirmacion_requerida=politica_de(
                orden.origen
            ).requiere_confirmacion_recepcion,
            confirmada_por=confirmacion.usuario_id if confirmacion else None,
            confirmada_en=confirmacion.fecha if confirmacion else None,
            comprobante_recepcion_emitido=(
                orden.documentos.comprobante_recepcion.generado
                or any(
                    documento.tipo is TipoDocumento.COMPROBANTE_RECEPCION
                    for documento in orden.documentos.emitidos
                )
            ),
            salida=(
                DevolucionOut(**salida.model_dump())
                if salida is not None
                else None
            ),
        )


class DocumentoResumenOut(BaseModel):
    """Un documento emitido, sin su contenido (para listar).

    ``vigente``: es la ultima version emitida de su tipo.
    """

    id: str
    tipo: TipoDocumento
    version: int
    fecha_emision: datetime
    usuario_id: str | None = None
    motivo: str | None = None
    reemplaza_a: str | None = None
    vigente: bool = True


class DocumentoEmitidoOut(DocumentoResumenOut):
    """Un documento emitido con su contenido, tal como se entrego."""

    orden_id: str
    contenido: ContenidoDocumento

    @classmethod
    def desde_dominio(
        cls,
        documento: DocumentoEmitido,
        *,
        vigente: bool,
    ) -> "DocumentoEmitidoOut":
        return cls(
            **documento.model_dump(exclude={"contenido"}),
            contenido=documento.contenido,
            vigente=vigente,
        )


def _vigentes(orden: OrdenReparacion) -> set[str]:
    """IDs de la ultima version emitida de cada tipo de documento."""
    ultimos: dict[TipoDocumento, str] = {}
    for documento in orden.documentos.emitidos:
        ultimos[documento.tipo] = documento.id
    return set(ultimos.values())


class DescuentoVigenteOut(BaseModel):
    """El descuento que rige hoy: como se expreso, cuanto y por que."""

    tipo: TipoDescuento
    valor: Decimal
    descripcion: str
    importe: Decimal
    motivo: str
    usuario_id: str
    fecha: datetime


class ResumenComercialOut(BaseModel):
    """Situacion comercial derivada. Nunca se persiste: se calcula.

    ``condicion_comercial`` (BR-REP-016) es la de ``PoliticaOrigen``:
    ``NO_COBRABLE_AL_CLIENTE`` (RT_INTERNO) o ``NO_COBRABLE``
    (RMA_GARANTIA_REPARACION) le dicen al frontend que ``total``/``saldo``
    son nominales -lo que hubiera costado-, no una deuda real a cobrar.
    """

    total: Decimal
    pagado: Decimal
    saldo: Decimal
    estado_pago: EstadoPago
    puntaje_total: int
    condicion_comercial: str
    # BR-REP-038: Saldo = Total - Pagado (valido) + Devuelto.
    devuelto: Decimal = Decimal("0")
    credito_a_favor: Decimal = Decimal("0")
    situacion_financiera: SituacionFinanciera = SituacionFinanciera.SALDADA
    # Descuento comercial (MVP v2): Total = Subtotal - descuento. El precio
    # de cada trabajo no cambia.
    subtotal: Decimal = Decimal("0")
    descuento_aplicado: Decimal = Decimal("0")
    descuento: DescuentoVigenteOut | None = None


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
    """Un paso que la Orden admite ahora, humano o de sistema.

    ``roles`` lista TODOS los actores autorizados; puede haber mas de uno
    cuando el nodo declara ``actores_alternativos`` en PROC-REP V1.3.

    Con ``requiere_actor: true`` (el caso normal), una lista vacia de
    ``roles`` significa que el negocio todavia no definio el actor
    (Registrar Pago, BR-REP-017), no que cualquiera pueda: el backend
    igual exige usuario activo.

    ``requiere_actor: false`` marca un nodo ``actor: ACT-SYSTEM`` (por
    ejemplo Informar a Gestion RT, PROC-REP-290): no hay ningun actor
    humano que autorizar, y el comando correspondiente no recibe
    ``usuario_id``.

    ``usuario_id`` (E2), cuando viene, es la UNICA persona que puede
    ejecutar la accion: el titular de la toma activa en las acciones
    tecnicas. La UI la deshabilita para cualquier otro usuario; el
    backend igual lo rechaza (409 TOMA_DE_OTRO_TECNICO).
    """

    codigo: str
    etiqueta: str
    roles: list[RolUsuario] = Field(default_factory=list)
    detalle_id: str | None = None
    ejecucion_id: str | None = None
    requiere_actor: bool = True
    usuario_id: str | None = None
    # Movimientos financieros: el Pago sobre el que actua (anularlo).
    pago_id: str | None = None
    # La accion corresponde pero hoy no puede ejecutarse (y por que).
    bloqueo: str | None = None
    # Cualquiera con el rol SALVO esta persona (liberar la Orden de otro).
    usuario_excluido_id: str | None = None

    @classmethod
    def desde_dominio(cls, accion: AccionDisponible) -> "AccionOut":
        return cls(
            codigo=accion.codigo,
            etiqueta=accion.etiqueta,
            roles=list(accion.roles),
            detalle_id=accion.detalle_id,
            ejecucion_id=accion.ejecucion_id,
            requiere_actor=accion.requiere_actor,
            usuario_id=accion.usuario_id,
            pago_id=accion.pago_id,
            bloqueo=accion.bloqueo,
            usuario_excluido_id=accion.usuario_excluido_id,
        )


class TareaOut(BaseModel):
    """Algo que hay que hacer ahora y las acciones que lo resuelven."""

    titulo: str
    motivo: str
    responsable: str
    acciones: list[AccionOut]


class AvisoOut(BaseModel):
    """Un bloqueo secundario de la Orden (estado mixto)."""

    codigo: str
    titulo: str
    responsable: str | None = None
    acciones: list[AccionOut] = Field(default_factory=list)


class EtapaOut(BaseModel):
    """Una de las seis etapas del negocio y su estado."""

    codigo: str
    titulo: str
    estado: str
    detalle: str | None = None


class SituacionOut(BaseModel):
    """Situacion operativa: que pasa, a quien le toca, que sigue.

    Solo lectura, para la pantalla (``application.situacion``): no cambia
    estados ni habilita nada. Las acciones de cada tarea son las mismas
    que la Orden ya publica en sus grupos de acciones.
    """

    codigo: str
    titulo: str
    descripcion: str
    responsable: str | None = None
    desde: datetime | None = None
    tareas: list[TareaOut] = Field(default_factory=list)
    avisos: list[AvisoOut] = Field(default_factory=list)
    etapas: list[EtapaOut] = Field(default_factory=list)
    roles: list[RolUsuario] = Field(default_factory=list)
    titular_id: str | None = None

    @classmethod
    def desde_aplicacion(cls, situacion: SituacionOperativa) -> "SituacionOut":
        def acciones(grupo):
            return [AccionOut.desde_dominio(accion) for accion in grupo]

        return cls(
            codigo=situacion.codigo,
            titulo=situacion.titulo,
            descripcion=situacion.descripcion,
            responsable=situacion.responsable,
            desde=situacion.desde,
            roles=list(situacion.roles),
            titular_id=situacion.titular_id,
            tareas=[
                TareaOut(
                    titulo=tarea.titulo,
                    motivo=tarea.motivo,
                    responsable=tarea.responsable,
                    acciones=acciones(tarea.acciones),
                )
                for tarea in situacion.tareas
            ],
            avisos=[
                AvisoOut(
                    codigo=aviso.codigo,
                    titulo=aviso.titulo,
                    responsable=aviso.responsable,
                    acciones=acciones(aviso.acciones),
                )
                for aviso in situacion.avisos
            ],
            etapas=[
                EtapaOut(
                    codigo=etapa.codigo,
                    titulo=etapa.titulo,
                    estado=etapa.estado,
                    detalle=etapa.detalle,
                )
                for etapa in situacion.etapas
            ],
        )


def _nombre_para_listado(orden: OrdenReparacion) -> str:
    """Identificacion legible de la Orden para el listado.

    ``cliente`` es ``None`` en RT_INTERNO (no hay Cliente externo): se
    identifica por su referencia de Gestion RT en su lugar.
    """
    if orden.cliente is not None:
        return orden.cliente.nombre_apellido
    return f"RT Interno · {orden.referencia_rt or orden.id}"


class SituacionResumenOut(BaseModel):
    """La situacion operativa resumida para una fila del listado."""

    codigo: str
    titulo: str
    responsable: str | None = None
    roles: list[RolUsuario] = Field(default_factory=list)
    titular_id: str | None = None
    desde: datetime | None = None

    @classmethod
    def desde_aplicacion(
        cls, situacion: SituacionOperativa
    ) -> "SituacionResumenOut":
        return cls(
            codigo=situacion.codigo,
            titulo=situacion.titulo,
            responsable=situacion.responsable,
            roles=list(situacion.roles),
            titular_id=situacion.titular_id,
            desde=situacion.desde,
        )


def _texto_de_prioridad_vigente(orden: OrdenReparacion) -> str | None:
    """«Prioridad 1 · Urgente» si la prioridad sigue contando."""
    vigente = prioridad_vigente(orden)
    return texto_de_prioridad(vigente) if vigente is not None else None


class OrdenResumenOut(BaseModel):
    """Fila del listado de Ordenes.

    Incluye los datos por los que se busca una Orden (telefono, equipo,
    IMEI, serie, referencia RT) y su situacion operativa, para que el
    listado no tenga que pedir cada Orden. Todo es de solo lectura.
    ``updated_at`` cambia con cada modificacion registrada de la Orden: es
    su ultima actividad.

    ``prioridad_texto`` («Prioridad 1 · Urgente») existe solo con una
    prioridad vigente. ``posicion_por_prioridad`` es el lugar de la Orden
    en el criterio unico de ``app.domain.prioridad`` (0 = la primera): el
    frontend ordena con ese numero y no reinterpreta la prioridad.
    """

    id: str
    origen: OrigenOrden
    orden_origen_id: str | None
    estado_workflow: EstadoWorkflow
    current_process: str
    prioridad: int
    prioridad_texto: str | None = None
    posicion_por_prioridad: int = 0
    cliente_nombre: str
    cliente_telefono: str | None = None
    equipo: str
    equipo_marca: str = ""
    equipo_modelo: str = ""
    imei: str | None = None
    numero_serie: str | None = None
    referencia_rt: str | None = None
    total: Decimal
    saldo: Decimal
    estado_pago: EstadoPago
    cobrable: bool = False
    cerrada: bool = False
    # Titular de la toma activa, si la hay.
    tecnico_id: str | None = None
    situacion: SituacionResumenOut | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def desde_dominio(
        cls,
        orden: OrdenReparacion,
        situacion: SituacionOperativa | None = None,
        posicion_por_prioridad: int = 0,
    ) -> "OrdenResumenOut":
        toma = toma_activa(orden)
        return cls(
            id=orden.id,
            origen=orden.origen,
            orden_origen_id=orden.orden_origen_id,
            estado_workflow=orden.estado_workflow,
            current_process=orden.current_process,
            prioridad=orden.prioridad,
            prioridad_texto=_texto_de_prioridad_vigente(orden),
            posicion_por_prioridad=posicion_por_prioridad,
            cliente_nombre=_nombre_para_listado(orden),
            cliente_telefono=(
                orden.cliente.telefono if orden.cliente is not None else None
            ),
            equipo=f"{orden.equipo.marca} {orden.equipo.modelo}",
            equipo_marca=orden.equipo.marca,
            equipo_modelo=orden.equipo.modelo,
            imei=orden.equipo.imei,
            numero_serie=orden.equipo.numero_serie,
            referencia_rt=orden.referencia_rt,
            total=orden.total,
            saldo=orden.saldo,
            estado_pago=orden.estado_pago,
            cobrable=(
                politica_de(orden.origen).condicion_comercial
                == CondicionComercial.COBRABLE
            ),
            cerrada=orden.esta_cerrada,
            tecnico_id=toma.usuario_id if toma is not None else None,
            situacion=(
                SituacionResumenOut.desde_aplicacion(situacion)
                if situacion is not None
                else None
            ),
            created_at=orden.created_at,
            updated_at=orden.updated_at,
        )


class ImpactoStockInsumoOut(BaseModel):
    """Un insumo previsto ante el override: lo que se confirma (E3).

    ``disponible = stock_fisico - reservado_otras_ordenes -
    reservado_esta_orden`` y ``disponible_resultante = disponible -
    requerido``.
    """

    insumo_id: str
    codigo: str
    nombre: str
    stock_fisico: Decimal
    reservado_otras_ordenes: Decimal
    reservado_esta_orden: Decimal
    disponible: Decimal
    requerido: Decimal
    disponible_resultante: Decimal


class ImpactoOverrideOut(BaseModel):
    """``GET .../details/{detalle_id}/resources/override-preview`` (E3)."""

    orden_id: str
    detalle_id: str
    insumos: list[ImpactoStockInsumoOut]
    deja_disponible_negativo: bool
    hay_reservas_de_otras_ordenes: bool
    advertencia: str

    @classmethod
    def desde_aplicacion(
        cls, impacto: ImpactoOverride
    ) -> "ImpactoOverrideOut":
        return cls(
            orden_id=impacto.orden_id,
            detalle_id=impacto.detalle_id,
            insumos=[
                ImpactoStockInsumoOut(
                    insumo_id=insumo.insumo_id,
                    codigo=insumo.codigo,
                    nombre=insumo.nombre,
                    stock_fisico=insumo.stock_fisico,
                    reservado_otras_ordenes=insumo.reservado_otras_ordenes,
                    reservado_esta_orden=insumo.reservado_esta_orden,
                    disponible=insumo.disponible,
                    requerido=insumo.requerido,
                    disponible_resultante=insumo.disponible_resultante,
                )
                for insumo in impacto.insumos
            ],
            deja_disponible_negativo=impacto.deja_disponible_negativo,
            hay_reservas_de_otras_ordenes=impacto.hay_reservas_de_otras_ordenes,
            advertencia=impacto.advertencia,
        )


def _toma_activa_out(orden: OrdenReparacion) -> TomaOut | None:
    toma = toma_activa(orden)
    return TomaOut.desde_dominio(toma) if toma is not None else None


class DetalleOrigenOut(BaseModel):
    """Detalle de la Orden origen de una garantia RMA (presentacion)."""

    id: str
    tipo_reparacion_nombre: str


class BloqueoDesistimientoOut(BaseModel):
    detalle_id: str
    motivo: str


class DesistimientoOut(BaseModel):
    """Que haria hoy el desistimiento total del cliente (solo lectura).

    ``rechazables``: pendientes que se rechazarian; ``desistibles``:
    autorizados que se cancelarian; ``conservados``: COMPLETO, no se tocan;
    ``bloqueantes``: lo que hoy lo impide (con ellos se rechaza entero).
    """

    rechazables: list[str]
    desistibles: list[str]
    conservados: list[str]
    bloqueantes: list[BloqueoDesistimientoOut]

    @classmethod
    def desde_servicio(
        cls, analisis: AnalisisDesistimiento
    ) -> "DesistimientoOut":
        return cls(
            rechazables=list(analisis.rechazables),
            desistibles=list(analisis.desistibles),
            conservados=list(analisis.conservados),
            bloqueantes=[
                BloqueoDesistimientoOut(detalle_id=detalle_id, motivo=motivo)
                for detalle_id, motivo in analisis.bloqueantes
            ],
        )


def _descuento_vigente(orden: OrdenReparacion) -> DescuentoVigenteOut | None:
    registro = orden.descuento_vigente
    if registro is None:
        return None
    return DescuentoVigenteOut(
        tipo=registro.tipo,
        valor=registro.valor,
        descripcion=descripcion_de_descuento(registro),
        importe=orden.descuento_aplicado,
        motivo=registro.motivo,
        usuario_id=registro.usuario_id,
        fecha=registro.fecha,
    )


def _resumen_comercial(orden: OrdenReparacion) -> "ResumenComercialOut":
    return ResumenComercialOut(
        total=orden.total,
        pagado=orden.resumen_pago.pagado,
        saldo=orden.saldo,
        estado_pago=orden.estado_pago,
        puntaje_total=orden.puntaje_total,
        condicion_comercial=politica_de(orden.origen).condicion_comercial,
        devuelto=orden.resumen_pago.devuelto,
        credito_a_favor=orden.credito_a_favor,
        situacion_financiera=situacion_financiera(orden),
        subtotal=orden.subtotal,
        descuento_aplicado=orden.descuento_aplicado,
        descuento=_descuento_vigente(orden),
    )


class OrdenOut(BaseModel):
    """La Orden completa tal como la consume el frontend."""

    id: str
    origen: OrigenOrden
    estado_workflow: EstadoWorkflow
    current_process: str
    prioridad: int
    # «Prioridad 1 · Urgente», solo con una prioridad vigente.
    prioridad_texto: str | None = None
    cliente: ClienteOut | None
    equipo: EquipoOut
    referencia_rt: str | None
    orden_origen_id: str | None
    detalles_origen_ids: list[str]
    # Presentacion (BR-REP-019): Tipo de cada Detalle origen, resuelto al
    # leer desde la Orden origen. No se persiste en la garantia.
    detalles_origen: list[DetalleOrigenOut] = Field(default_factory=list)
    # PROC-REP-069: derivado del historial, no es un estado de workflow.
    finalizada_sin_reparacion: bool = False
    # E1: la Orden termino su proceso (entregada o devuelta a Gestion RT)
    # y solo puede consultarse. Derivado, no se persiste.
    cerrada: bool = False
    reparaciones_detail: list[DetalleOut]
    tomas: list[TomaOut]
    # E2: la toma vigente (tecnico, estacion, inicio), si la hay. Derivada
    # de ``tomas``: es lo que cualquier usuario necesita ver para saber
    # quien tiene la Orden.
    toma_activa: TomaOut | None = None
    ejecuciones: list[EjecucionOut]
    pagos: list[PagoOut]
    devoluciones_dinero: list[DevolucionDineroOut] = Field(
        default_factory=list
    )
    documentos: DocumentosOut
    resumen: ResumenComercialOut
    historial: list[HistorialOut]
    progreso: list[PasoProgresoOut]
    acciones_disponibles: list[AccionOut]
    # Cancelaciones posibles ahora (PROC-REP-300/305/306): capacidades
    # excepcionales, separadas de la accion del flujo.
    acciones_cancelacion: list[AccionOut] = Field(default_factory=list)
    # BR-REP-028: el Origen exige la decision del cliente por Detalle, y la
    # accion de registrarla si corresponde ahora (carril de Recepcion).
    autorizacion_requerida: bool = False
    acciones_autorizacion: list[AccionOut] = Field(default_factory=list)
    # Vista previa del desistimiento total (CLIENTE_EXTERNO con Detalles).
    desistimiento: DesistimientoOut | None = None
    # FEAT-REP-007: cobrar, anular un Pago o devolver dinero, si corresponde.
    acciones_financieras: list[AccionOut] = Field(default_factory=list)
    # Orden CANCELADA: devolucion fisica del equipo (registrada o pendiente).
    devolucion: DevolucionOut | None = None
    devolucion_pendiente: bool = False
    # Ingreso fisico y custodia (independiente del comprobante).
    recepcion: RecepcionOut | None = None
    custodia: CustodiaOut | None = None
    # Entrega de la Orden ENTREGADA: quien retiro el equipo.
    entrega: DevolucionOut | None = None
    # Documentos emitidos (sin contenido: ``GET .../documents``).
    documentos_emitidos: list[DocumentoResumenOut] = Field(
        default_factory=list
    )
    # Registrar o corregir el ingreso, confirmar la recepcion o registrar
    # "Equipo no recibido", observacion complementaria, nueva version del
    # comprobante de recepcion.
    acciones_custodia: list[AccionOut] = Field(default_factory=list)
    # Cambiar la prioridad, liberar la Orden de otro tecnico y ajustar la
    # garantia de un trabajo (MVP v2): no avanzan el proceso.
    acciones_complementarias: list[AccionOut] = Field(default_factory=list)
    # Historia de los descuentos (el ultimo es el vigente; sin tipo: quitado).
    descuentos: list[RegistroDescuento] = Field(default_factory=list)
    # Orden CANCELADA abierta: que falta para cerrarla (custodia, devolucion
    # fisica, saldo a favor). Vacio en los demas casos.
    pendientes_de_cierre: list[str] = Field(default_factory=list)
    # Situacion operativa para la pantalla (solo lectura).
    situacion: SituacionOut | None = None
    # Ingreso inicial de Cliente Externo: falta el comprobante de ingreso y
    # autorizacion (presentacion derivada).
    ingreso_inicial: bool = False
    # Fotos del equipo (UAT-010) y si el entorno tiene donde guardarlas.
    fotos: list[FotoOut] = Field(default_factory=list)
    fotos_habilitadas: bool = False
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
        detalles_origen: Sequence[DetalleOrigen] = (),
        acciones_cancelacion: Sequence[AccionDisponible] = (),
        acciones_autorizacion: Sequence[AccionDisponible] = (),
        acciones_financieras: Sequence[AccionDisponible] = (),
        acciones_custodia: Sequence[AccionDisponible] = (),
        acciones_complementarias: Sequence[AccionDisponible] = (),
        situacion: SituacionOperativa | None = None,
        fotos_habilitadas: bool = False,
    ) -> "OrdenOut":
        vigentes = _vigentes(orden)
        en_ingreso = es_ingreso_inicial(orden)
        del_ingreso = autorizados_en_el_ingreso(orden)
        return cls(
            id=orden.id,
            origen=orden.origen,
            estado_workflow=orden.estado_workflow,
            current_process=orden.current_process,
            prioridad=orden.prioridad,
            prioridad_texto=_texto_de_prioridad_vigente(orden),
            cliente=(
                ClienteOut(**orden.cliente.model_dump())
                if orden.cliente is not None
                else None
            ),
            equipo=EquipoOut(**orden.equipo.model_dump()),
            referencia_rt=orden.referencia_rt,
            orden_origen_id=orden.orden_origen_id,
            detalles_origen_ids=list(orden.detalles_origen_ids),
            detalles_origen=[
                DetalleOrigenOut(
                    id=origen.id,
                    tipo_reparacion_nombre=origen.tipo_reparacion_nombre,
                )
                for origen in detalles_origen
            ],
            finalizada_sin_reparacion=finalizada_sin_reparacion(orden),
            cerrada=orden.esta_cerrada,
            reparaciones_detail=[
                DetalleOut.desde_dominio(
                    detalle,
                    (insumos_previstos or {}).get(detalle.id, ()),
                    (nombres_de_tipo or {}).get(detalle.id),
                    estado_autorizacion=estado_autorizacion(orden, detalle),
                    situacion_autorizacion=situacion_autorizacion(
                        orden, detalle
                    ),
                    pendiente_comprobante_ingreso=en_ingreso
                    and estado_autorizacion(orden, detalle)
                    is EstadoAutorizacion.PENDIENTE,
                    autorizado_en_ingreso=estado_autorizacion(orden, detalle)
                    is EstadoAutorizacion.AUTORIZADO
                    and (detalle.id, detalle.version_definicion)
                    in del_ingreso,
                )
                for detalle in orden.reparaciones_detail
            ],
            tomas=[TomaOut.desde_dominio(toma) for toma in orden.tomas],
            toma_activa=_toma_activa_out(orden),
            ejecuciones=[
                EjecucionOut.desde_dominio(ejecucion)
                for ejecucion in orden.ejecuciones
            ],
            pagos=[
                PagoOut(
                    **pago.model_dump(exclude={"operacion_id"}),
                    vigente=pago.vigente,
                    devuelto=orden.resumen_pago.devuelto_de(pago.id),
                    devolvible=devolvible_de(orden, pago),
                )
                for pago in orden.resumen_pago.pagos
            ],
            devoluciones_dinero=[
                DevolucionDineroOut(
                    **devolucion.model_dump(exclude={"operacion_id"})
                )
                for devolucion in orden.resumen_pago.devoluciones
            ],
            documentos=DocumentosOut(**orden.documentos.model_dump()),
            resumen=_resumen_comercial(orden),
            historial=[
                HistorialOut.desde_dominio(paso) for paso in orden.historial
            ],
            progreso=[
                PasoProgresoOut.desde_dominio(paso) for paso in progreso
            ],
            acciones_disponibles=[
                AccionOut.desde_dominio(accion) for accion in acciones
            ],
            acciones_cancelacion=[
                AccionOut.desde_dominio(accion)
                for accion in acciones_cancelacion
            ],
            autorizacion_requerida=requiere_autorizacion_cliente(orden),
            desistimiento=(
                DesistimientoOut.desde_servicio(analizar_desistimiento(orden))
                if requiere_autorizacion_cliente(orden)
                and orden.reparaciones_detail
                else None
            ),
            acciones_autorizacion=[
                AccionOut.desde_dominio(accion)
                for accion in acciones_autorizacion
            ],
            acciones_financieras=[
                AccionOut.desde_dominio(accion)
                for accion in acciones_financieras
            ],
            devolucion=(
                DevolucionOut(**orden.devolucion.model_dump())
                if orden.devolucion is not None
                else None
            ),
            devolucion_pendiente=devolucion_pendiente(orden),
            recepcion=(
                RecepcionOut.desde_dominio(orden.recepcion)
                if orden.recepcion is not None
                else None
            ),
            custodia=CustodiaOut.desde_dominio(orden),
            entrega=(
                DevolucionOut(**orden.entrega.model_dump())
                if orden.entrega is not None
                else None
            ),
            documentos_emitidos=[
                DocumentoResumenOut(
                    **documento.model_dump(exclude={"contenido", "orden_id"}),
                    vigente=documento.id in vigentes,
                )
                for documento in orden.documentos.emitidos
            ],
            acciones_custodia=[
                AccionOut.desde_dominio(accion) for accion in acciones_custodia
            ],
            acciones_complementarias=[
                AccionOut.desde_dominio(accion)
                for accion in acciones_complementarias
            ],
            descuentos=list(orden.descuentos),
            pendientes_de_cierre=pendientes_para_cerrar(orden),
            situacion=(
                SituacionOut.desde_aplicacion(situacion)
                if situacion is not None
                else None
            ),
            ingreso_inicial=en_ingreso,
            fotos=[
                FotoOut(**foto.model_dump(exclude={"objeto"}))
                for foto in orden.fotos
            ],
            fotos_habilitadas=fotos_habilitadas,
            created_at=orden.created_at,
            updated_at=orden.updated_at,
        )


class AutorizacionDetalleOut(BaseModel):
    """La autorizacion de UN Detalle (``GET .../authorizations``).

    ``decision_vigente`` es la decision sobre la definicion vigente (si la
    hay); ``historial``, todas, de cualquier version. ``decidible``: se
    puede registrar ahora su decision.
    """

    detalle_id: str
    tipo_reparacion_id: str
    tipo_reparacion_nombre: str
    precio: Decimal
    version_definicion: int
    estado: EstadoAutorizacion
    situacion: SituacionAutorizacion
    decision_vigente: AutorizacionClienteOut | None = None
    historial: list[AutorizacionClienteOut] = Field(default_factory=list)
    decidible: bool

    @classmethod
    def desde_aplicacion(
        cls, autorizacion: AutorizacionDetalle
    ) -> "AutorizacionDetalleOut":
        vigente = autorizacion.decision_vigente
        return cls(
            detalle_id=autorizacion.detalle_id,
            tipo_reparacion_id=autorizacion.tipo_reparacion_id,
            tipo_reparacion_nombre=autorizacion.tipo_reparacion_nombre,
            precio=autorizacion.precio,
            version_definicion=autorizacion.version_definicion,
            estado=autorizacion.estado,
            situacion=autorizacion.situacion,
            decision_vigente=(
                AutorizacionClienteOut.desde_dominio(vigente)
                if vigente is not None
                else None
            ),
            historial=[
                AutorizacionClienteOut.desde_dominio(registro)
                for registro in autorizacion.historial
            ],
            decidible=autorizacion.decidible,
        )


class AutorizacionesOrdenOut(BaseModel):
    """``GET /api/orders/{id}/authorizations``."""

    orden_id: str
    requerida: bool
    registrable: bool
    detalles: list[AutorizacionDetalleOut]

    @classmethod
    def desde_aplicacion(
        cls, autorizaciones: AutorizacionesOrden
    ) -> "AutorizacionesOrdenOut":
        return cls(
            orden_id=autorizaciones.orden_id,
            requerida=autorizaciones.requerida,
            registrable=autorizaciones.registrable,
            detalles=[
                AutorizacionDetalleOut.desde_aplicacion(detalle)
                for detalle in autorizaciones.detalles
            ],
        )


class PendienteAutorizacionOut(BaseModel):
    """``GET /api/orders/authorizations/pending``: un Detalle pendiente."""

    orden_id: str
    cliente_nombre: str
    equipo: str
    detalle_id: str
    tipo_reparacion_nombre: str
    precio: Decimal
    version_definicion: int

    @classmethod
    def desde_aplicacion(
        cls, pendiente: PendienteAutorizacion
    ) -> "PendienteAutorizacionOut":
        return cls(
            orden_id=pendiente.orden_id,
            cliente_nombre=pendiente.cliente_nombre,
            equipo=pendiente.equipo,
            detalle_id=pendiente.detalle_id,
            tipo_reparacion_nombre=pendiente.tipo_reparacion_nombre,
            precio=pendiente.precio,
            version_definicion=pendiente.version_definicion,
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


class MovimientoFinancieroOut(BaseModel):
    """Un movimiento de dinero de la Orden (``GET .../finances``).

    ``efecto``: como movio el saldo (negativo lo baja: un Pago; positivo lo
    sube: una anulacion o una devolucion).
    """

    fecha: datetime
    tipo: str
    id: str
    pago_id: str
    monto: Decimal
    efecto: Decimal
    medio: str | None = None
    usuario_id: str
    detalle: str

    @classmethod
    def desde_aplicacion(
        cls, movimiento: MovimientoFinanciero
    ) -> "MovimientoFinancieroOut":
        return cls(
            fecha=movimiento.fecha,
            tipo=movimiento.tipo.value,
            id=movimiento.id,
            pago_id=movimiento.pago_id,
            monto=movimiento.monto,
            efecto=movimiento.efecto,
            medio=movimiento.medio,
            usuario_id=movimiento.usuario_id,
            detalle=movimiento.detalle,
        )


class DocumentosOrdenOut(BaseModel):
    """``GET /api/orders/{id}/documents``.

    ``emitidos``: todas las versiones, con su contenido. ``marcas``: lo que
    registro el proceso (una Orden anterior puede tener la marca sin copia
    del documento). ``previsualizables``: tipos con vista previa ahora.
    """

    orden_id: str
    cerrada: bool
    emitidos: list[DocumentoEmitidoOut]
    marcas: DocumentosOut
    previsualizables: list[TipoDocumento]


class VistaPreviaDocumentoOut(BaseModel):
    """Contenido de un documento con los datos vigentes. NO esta emitido."""

    orden_id: str
    tipo: TipoDocumento
    vista_previa: bool = True
    contenido: ContenidoDocumento


class FinanzasOrdenOut(BaseModel):
    """``GET /api/orders/{id}/finances``: saldo, credito y movimientos."""

    orden_id: str
    resumen: ResumenComercialOut
    movimientos: list[MovimientoFinancieroOut]

    @classmethod
    def desde_dominio(cls, orden: OrdenReparacion) -> "FinanzasOrdenOut":
        return cls(
            orden_id=orden.id,
            resumen=_resumen_comercial(orden),
            movimientos=[
                MovimientoFinancieroOut.desde_aplicacion(movimiento)
                for movimiento in movimientos_financieros(orden)
            ],
        )
