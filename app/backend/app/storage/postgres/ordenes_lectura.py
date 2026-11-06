"""Lectura del agregado Orden de Reparacion desde PostgreSQL (E4, A1).

Carga una o varias Ordenes con una consulta por tabla, filtrando por la
lista de Ordenes (``= ANY``): ``listar()`` no hace una consulta por
Orden. Cada lista sale con ``ORDER BY`` explicito (posicion, secuencia o
codigo), y cada fecha en UTC, como las del dominio.

Ademas del dominio devuelve la ``Instantanea``: los uuid de cada fila y
la version persistida, que ``guardar`` usa para comparar lo que cambio
(DA-1) y para el control de version (DA-2).

Partes del agregado que todavia no tienen mapeo (pagos, descuentos y
movimientos de insumo: slices A3, A6 y A7) se leen vacias; ``guardar`` las
rechaza si llegan con datos.

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
    HistorialWorkflow,
    InsumoUtilizado,
    OrdenReparacion,
)
from app.domain.models.documentos import Documento, DocumentoEmitido
from app.domain.models.equipos import EntregaEquipo
from app.domain.models.fotos import FotoOrden
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

from .consultas import LECTURA, consulta
from .ejecutor import LectorSql
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
_CODIGOS = consulta(
    "ordenes.codigos",
    'SELECT codigo FROM rma.orden ORDER BY codigo COLLATE "C"',
    modo=LECTURA,
)
_ORIGEN = consulta(
    "ordenes.detalles_origen",
    """
    SELECT x.orden_id, d.codigo
    FROM rma.orden_detalle_origen x
    JOIN rma.detalle d ON d.id = x.detalle_id
    WHERE x.orden_id = ANY(%(ids)s)
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
    WHERE r.orden_id = ANY(%(ids)s)
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
           ux.codigo AS cancelado_por, d.cancelado_en
    FROM rma.detalle d
    LEFT JOIN rma.usuario uc ON uc.id = d.control_usuario_id
    LEFT JOIN rma.usuario ux ON ux.id = d.cancelado_por
    LEFT JOIN rma.detalle od ON od.id = d.detalle_origen_id
    WHERE d.orden_id = ANY(%(ids)s)
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
    WHERE d.orden_id = ANY(%(ids)s)
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
    WHERE d.orden_id = ANY(%(ids)s)
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
    WHERE d.orden_id = ANY(%(ids)s)
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
    WHERE d.orden_id = ANY(%(ids)s)
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
    WHERE t.orden_id = ANY(%(ids)s)
    ORDER BY t.orden_id, t.posicion, t.inicio, t.codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_EJECUCIONES = consulta(
    "ordenes.ejecuciones",
    """
    SELECT x.orden_id, x.id, x.codigo, d.codigo AS detalle,
           t.codigo AS toma, u.codigo AS usuario, x.estado, x.inicio, x.fin,
           x.observaciones, x.motivo_interrupcion, x.motivo_redefinicion
    FROM rma.ejecucion x
    JOIN rma.detalle d ON d.id = x.detalle_id
    JOIN rma.toma t ON t.id = x.toma_id
    JOIN rma.usuario u ON u.id = x.usuario_id
    WHERE x.orden_id = ANY(%(ids)s)
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
    WHERE x.orden_id = ANY(%(ids)s)
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
    WHERE v.orden_id = ANY(%(ids)s)
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
    WHERE n.orden_id = ANY(%(ids)s)
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
    WHERE c.orden_id = ANY(%(ids)s)
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
    WHERE f.orden_id = ANY(%(ids)s)
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
    WHERE d.orden_id = ANY(%(ids)s)
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
    WHERE s.orden_id = ANY(%(ids)s)
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
    WHERE e.orden_id = ANY(%(ids)s)
      AND e.historial_referencia_id IS NOT NULL
    ORDER BY e.orden_id, e.secuencia
    """,
    modo=LECTURA,
)


def utc(valor: datetime | None) -> datetime | None:
    """La fecha en UTC, como las del dominio (``contexto.ahora``)."""
    return None if valor is None else valor.astimezone(timezone.utc)


def codigos_de_ordenes(lector: LectorSql) -> list[str]:
    """Todos los numeros de Orden, en el orden de ``listar()``."""
    return [fila.codigo for fila in lector.filas(_CODIGOS)]


def cargar_ordenes(lector: LectorSql, codigos: list[str]) -> list[Instantanea]:
    """Las Ordenes de ``codigos`` que existen, por numero ascendente."""
    if not codigos:
        return []
    raices = lector.filas(_ORDENES, {"codigos": list(codigos)})
    if not raices:
        return []
    ids = [raiz.id for raiz in raices]
    por_orden = _agrupar_hijas(lector, ids)
    return [_armar(raiz, por_orden) for raiz in raices]


def _agrupar_hijas(lector: LectorSql, ids: list[UUID]) -> dict[str, Any]:
    parametros = {"ids": ids}

    def por(columna: str, filas: list[Any]) -> dict[UUID, list[Any]]:
        grupos: dict[UUID, list[Any]] = defaultdict(list)
        for fila in filas:
            grupos[getattr(fila, columna)].append(fila)
        return grupos

    return {
        "origen": por("orden_id", lector.filas(_ORIGEN, parametros)),
        "recepcion": {
            fila.orden_id: fila
            for fila in lector.filas(_RECEPCION, parametros)
        },
        "detalles": por("orden_id", lector.filas(_DETALLES, parametros)),
        "versiones": por("detalle_id", lector.filas(_VERSIONES, parametros)),
        "decisiones": por("detalle_id", lector.filas(_DECISIONES, parametros)),
        "ajustes": por("detalle_id", lector.filas(_AJUSTES, parametros)),
        "controles": por("detalle_id", lector.filas(_CONTROLES, parametros)),
        "tomas": por("orden_id", lector.filas(_TOMAS, parametros)),
        "ejecuciones": por("orden_id", lector.filas(_EJECUCIONES, parametros)),
        "insumos": por(
            "ejecucion_id", lector.filas(_INSUMOS_UTILIZADOS, parametros)
        ),
        "historial": por("orden_id", lector.filas(_HISTORIAL, parametros)),
        "versiones_recepcion": por(
            "orden_id", lector.filas(_VERSIONES_RECEPCION, parametros)
        ),
        "notas": por("orden_id", lector.filas(_NOTAS_RECEPCION, parametros)),
        "checkins": por("orden_id", lector.filas(_CHECKINS, parametros)),
        "fotos": por("orden_id", lector.filas(_FOTOS, parametros)),
        "documentos": por("orden_id", lector.filas(_DOCUMENTOS, parametros)),
        "salidas": {
            fila.orden_id: fila for fila in lector.filas(_SALIDAS, parametros)
        },
    }


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
