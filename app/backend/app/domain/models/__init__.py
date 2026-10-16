"""Modelos de dominio del MVP de Rosario Tecno RMA App.

Alcance: lo necesario para representar el escenario HP-REP-001
("Reparacion estandar de cliente externo") de PROC-REP V1.3. Los modelos
no leen ni derivan nada de ``business/``: esa sigue siendo la unica
fuente de verdad funcional, y aqui solo se conservan sus IDs
(``HistorialWorkflow.referencia_id``).
"""

from .catalogos import (
    DATOS_EMPRESA_PREDETERMINADOS,
    MEDIOS_PAGO_PREDETERMINADOS,
    DatosEmpresa,
    EstacionTrabajo,
    Insumo,
    MedioPago,
    TipoReparacion,
    TipoReparacionEstacion,
    TipoReparacionInsumos,
)
from .documentos import (
    CoberturaGarantia,
    ContenidoComprobanteAutorizacion,
    ContenidoComprobanteEntrega,
    ContenidoComprobanteRecepcion,
    ContenidoDocumento,
    ContenidoGarantia,
    DevolucionDineroEnDocumento,
    Documento,
    DocumentoEmitido,
    DocumentosOrden,
    PagoEnDocumento,
    TrabajoAutorizadoEnDocumento,
    TrabajoCanceladoEnDocumento,
    TrabajoEnDocumento,
    UsuarioEnDocumento,
)
from .enums import (
    CanalComunicacion,
    CondicionReparacionDetail,
    EstadoControl,
    EstadoCustodia,
    EstadoEjecucion,
    EstadoPago,
    EstadoReparacionDetail,
    EstadoTomaOrden,
    EstadoWorkflow,
    OrigenCancelacion,
    OrigenOrden,
    RegistroRecepcion,
    ResultadoAutorizacion,
    ResultadoControl,
    RolUsuario,
    TipoDocumento,
    TipoEntrega,
    TipoMovimientoInsumo,
    TipoPago,
    TipoReferenciaHistorial,
)
from .equipos import DevolucionEquipo, EntregaEquipo, Equipo
from .inventario import InsumoUtilizado, MovimientoInsumo, MovimientoStock
from .orden_reparacion import OrdenReparacion
from .pagos import AnulacionPago, DevolucionDinero, Pago, ResumenPago
from .personas import Cliente, Usuario
from .recepcion import (
    ConfirmacionRecepcion,
    DatosRecepcion,
    NoRecepcion,
    NotaRecepcion,
    RecepcionEquipo,
    VersionRecepcion,
)
from .reparacion import (
    DefinicionAnteriorDetalle,
    EjecucionReparacion,
    RegistroAutorizacionCliente,
    RegistroCancelacion,
    RegistroControlTecnico,
    ReparacionDetail,
    TomaOrden,
)
from .workflow import HistorialWorkflow

__all__ = [
    # Enums
    "CanalComunicacion",
    "CondicionReparacionDetail",
    "DefinicionAnteriorDetalle",
    "EstadoControl",
    "EstadoCustodia",
    "EstadoEjecucion",
    "EstadoPago",
    "EstadoReparacionDetail",
    "EstadoTomaOrden",
    "EstadoWorkflow",
    "OrigenCancelacion",
    "OrigenOrden",
    "RegistroRecepcion",
    "ResultadoAutorizacion",
    "ResultadoControl",
    "RolUsuario",
    "TipoDocumento",
    "TipoEntrega",
    "TipoMovimientoInsumo",
    "TipoPago",
    "TipoReferenciaHistorial",
    # Personas y equipo
    "Cliente",
    "DevolucionEquipo",
    "EntregaEquipo",
    "Equipo",
    "Usuario",
    # Recepcion y custodia
    "ConfirmacionRecepcion",
    "DatosRecepcion",
    "NoRecepcion",
    "NotaRecepcion",
    "RecepcionEquipo",
    "VersionRecepcion",
    # Catalogos
    "DATOS_EMPRESA_PREDETERMINADOS",
    "MEDIOS_PAGO_PREDETERMINADOS",
    "DatosEmpresa",
    "EstacionTrabajo",
    "Insumo",
    "MedioPago",
    "TipoReparacion",
    "TipoReparacionEstacion",
    "TipoReparacionInsumos",
    # Trabajo tecnico
    "EjecucionReparacion",
    "RegistroAutorizacionCliente",
    "RegistroCancelacion",
    "RegistroControlTecnico",
    "ReparacionDetail",
    "TomaOrden",
    # Inventario
    "InsumoUtilizado",
    "MovimientoInsumo",
    "MovimientoStock",
    # Pagos y devoluciones de dinero
    "AnulacionPago",
    "DevolucionDinero",
    "Pago",
    "ResumenPago",
    # Documentos
    "CoberturaGarantia",
    "ContenidoComprobanteAutorizacion",
    "ContenidoComprobanteEntrega",
    "ContenidoComprobanteRecepcion",
    "ContenidoDocumento",
    "ContenidoGarantia",
    "DevolucionDineroEnDocumento",
    "Documento",
    "DocumentoEmitido",
    "DocumentosOrden",
    "PagoEnDocumento",
    "TrabajoAutorizadoEnDocumento",
    "TrabajoCanceladoEnDocumento",
    "TrabajoEnDocumento",
    "UsuarioEnDocumento",
    # Workflow
    "HistorialWorkflow",
    # Aggregate raiz
    "OrdenReparacion",
]
