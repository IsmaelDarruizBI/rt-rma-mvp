"""Lectura del agregado Orden de Reparacion desde PostgreSQL (E4, A1).

Carga una o varias Ordenes con una consulta por tabla, filtrando por la
lista de Ordenes (``= ANY``): ``listar()`` no hace una consulta por
Orden. Cada lista sale con ``ORDER BY`` explicito (posicion, secuencia o
codigo), y cada fecha en UTC, como las del dominio.

Viajes a la base (cada uno cuesta lo que la red, no lo que la consulta):
las hijas salen juntas en un solo envio (``filas_en_lote``).
``cargar_en_un_envio`` suma la raiz a ese envio y es para quien ya tiene un
solo instante: una lectura ``REPEATABLE READ`` o una Orden bloqueada.
``cargar_ordenes`` lee la raiz primero: es la de un comando que lee Ordenes
sin bloquearlas, donde cada consulta ve su propio instante y quien llama
compara versiones (QA-A2-M2).

Ademas del dominio devuelve la ``Instantanea``: los uuid de cada fila y
la version persistida, que ``guardar`` usa para comparar lo que cambio
(DA-1) y para el control de version (DA-2).

Movimientos de insumo (A6): los de la Orden en ``rma.movimiento_inventario``,
por ``posicion``. El insumo vuelve a su ``clave`` y el Detalle, la Ejecucion
y el movimiento de origen, a su codigo.

Pagos, devoluciones de dinero y descuentos (A3): cada lista sale por
``posicion``; los importes, sin ceros decimales de mas (DE3-3). El medio
de pago y el pago de origen de una devolucion vuelven a ser codigos.

Dos datos se reconstruyen (A4):

- ``recepcion.datos.checkin``: con registros de check-in es el ultimo, porque
  un trigger impide actualizar ``rma.recepcion`` despues de decidir la
  custodia; sin registros, el del ingreso (``checkin_ingreso``).
- ``entrega`` o ``devolucion``: las dos son la unica fila de ``rma.salida``.
  El ``tipo`` no las distingue (una Orden sin reparacion tambien se entrega
  como devolucion), asi que decide el estado: ``entrega`` solo existe en una
  Orden ENTREGADA.

Diseno: ``docs/postgresql/e4-e7-diseno-integrado.md`` (seccion 4).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.domain.models import (
    Cliente,
    DocumentosOrden,
    Equipo,
    EstadoWorkflow,
    ExcepcionGarantia,
    HistorialWorkflow,
    InsumoUtilizado,
    MovimientoInsumo,
    OrdenReparacion,
    SolicitudDesistimiento,
    VigenciaGarantiaOrigen,
)
from app.domain.models.descuentos import RegistroDescuento
from app.domain.models.documentos import Documento, DocumentoEmitido
from app.domain.models.equipos import EntregaEquipo
from app.domain.models.fotos import FotoOrden
from app.domain.models.pagos import (
    AnulacionPago,
    DevolucionDinero,
    Pago,
    ResumenPago,
)
from app.domain.models.recepcion import (
    ConfirmacionRecepcion,
    DatosRecepcion,
    NoRecepcion,
    NotaRecepcion,
    RecepcionEquipo,
    RegistroCheckin,
    VersionRecepcion,
)
from app.domain.models.reparacion import (
    AjusteGarantia,
    DefinicionAnteriorDetalle,
    EjecucionReparacion,
    RegistroAutorizacionCliente,
    RegistroCancelacion,
    RegistroControlTecnico,
    ReparacionDetail,
    TomaOrden,
)
from app.repositories.exceptions import PersistenciaError

from .consultas import LECTURA, Consulta, consulta
from .ejecutor import LectorSql, Parametros
from .mapeo import decimal_sin_ceros


@dataclass
class Instantanea:
    """Lo persistido de una Orden, tal como lo cargo la transaccion."""

    orden: OrdenReparacion
    id: UUID
    version: int
    cliente: UUID | None
    equipo: UUID
    detalles: dict[str, UUID] = field(default_factory=dict)
    # Por Detalle: los uuid de sus versiones de definicion, en orden.
    versiones: dict[str, list[UUID]] = field(default_factory=dict)
    tomas: dict[str, UUID] = field(default_factory=dict)
    ejecuciones: dict[str, UUID] = field(default_factory=dict)
    tiene_recepcion: bool = False
    # El ``checkin_ingreso`` guardado: ``datos.checkin`` puede ser otro.
    checkin_ingreso: bool | None = None
    documentos: dict[str, UUID] = field(default_factory=dict)
    # Por codigo de Pago: su uuid (devoluciones e historial lo referencian).
    pagos: dict[str, UUID] = field(default_factory=dict)
    # Por codigo de movimiento: su uuid (un CONSUMO referencia su RESERVA).
    movimientos: dict[str, UUID] = field(default_factory=dict)
    # La que lleva la Orden entregada por ``obtener_para_modificar``. Sin
    # marca: la fila la creo esta misma transaccion (ver ``guardar``).
    marca: str | None = None


_ORDENES = consulta(
    "ordenes.cargar",
    """
    SELECT o.id, o.codigo, o.origen, o.estado_workflow, o.posicion_proceso,
           o.prioridad, o.referencia_rt, oo.codigo AS orden_origen,
           o.cliente_id, c.codigo AS cliente_codigo, o.cliente_nombre,
           o.cliente_documento_numero, o.cliente_telefono, o.cliente_email,
           o.equipo_id, e.codigo AS equipo_codigo, o.equipo_marca,
           o.equipo_modelo, o.equipo_variante, o.equipo_capacidad_texto,
           o.equipo_color, o.equipo_imei, o.equipo_numero_serie,
           o.equipo_tipo_producto_id, me.codigo AS modelo_tecnico,
           o.falla_reportada, o.comprobante_recepcion_generado_en,
           o.comprobante_final_generado_en, o.garantia_generada_en,
           o.version, o.creada_en, o.actualizado_en
    FROM rma.orden o
    JOIN rma.equipo e ON e.id = o.equipo_id
    LEFT JOIN rma.orden oo ON oo.id = o.orden_origen_id
    LEFT JOIN rma.cliente c ON c.id = o.cliente_id
    LEFT JOIN rma.modelo_equipo me ON me.id = o.equipo_modelo_equipo_id
    WHERE o.codigo = ANY(%(codigos)s)
    ORDER BY o.codigo COLLATE "C"
    """,
    modo=LECTURA,
)
# --- Filtros de las consultas dedicadas (E2, A5) ----------------------------
# Cada uno devuelve las candidatas con su version: ``(codigo, version)``.
# El resultado exacto lo decide el predicado del dominio sobre la Orden
# cargada (``ordenes.py``), el mismo que usa JSON.

FILTRO_UNA = consulta(
    "ordenes.filtro_una",
    "SELECT codigo, version FROM rma.orden WHERE codigo = %(codigo)s",
    modo=LECTURA,
)
FILTRO_TODAS = consulta(
    "ordenes.filtro_todas",
    "SELECT codigo, version FROM rma.orden",
    modo=LECTURA,
)
# ``esta_cerrada``: ENTREGADA o devuelta a Gestion RT (EVT-REP-999).
FILTRO_ABIERTAS = consulta(
    "ordenes.filtro_abiertas",
    """
    SELECT codigo, version FROM rma.orden
    WHERE estado_workflow <> 'ENTREGADA'
      AND posicion_proceso IS DISTINCT FROM 'EVT-REP-999'
    """,
    modo=LECTURA,
)
# QA-A2-L1: la copia del cliente en la Orden, como JSON; no el documento
# vigente del Cliente compartido.
FILTRO_DNI = consulta(
    "ordenes.filtro_dni",
    """
    SELECT codigo, version FROM rma.orden
    WHERE cliente_id IS NOT NULL AND cliente_documento_numero = %(dni)s
    """,
    modo=LECTURA,
)
# ``claves`` nulo: cualquier insumo. Toda Orden con alguna RESERVA, como
# JSON (el contrato admite tambien las ya consumidas o liberadas).
FILTRO_RESERVAS = consulta(
    "ordenes.filtro_reservas",
    """
    SELECT o.codigo, o.version FROM rma.orden o
    WHERE EXISTS (
        SELECT 1 FROM rma.movimiento_inventario m
        JOIN rma.insumo i ON i.id = m.insumo_id
        WHERE m.orden_id = o.id AND m.tipo = 'RESERVA'
          AND (%(claves)s::text[] IS NULL OR i.clave = ANY(%(claves)s))
    )
    """,
    modo=LECTURA,
)
FILTRO_MOVIMIENTOS = consulta(
    "ordenes.filtro_movimientos",
    """
    SELECT o.codigo, o.version FROM rma.orden o
    WHERE EXISTS (
        SELECT 1 FROM rma.movimiento_inventario m
        JOIN rma.insumo i ON i.id = m.insumo_id
        WHERE m.orden_id = o.id
          AND (%(clave)s::text IS NULL OR i.clave = %(clave)s)
    )
    """,
    modo=LECTURA,
)
VERSIONES = consulta(
    "ordenes.versiones",
    "SELECT codigo, version FROM rma.orden WHERE codigo = ANY(%(codigos)s)",
    modo=LECTURA,
)
CLAVES_DE_FOTOS = consulta(
    "ordenes.claves_de_fotos",
    "SELECT objeto_clave FROM rma.foto",
    modo=LECTURA,
)
_ORIGEN = consulta(
    "ordenes.detalles_origen",
    """
    SELECT x.orden_id, d.codigo, x.garantia_dias, x.garantia_vence,
           x.garantia_vigente, ue.codigo AS excepcion_por, x.excepcion_en,
           x.excepcion_motivo
    FROM rma.orden_detalle_origen x
    JOIN rma.detalle d ON d.id = x.detalle_id
    LEFT JOIN rma.usuario ue ON ue.id = x.excepcion_por
    WHERE x.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY x.orden_id, x.posicion, d.codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_RECEPCION = consulta(
    "ordenes.recepcion",
    """
    SELECT r.orden_id, r.registro, r.estado_fisico, r.accesorios,
           r.observaciones, r.notas_internas, r.checkin_ingreso,
           ur.codigo AS registrado_por, r.registrado_en,
           uc.codigo AS confirmada_por, r.confirmada_en,
           r.confirmacion_observaciones,
           un.codigo AS no_recibido_por, r.no_recibido_en,
           r.no_recibido_motivo
    FROM rma.recepcion r
    JOIN rma.usuario ur ON ur.id = r.registrado_por
    LEFT JOIN rma.usuario uc ON uc.id = r.confirmada_por
    LEFT JOIN rma.usuario un ON un.id = r.no_recibido_por
    WHERE r.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    """,
    modo=LECTURA,
)
_DETALLES = consulta(
    "ordenes.detalles",
    """
    SELECT d.orden_id, d.id, d.codigo, d.estado, d.condicion,
           d.control_estado, uc.codigo AS control_usuario, d.control_en,
           d.control_observaciones, d.garantia_dias,
           d.garantia_dias_sugerida, od.codigo AS detalle_origen,
           d.observaciones, d.cancelacion_origen, d.cancelacion_motivo,
           ux.codigo AS cancelado_por, d.cancelado_en,
           us.codigo AS desistimiento_solicitado_por,
           d.desistimiento_solicitado_en, d.desistimiento_motivo,
           d.desistimiento_canal
    FROM rma.detalle d
    LEFT JOIN rma.usuario uc ON uc.id = d.control_usuario_id
    LEFT JOIN rma.usuario ux ON ux.id = d.cancelado_por
    LEFT JOIN rma.usuario us ON us.id = d.desistimiento_solicitado_por
    LEFT JOIN rma.detalle od ON od.id = d.detalle_origen_id
    WHERE d.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY d.orden_id, d.codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_VERSIONES = consulta(
    "ordenes.versiones_detalle",
    """
    SELECT v.detalle_id, v.id, v.numero, t.codigo AS tipo, v.descripcion,
           v.precio, v.puntaje, v.garantia_dias,
           u.codigo AS definida_por, v.definida_en,
           v.garantia_dias_reemplazada
    FROM rma.detalle_version v
    JOIN rma.detalle d ON d.id = v.detalle_id
    JOIN rma.tipo_reparacion t ON t.id = v.tipo_reparacion_id
    LEFT JOIN rma.usuario u ON u.id = v.definida_por
    WHERE d.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY v.detalle_id, v.numero
    """,
    modo=LECTURA,
)
_DECISIONES = consulta(
    "ordenes.decisiones",
    """
    SELECT v.detalle_id, v.numero, c.resultado, c.canal,
           u.codigo AS usuario, c.registrada_en, c.observaciones
    FROM rma.decision_cliente c
    JOIN rma.detalle_version v ON v.id = c.detalle_version_id
    JOIN rma.detalle d ON d.id = v.detalle_id
    JOIN rma.usuario u ON u.id = c.usuario_id
    WHERE d.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY v.detalle_id, c.posicion, c.registrada_en, c.id
    """,
    modo=LECTURA,
)
_AJUSTES = consulta(
    "ordenes.ajustes_garantia",
    """
    SELECT a.detalle_id, a.dias_anteriores, a.dias_nuevos, a.motivo,
           u.codigo AS usuario, a.registrado_en
    FROM rma.ajuste_garantia a
    JOIN rma.detalle d ON d.id = a.detalle_id
    JOIN rma.usuario u ON u.id = a.usuario_id
    WHERE d.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY a.detalle_id, a.posicion, a.registrado_en, a.id
    """,
    modo=LECTURA,
)
_CONTROLES = consulta(
    "ordenes.controles",
    """
    SELECT c.detalle_id, c.resultado, u.codigo AS usuario, c.registrado_en,
           c.observaciones, x.codigo AS ejecucion
    FROM rma.control_tecnico c
    JOIN rma.detalle d ON d.id = c.detalle_id
    JOIN rma.usuario u ON u.id = c.usuario_id
    LEFT JOIN rma.ejecucion x ON x.id = c.ejecucion_id
    WHERE d.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY c.detalle_id, c.posicion, c.registrado_en, c.id
    """,
    modo=LECTURA,
)
_TOMAS = consulta(
    "ordenes.tomas",
    """
    SELECT t.orden_id, t.id, t.codigo, u.codigo AS usuario,
           m.codigo AS estacion, t.estado, t.inicio, t.fin,
           l.codigo AS liberada_por, t.motivo_liberacion
    FROM rma.toma t
    JOIN rma.usuario u ON u.id = t.usuario_id
    JOIN rma.mesa_trabajo m ON m.id = t.mesa_trabajo_id
    LEFT JOIN rma.usuario l ON l.id = t.liberada_por
    WHERE t.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY t.orden_id, t.posicion, t.inicio, t.codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_EJECUCIONES = consulta(
    "ordenes.ejecuciones",
    """
    SELECT x.orden_id, x.id, x.codigo, d.codigo AS detalle,
           t.codigo AS toma, u.codigo AS usuario, x.estado, x.inicio, x.fin,
           x.observaciones, x.motivo_interrupcion, x.motivo_redefinicion,
           x.estado_trabajo, x.reversible
    FROM rma.ejecucion x
    JOIN rma.detalle d ON d.id = x.detalle_id
    JOIN rma.toma t ON t.id = x.toma_id
    JOIN rma.usuario u ON u.id = x.usuario_id
    WHERE x.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY x.orden_id, x.posicion, x.inicio, x.codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_INSUMOS_UTILIZADOS = consulta(
    "ordenes.insumos_utilizados",
    """
    SELECT ei.ejecucion_id, i.clave AS insumo, ei.cantidad_utilizada
    FROM rma.ejecucion_insumo ei
    JOIN rma.ejecucion x ON x.id = ei.ejecucion_id
    JOIN rma.insumo i ON i.id = ei.insumo_id
    WHERE x.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY ei.ejecucion_id, ei.posicion, i.clave COLLATE "C"
    """,
    modo=LECTURA,
)
_VERSIONES_RECEPCION = consulta(
    "ordenes.versiones_recepcion",
    """
    SELECT v.orden_id, v.datos, r.codigo AS registrado_por, v.registrado_en,
           p.codigo AS reemplazado_por, v.reemplazado_en
    FROM rma.recepcion_version v
    JOIN rma.usuario r ON r.id = v.registrado_por
    JOIN rma.usuario p ON p.id = v.reemplazado_por
    WHERE v.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY v.orden_id, v.posicion NULLS FIRST, v.reemplazado_en,
             v.registrado_en, v.id
    """,
    modo=LECTURA,
)
_NOTAS_RECEPCION = consulta(
    "ordenes.notas_recepcion",
    """
    SELECT n.orden_id, u.codigo AS usuario, n.registrada_en, n.texto,
           n.interna
    FROM rma.recepcion_nota n
    JOIN rma.usuario u ON u.id = n.usuario_id
    WHERE n.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY n.orden_id, n.posicion NULLS FIRST, n.registrada_en, n.id
    """,
    modo=LECTURA,
)
_CHECKINS = consulta(
    "ordenes.checkins",
    """
    SELECT c.orden_id, c.realizado, u.codigo AS usuario, c.registrado_en
    FROM rma.checkin c
    JOIN rma.usuario u ON u.id = c.usuario_id
    WHERE c.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY c.orden_id, c.posicion NULLS FIRST, c.registrado_en, c.id
    """,
    modo=LECTURA,
)
_FOTOS = consulta(
    "ordenes.fotos",
    """
    SELECT f.orden_id, f.codigo, f.objeto_clave, f.tipo_contenido,
           f.tamano_bytes, u.codigo AS usuario, f.registrada_en,
           f.nombre_original
    FROM rma.foto f
    JOIN rma.usuario u ON u.id = f.usuario_id
    WHERE f.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY f.orden_id, f.posicion NULLS FIRST, f.registrada_en,
             f.codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_DOCUMENTOS = consulta(
    "ordenes.documentos",
    """
    SELECT d.orden_id, d.id, d.codigo, d.tipo, d.version, d.emitido_en,
           u.codigo AS usuario, d.motivo, r.codigo AS reemplaza,
           d.contenido
    FROM rma.documento_emitido d
    LEFT JOIN rma.usuario u ON u.id = d.usuario_id
    LEFT JOIN rma.documento_emitido r ON r.id = d.reemplaza_a
    WHERE d.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY d.orden_id, d.posicion NULLS FIRST, d.emitido_en, d.version,
             d.codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_SALIDAS = consulta(
    "ordenes.salidas",
    """
    SELECT s.orden_id, s.tipo, u.codigo AS entregado_por, s.retira_nombre,
           s.retira_identificacion, s.registrada_en, s.observaciones
    FROM rma.salida s
    JOIN rma.usuario u ON u.id = s.entregado_por
    WHERE s.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    """,
    modo=LECTURA,
)
_PAGOS = consulta(
    "ordenes.pagos",
    """
    SELECT p.orden_id, p.id, p.codigo, p.monto, p.tipo_pago,
           m.codigo AS metodo, u.codigo AS usuario, p.registrado_en,
           p.referencia, p.operacion_id, a.codigo AS anulado_por,
           p.anulado_en, p.anulacion_motivo
    FROM rma.pago p
    JOIN rma.medio_pago m ON m.id = p.medio_pago_id
    JOIN rma.usuario u ON u.id = p.usuario_id
    LEFT JOIN rma.usuario a ON a.id = p.anulado_por
    WHERE p.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY p.orden_id, p.posicion NULLS FIRST, p.registrado_en,
             p.codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_DEVOLUCIONES = consulta(
    "ordenes.devoluciones_dinero",
    """
    SELECT d.orden_id, d.codigo, p.codigo AS pago, d.monto,
           m.codigo AS medio, u.codigo AS usuario, d.registrada_en,
           d.motivo, d.referencia, d.operacion_id
    FROM rma.devolucion_dinero d
    JOIN rma.pago p ON p.id = d.pago_id
    JOIN rma.medio_pago m ON m.id = d.medio_pago_id
    JOIN rma.usuario u ON u.id = d.usuario_id
    WHERE d.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY d.orden_id, d.posicion NULLS FIRST, d.registrada_en,
             d.codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_DESCUENTOS = consulta(
    "ordenes.descuentos",
    """
    SELECT d.orden_id, d.tipo, d.valor, d.motivo, u.codigo AS usuario,
           d.registrado_en, d.clase
    FROM rma.descuento d
    JOIN rma.usuario u ON u.id = d.usuario_id
    WHERE d.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY d.orden_id, d.posicion NULLS FIRST, d.registrado_en, d.id
    """,
    modo=LECTURA,
)
_MOVIMIENTOS = consulta(
    "ordenes.movimientos_insumo",
    """
    SELECT m.orden_id, m.id, m.codigo, m.tipo, i.clave AS insumo,
           d.codigo AS detalle, x.codigo AS ejecucion, o.codigo AS origen,
           m.cantidad, u.codigo AS usuario, m.registrado_en, m.observacion
    FROM rma.movimiento_inventario m
    JOIN rma.insumo i ON i.id = m.insumo_id
    JOIN rma.detalle d ON d.id = m.detalle_id
    LEFT JOIN rma.ejecucion x ON x.id = m.ejecucion_id
    LEFT JOIN rma.movimiento_inventario o ON o.id = m.movimiento_origen_id
    LEFT JOIN rma.usuario u ON u.id = m.usuario_id
    WHERE m.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
    ORDER BY m.orden_id, m.posicion NULLS FIRST, m.registrado_en,
             m.codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_HISTORIAL = consulta(
    "ordenes.historial",
    """
    SELECT e.orden_id, e.historial_tipo_referencia AS tipo_referencia,
           e.historial_referencia_id AS referencia_id,
           e.historial_accion AS accion, e.ocurrido_en,
           u.codigo AS usuario, d.codigo AS detalle, x.codigo AS ejecucion,
           p.codigo AS pago, e.observacion
    FROM rma.evento_negocio e
    LEFT JOIN rma.usuario u ON u.id = e.usuario_id
    LEFT JOIN rma.detalle d ON d.id = e.detalle_id
    LEFT JOIN rma.ejecucion x ON x.id = e.ejecucion_id
    LEFT JOIN rma.pago p ON p.id = e.pago_id
    WHERE e.orden_id = ANY(ARRAY(
        SELECT id FROM rma.orden WHERE codigo = ANY(%(codigos)s)
    ))
      AND e.historial_referencia_id IS NOT NULL
    ORDER BY e.orden_id, e.secuencia
    """,
    modo=LECTURA,
)


@dataclass(frozen=True)
class _Hija:
    """Una tabla del agregado: como se lee y por que columna se agrupa.
    ``unica``: a lo sumo una fila por Orden."""

    nombre: str
    consulta: Consulta
    columna: str = "orden_id"
    unica: bool = False


_HIJAS = (
    _Hija("origen", _ORIGEN),
    _Hija("recepcion", _RECEPCION, unica=True),
    _Hija("detalles", _DETALLES),
    _Hija("versiones", _VERSIONES, columna="detalle_id"),
    _Hija("decisiones", _DECISIONES, columna="detalle_id"),
    _Hija("ajustes", _AJUSTES, columna="detalle_id"),
    _Hija("controles", _CONTROLES, columna="detalle_id"),
    _Hija("tomas", _TOMAS),
    _Hija("ejecuciones", _EJECUCIONES),
    _Hija("insumos", _INSUMOS_UTILIZADOS, columna="ejecucion_id"),
    _Hija("historial", _HISTORIAL),
    _Hija("versiones_recepcion", _VERSIONES_RECEPCION),
    _Hija("notas", _NOTAS_RECEPCION),
    _Hija("checkins", _CHECKINS),
    _Hija("fotos", _FOTOS),
    _Hija("documentos", _DOCUMENTOS),
    _Hija("salidas", _SALIDAS, unica=True),
    _Hija("pagos", _PAGOS),
    _Hija("devoluciones", _DEVOLUCIONES),
    _Hija("descuentos", _DESCUENTOS),
    _Hija("movimientos", _MOVIMIENTOS),
)


def utc(valor: datetime | None) -> datetime | None:
    """La fecha en UTC, como las del dominio (``contexto.ahora``)."""
    return None if valor is None else valor.astimezone(timezone.utc)


def versiones_de(lector: LectorSql, codigos: list[str]) -> dict[str, int]:
    """La version persistida de cada Orden de ``codigos`` (QA-A2-M2)."""
    return {
        f.codigo: f.version
        for f in lector.filas(VERSIONES, {"codigos": list(codigos)})
    }


def claves_de_fotos(lector: LectorSql) -> frozenset[str]:
    """Las claves de objeto de todas las fotos, en una sola consulta."""
    return frozenset(f.objeto_clave for f in lector.filas(CLAVES_DE_FOTOS))


def cargar_ordenes(lector: LectorSql, codigos: list[str]) -> list[Instantanea]:
    """Las Ordenes de ``codigos`` que existen, por numero ascendente."""
    if not codigos:
        return []
    raices = lector.filas(_ORDENES, {"codigos": list(codigos)})
    if not raices:
        return []
    por_orden = _agrupar_hijas(lector, [raiz.codigo for raiz in raices])
    return [_armar(raiz, por_orden) for raiz in raices]


def cargar_en_un_envio(
    lector: LectorSql,
    codigos: list[str],
    antes: tuple[Consulta, Parametros] | None = None,
) -> list[Instantanea]:
    """Como ``cargar_ordenes``, con la raiz en el mismo envio que las hijas.

    Solo con un instante asegurado (ver el modulo). ``antes`` corre primero
    en ese envio: la base ejecuta las consultas en orden, asi que las que
    siguen a un bloqueo leen despues de obtenerlo.
    """
    if not codigos:
        return []
    parametros = {"codigos": list(codigos)}
    pedidos = [(_ORDENES, parametros), *_pedidos_de_hijas(parametros)]
    if antes is not None:
        pedidos.insert(0, antes)
    lotes = lector.filas_en_lote(pedidos)
    if antes is not None:
        lotes = lotes[1:]
    raices, hijas = lotes[0], lotes[1:]
    por_orden = _agrupadas(hijas)
    return [_armar(raiz, por_orden) for raiz in raices]


def _pedidos_de_hijas(
    parametros: dict[str, Any],
) -> list[tuple[Consulta, Any]]:
    return [(hija.consulta, parametros) for hija in _HIJAS]


def _agrupar_hijas(lector: LectorSql, codigos: list[str]) -> dict[str, Any]:
    parametros = {"codigos": list(codigos)}
    return _agrupadas(lector.filas_en_lote(_pedidos_de_hijas(parametros)))


def _agrupadas(lotes: list[list[Any]]) -> dict[str, Any]:
    """Las filas de cada hija, por la columna que la une al agregado."""
    agrupadas: dict[str, Any] = {}
    for hija, filas in zip(_HIJAS, lotes, strict=True):
        if hija.unica:
            agrupadas[hija.nombre] = {
                getattr(fila, hija.columna): fila for fila in filas
            }
            continue
        grupos: dict[UUID, list[Any]] = defaultdict(list)
        for fila in filas:
            grupos[getattr(fila, hija.columna)].append(fila)
        agrupadas[hija.nombre] = grupos
    return agrupadas


def _armar(raiz: Any, hijas: dict[str, Any]) -> Instantanea:
    detalles, versiones_por_detalle, detalles_ids = _detalles(
        hijas["detalles"].get(raiz.id, []), hijas
    )
    tomas = [_toma(fila) for fila in hijas["tomas"].get(raiz.id, [])]
    filas_ejecucion = hijas["ejecuciones"].get(raiz.id, [])
    filas_documento = hijas["documentos"].get(raiz.id, [])
    salida = _salida(hijas["salidas"].get(raiz.id))
    entregada = raiz.estado_workflow == EstadoWorkflow.ENTREGADA.value
    fila_recepcion = hijas["recepcion"].get(raiz.id)
    filas_pago = hijas["pagos"].get(raiz.id, [])
    filas_movimiento = hijas["movimientos"].get(raiz.id, [])
    orden = OrdenReparacion(
        id=raiz.codigo,
        origen=raiz.origen,
        estado_workflow=raiz.estado_workflow,
        current_process=raiz.posicion_proceso,
        cliente=_cliente(raiz),
        equipo=Equipo(
            id=raiz.equipo_codigo,
            marca=raiz.equipo_marca,
            modelo=raiz.equipo_modelo,
            falla_reportada=raiz.falla_reportada,
            imei=raiz.equipo_imei,
            numero_serie=raiz.equipo_numero_serie,
            tipo_producto_id=raiz.equipo_tipo_producto_id,
            modelo_tecnico_id=raiz.modelo_tecnico,
            variante=raiz.equipo_variante,
            capacidad=raiz.equipo_capacidad_texto,
            color=raiz.equipo_color,
        ),
        referencia_rt=raiz.referencia_rt,
        orden_origen_id=raiz.orden_origen,
        detalles_origen_ids=[
            fila.codigo for fila in hijas["origen"].get(raiz.id, [])
        ],
        vigencia_garantia_origen=[
            VigenciaGarantiaOrigen(
                detalle_id=fila.codigo,
                garantia_dias=fila.garantia_dias,
                vence=fila.garantia_vence,
                vigente=fila.garantia_vigente,
                excepcion=(
                    None
                    if fila.excepcion_en is None
                    else ExcepcionGarantia(
                        usuario_id=fila.excepcion_por,
                        fecha=utc(fila.excepcion_en),
                        motivo=fila.excepcion_motivo,
                    )
                ),
            )
            for fila in hijas["origen"].get(raiz.id, [])
            if fila.garantia_vigente is not None
        ],
        prioridad=raiz.prioridad,
        reparaciones_detail=detalles,
        tomas=tomas,
        ejecuciones=[
            _ejecucion(fila, hijas["insumos"].get(fila.id, []))
            for fila in filas_ejecucion
        ],
        documentos=DocumentosOrden(
            comprobante_recepcion=_documento(
                raiz.comprobante_recepcion_generado_en
            ),
            comprobante_final=_documento(raiz.comprobante_final_generado_en),
            garantia_reparacion=_documento(raiz.garantia_generada_en),
            emitidos=[
                _documento_emitido(fila, raiz.codigo)
                for fila in filas_documento
            ],
        ),
        historial=[
            _paso(fila) for fila in hijas["historial"].get(raiz.id, [])
        ],
        recepcion=_recepcion(fila_recepcion, raiz.id, hijas),
        fotos=[_foto(fila) for fila in hijas["fotos"].get(raiz.id, [])],
        resumen_pago=ResumenPago(
            pagos=[_pago(fila) for fila in filas_pago],
            devoluciones=[
                _devolucion(fila)
                for fila in hijas["devoluciones"].get(raiz.id, [])
            ],
        ),
        descuentos=[
            _descuento(fila) for fila in hijas["descuentos"].get(raiz.id, [])
        ],
        movimientos_insumo=[_movimiento(fila) for fila in filas_movimiento],
        devolucion=None if entregada else salida,
        entrega=salida if entregada else None,
        created_at=utc(raiz.creada_en),
        updated_at=utc(raiz.actualizado_en or raiz.creada_en),
    )
    return Instantanea(
        orden=orden,
        id=raiz.id,
        version=raiz.version,
        cliente=raiz.cliente_id,
        equipo=raiz.equipo_id,
        detalles=detalles_ids,
        versiones=versiones_por_detalle,
        tomas={
            fila.codigo: fila.id for fila in hijas["tomas"].get(raiz.id, [])
        },
        ejecuciones={fila.codigo: fila.id for fila in filas_ejecucion},
        tiene_recepcion=fila_recepcion is not None,
        checkin_ingreso=(
            fila_recepcion.checkin_ingreso if fila_recepcion else None
        ),
        documentos={fila.codigo: fila.id for fila in filas_documento},
        pagos={fila.codigo: fila.id for fila in filas_pago},
        movimientos={fila.codigo: fila.id for fila in filas_movimiento},
    )


def _cliente(raiz: Any) -> Cliente | None:
    if raiz.cliente_codigo is None:
        return None
    return Cliente(
        id=raiz.cliente_codigo,
        dni=raiz.cliente_documento_numero,
        nombre_apellido=raiz.cliente_nombre,
        telefono=raiz.cliente_telefono,
        email=raiz.cliente_email,
    )


def _documento(generado_en: datetime | None) -> Documento:
    if generado_en is None:
        return Documento()
    return Documento(generado=True, fecha_generacion=utc(generado_en))


def _recepcion(
    fila: Any, orden_id: UUID, hijas: dict[str, Any]
) -> RecepcionEquipo | None:
    if fila is None:
        return None
    registros = [
        RegistroCheckin(
            realizado=checkin.realizado,
            usuario_id=checkin.usuario,
            fecha=utc(checkin.registrado_en),
        )
        for checkin in hijas["checkins"].get(orden_id, [])
    ]
    confirmacion = None
    if fila.confirmada_en is not None:
        confirmacion = ConfirmacionRecepcion(
            usuario_id=fila.confirmada_por,
            fecha=utc(fila.confirmada_en),
            observaciones=fila.confirmacion_observaciones,
        )
    no_recibido = None
    if fila.no_recibido_en is not None:
        no_recibido = NoRecepcion(
            usuario_id=fila.no_recibido_por,
            fecha=utc(fila.no_recibido_en),
            motivo=fila.no_recibido_motivo,
        )
    return RecepcionEquipo(
        registro=fila.registro,
        datos=DatosRecepcion(
            estado_fisico=fila.estado_fisico,
            accesorios=list(fila.accesorios),
            observaciones=fila.observaciones,
            checkin=(
                registros[-1].realizado if registros else fila.checkin_ingreso
            ),
            notas_internas=fila.notas_internas,
        ),
        registrado_por=fila.registrado_por,
        registrado_en=utc(fila.registrado_en),
        versiones_anteriores=[
            VersionRecepcion(
                equipo=version.datos["equipo"],
                datos=version.datos["datos"],
                registrado_por=version.registrado_por,
                registrado_en=utc(version.registrado_en),
                reemplazado_por=version.reemplazado_por,
                reemplazado_en=utc(version.reemplazado_en),
            )
            for version in hijas["versiones_recepcion"].get(orden_id, [])
        ],
        confirmacion=confirmacion,
        no_recibido=no_recibido,
        notas=[
            NotaRecepcion(
                usuario_id=nota.usuario,
                fecha=utc(nota.registrada_en),
                texto=nota.texto,
                interna=nota.interna,
            )
            for nota in hijas["notas"].get(orden_id, [])
        ],
        registros_checkin=registros,
    )


def _foto(fila: Any) -> FotoOrden:
    return FotoOrden(
        id=fila.codigo,
        objeto=fila.objeto_clave,
        tipo_contenido=fila.tipo_contenido,
        tamano_bytes=fila.tamano_bytes,
        usuario_id=fila.usuario,
        fecha=utc(fila.registrada_en),
        nombre_original=fila.nombre_original,
    )


def _documento_emitido(fila: Any, orden_id: str) -> DocumentoEmitido:
    return DocumentoEmitido(
        id=fila.codigo,
        tipo=fila.tipo,
        orden_id=orden_id,
        version=fila.version,
        fecha_emision=utc(fila.emitido_en),
        usuario_id=fila.usuario,
        motivo=fila.motivo,
        reemplaza_a=fila.reemplaza,
        contenido=fila.contenido,
    )


def _pago(fila: Any) -> Pago:
    anulacion = None
    if fila.anulado_en is not None:
        anulacion = AnulacionPago(
            usuario_id=fila.anulado_por,
            fecha=utc(fila.anulado_en),
            motivo=fila.anulacion_motivo,
        )
    return Pago(
        id=fila.codigo,
        monto=decimal_sin_ceros(fila.monto),
        tipo_pago=fila.tipo_pago,
        metodo=fila.metodo,
        usuario_id=fila.usuario,
        fecha=utc(fila.registrado_en),
        referencia=fila.referencia,
        operacion_id=fila.operacion_id,
        anulacion=anulacion,
    )


def _devolucion(fila: Any) -> DevolucionDinero:
    return DevolucionDinero(
        id=fila.codigo,
        pago_id=fila.pago,
        monto=decimal_sin_ceros(fila.monto),
        medio=fila.medio,
        usuario_id=fila.usuario,
        fecha=utc(fila.registrada_en),
        motivo=fila.motivo,
        referencia=fila.referencia,
        operacion_id=fila.operacion_id,
    )


def _descuento(fila: Any) -> RegistroDescuento:
    return RegistroDescuento(
        tipo=fila.tipo,
        valor=None if fila.valor is None else decimal_sin_ceros(fila.valor),
        motivo=fila.motivo,
        usuario_id=fila.usuario,
        fecha=utc(fila.registrado_en),
        clase=fila.clase,
    )


def _movimiento(fila: Any) -> MovimientoInsumo:
    return MovimientoInsumo(
        id=fila.codigo,
        tipo=fila.tipo,
        insumo_id=fila.insumo,
        reparacion_detail_id=fila.detalle,
        ejecucion_id=fila.ejecucion,
        cantidad=decimal_sin_ceros(fila.cantidad),
        movimiento_origen_id=fila.origen,
        usuario_id=fila.usuario,
        fecha=utc(fila.registrado_en),
        observacion=fila.observacion,
    )


def _salida(fila: Any) -> EntregaEquipo | None:
    if fila is None:
        return None
    return EntregaEquipo(
        tipo=fila.tipo,
        entregado_por=fila.entregado_por,
        recibido_por=fila.retira_nombre,
        identificacion_receptor=fila.retira_identificacion,
        fecha=utc(fila.registrada_en),
        observaciones=fila.observaciones,
    )


def _detalles(
    filas: list[Any], hijas: dict[str, Any]
) -> tuple[list[ReparacionDetail], dict[str, list[UUID]], dict[str, UUID]]:
    detalles = []
    versiones_por_detalle: dict[str, list[UUID]] = {}
    ids: dict[str, UUID] = {}
    for fila in filas:
        versiones = hijas["versiones"].get(fila.id, [])
        if not versiones:
            raise PersistenciaError(
                f"El Detalle {fila.codigo} no tiene version de definicion."
            )
        vigente = versiones[-1]
        anteriores = [
            # La version k la reemplazo la k+1: quien, cuando y con que
            # garantia quedo la k se guarda en la fila k+1.
            DefinicionAnteriorDetalle(
                tipo_reparacion_id=version.tipo,
                precio=decimal_sin_ceros(version.precio),
                puntaje=version.puntaje,
                garantia_dias=siguiente.garantia_dias_reemplazada,
                reemplazada_en=utc(siguiente.definida_en),
                usuario_id=siguiente.definida_por,
            )
            for version, siguiente in zip(versiones, versiones[1:])
        ]
        numero_de = {version.numero: version for version in versiones}
        cancelacion = None
        if fila.cancelado_en is not None:
            cancelacion = RegistroCancelacion(
                usuario_id=fila.cancelado_por,
                fecha=utc(fila.cancelado_en),
                motivo=fila.cancelacion_motivo,
                origen=fila.cancelacion_origen,
            )
        detalles.append(
            ReparacionDetail(
                id=fila.codigo,
                tipo_reparacion_id=vigente.tipo,
                descripcion=vigente.descripcion,
                precio=decimal_sin_ceros(vigente.precio),
                puntaje=vigente.puntaje,
                garantia_dias=fila.garantia_dias,
                garantia_dias_sugerida=fila.garantia_dias_sugerida,
                ajustes_garantia=[
                    AjusteGarantia(
                        dias_anteriores=ajuste.dias_anteriores,
                        dias_nuevos=ajuste.dias_nuevos,
                        motivo=ajuste.motivo,
                        usuario_id=ajuste.usuario,
                        fecha=utc(ajuste.registrado_en),
                    )
                    for ajuste in hijas["ajustes"].get(fila.id, [])
                ],
                estado=fila.estado,
                condicion=fila.condicion,
                control_estado=fila.control_estado,
                control_usuario_id=fila.control_usuario,
                control_fecha=utc(fila.control_en),
                control_observaciones=fila.control_observaciones,
                controles=[
                    RegistroControlTecnico(
                        resultado=control.resultado,
                        usuario_id=control.usuario,
                        fecha=utc(control.registrado_en),
                        observaciones=control.observaciones,
                        ejecucion_id=control.ejecucion,
                    )
                    for control in hijas["controles"].get(fila.id, [])
                ],
                cancelacion=cancelacion,
                solicitud_desistimiento=(
                    None
                    if fila.desistimiento_solicitado_en is None
                    else SolicitudDesistimiento(
                        usuario_id=fila.desistimiento_solicitado_por,
                        fecha=utc(fila.desistimiento_solicitado_en),
                        motivo=fila.desistimiento_motivo,
                        canal=fila.desistimiento_canal,
                    )
                ),
                observaciones=fila.observaciones,
                detalle_origen_id=fila.detalle_origen,
                definiciones_anteriores=anteriores,
                autorizaciones=[
                    RegistroAutorizacionCliente(
                        version_definicion=numero_de[decision.numero].numero,
                        resultado=decision.resultado,
                        usuario_id=decision.usuario,
                        fecha=utc(decision.registrada_en),
                        canal=decision.canal,
                        observaciones=decision.observaciones,
                    )
                    for decision in hijas["decisiones"].get(fila.id, [])
                ],
            )
        )
        versiones_por_detalle[fila.codigo] = [v.id for v in versiones]
        ids[fila.codigo] = fila.id
    return detalles, versiones_por_detalle, ids


def _toma(fila: Any) -> TomaOrden:
    return TomaOrden(
        id=fila.codigo,
        usuario_id=fila.usuario,
        estacion_id=fila.estacion,
        estado=fila.estado,
        inicio=utc(fila.inicio),
        fin=utc(fila.fin),
        liberada_por=fila.liberada_por,
        motivo_liberacion=fila.motivo_liberacion,
    )


def _ejecucion(fila: Any, insumos: list[Any]) -> EjecucionReparacion:
    return EjecucionReparacion(
        id=fila.codigo,
        reparacion_detail_id=fila.detalle,
        toma_orden_id=fila.toma,
        usuario_id=fila.usuario,
        estado=fila.estado,
        inicio=utc(fila.inicio),
        fin=utc(fila.fin),
        insumos_utilizados=[
            InsumoUtilizado(
                insumo_id=insumo.insumo,
                cantidad=decimal_sin_ceros(insumo.cantidad_utilizada),
            )
            for insumo in insumos
        ],
        observaciones=fila.observaciones,
        motivo_interrupcion=fila.motivo_interrupcion,
        motivo_redefinicion=fila.motivo_redefinicion,
        estado_trabajo=fila.estado_trabajo,
        reversible=fila.reversible,
    )


def _paso(fila: Any) -> HistorialWorkflow:
    return HistorialWorkflow(
        tipo_referencia=fila.tipo_referencia,
        referencia_id=fila.referencia_id,
        accion=fila.accion,
        fecha=utc(fila.ocurrido_en),
        usuario_id=fila.usuario,
        reparacion_detail_id=fila.detalle,
        ejecucion_id=fila.ejecucion,
        pago_id=fila.pago,
        observacion=fila.observacion,
    )
