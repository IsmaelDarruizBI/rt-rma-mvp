"""Evaluacion tecnica de un Detalle (PROC-REP-182 -> 183 -> 184) y
reparaciones adicionales detectadas por el tecnico (PROC-REP-128).

Un comando del tecnico titular de la toma. Despues del resultado:

- CONFIRMADO: el Detalle queda listo para iniciarse (181 -> 182 -> 174);
- DESCARTADO: 300 ya cancelo el Detalle; 211 recalcula la Orden;
- REQUIERE_REDEFINICION: 127 ya registro la definicion nueva. Con
  autorizacion del cliente (CLIENTE_EXTERNO) 211 deja la solicitud
  pendiente para Recepcion (129, VAR-REP-019); en los demas Origenes la
  factibilidad del Detalle redefinido (080) y despues 211.

Las reparaciones adicionales del mismo acto (184 -> 128) nacen pendientes
de autorizacion en CLIENTE_EXTERNO -las resuelve Recepcion por su carril,
sin espera del tecnico (BR-REP-037)- y pasan por la factibilidad (080) en
los demas Origenes.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.domain.models import (
    OrdenReparacion,
    ResultadoEvaluacionTecnica,
)
from app.services import (
    cargar_reservas_externas,
    evaluar_situacion_orden,
    validar_factibilidad_detalles,
)
from app.services.autorizacion_cliente import requiere_autorizacion_cliente
from app.services.evaluacion_tecnica import ReparacionAdicional
from app.services.evaluacion_tecnica import evaluar_detalle as evaluar_servicio
from app.services.reparaciones import agregar_detalle_adicional
from app.services.tomas import hay_ejecucion_activa

from .contexto import ApplicationContext
from .identificadores import siguiente_detalle_id, siguientes_detalle_ids
from .modificacion import orden_para_modificar


@dataclass(frozen=True)
class PedidoAdicional:
    """Lo que el tecnico carga de cada reparacion adicional."""

    tipo_reparacion_id: str
    observaciones: str | None = None
    detalle_origen_id: str | None = None


def _factibilidad(
    contexto: ApplicationContext,
    orden: OrdenReparacion,
    detalle_ids: Collection[str],
    fecha: datetime,
) -> OrdenReparacion:
    """080 solo de esos Detalles, sobre una Orden ya habilitada."""
    orden, _ = validar_factibilidad_detalles(
        orden,
        insumos=contexto.catalogos.listar_insumos(),
        insumos_previstos=contexto.catalogos.listar_tipo_reparacion_insumos(),
        fecha=fecha,
        reservas_externas=cargar_reservas_externas(orden.id, contexto.ordenes),
        detalle_ids=set(detalle_ids),
        registrar_faltantes=False,
    )
    return orden


def evaluar_detalle(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    detalle_id: str,
    usuario_id: str,
    resultado: ResultadoEvaluacionTecnica,
    observaciones: str | None,
    tipo_reparacion_id: str | None = None,
    adicionales: Sequence[PedidoAdicional] = (),
) -> OrdenReparacion:
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    tipo = (
        contexto.catalogos.obtener_tipo_reparacion(tipo_reparacion_id)
        if tipo_reparacion_id
        else None
    )
    tipos_adicionales = [
        contexto.catalogos.obtener_tipo_reparacion(a.tipo_reparacion_id)
        for a in adicionales
    ]
    fecha = contexto.ahora()

    with (
        contexto.transaccion(),
        orden_para_modificar(contexto, orden_id) as orden,
    ):
        ids_nuevos = siguientes_detalle_ids(orden, len(adicionales))
        orden = evaluar_servicio(
            orden,
            detalle_id=detalle_id,
            resultado=resultado,
            observaciones=observaciones,
            usuario=usuario,
            fecha=fecha,
            tipo_reparacion=tipo,
            adicionales=[
                ReparacionAdicional(
                    detalle_id=nuevo_id,
                    tipo_reparacion=tipo_adicional,
                    observaciones=pedido.observaciones,
                    detalle_origen_id=pedido.detalle_origen_id,
                )
                for nuevo_id, tipo_adicional, pedido in zip(
                    ids_nuevos, tipos_adicionales, adicionales, strict=True
                )
            ],
        )
        con_autorizacion = requiere_autorizacion_cliente(orden)
        por_factibilidad = [] if con_autorizacion else list(ids_nuevos)
        if (
            resultado is ResultadoEvaluacionTecnica.REQUIERE_REDEFINICION
            and not con_autorizacion
        ):
            por_factibilidad.insert(0, detalle_id)
        if por_factibilidad:
            orden = _factibilidad(contexto, orden, por_factibilidad, fecha)
        if resultado is not ResultadoEvaluacionTecnica.CONFIRMADO or (
            por_factibilidad
        ):
            orden, _ = evaluar_situacion_orden(orden, fecha=fecha)

        contexto.ordenes.guardar(orden)

    return orden


def agregar_trabajo_adicional(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    tipo_reparacion_id: str,
    observaciones: str | None = None,
    detalle_origen_id: str | None = None,
) -> OrdenReparacion:
    """PROC-REP-128 durante la participacion del tecnico (desde 190).

    En CLIENTE_EXTERNO el Detalle queda pendiente de autorizacion y la
    Ejecucion vigente continua; en los demas Origenes pasa por la
    factibilidad (080) y, sin Ejecucion activa, el resolver (211) decide.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    tipo = contexto.catalogos.obtener_tipo_reparacion(tipo_reparacion_id)
    fecha = contexto.ahora()

    with (
        contexto.transaccion(),
        orden_para_modificar(contexto, orden_id) as orden,
    ):
        nuevo_id = siguiente_detalle_id(orden)
        orden = agregar_detalle_adicional(
            orden,
            detalle_id=nuevo_id,
            tipo_reparacion=tipo,
            usuario=usuario,
            fecha=fecha,
            observaciones=observaciones,
            detalle_origen_id=detalle_origen_id,
        )
        if not requiere_autorizacion_cliente(orden):
            orden = _factibilidad(contexto, orden, [nuevo_id], fecha)
            if not hay_ejecucion_activa(orden):
                orden, _ = evaluar_situacion_orden(orden, fecha=fecha)
        contexto.ordenes.guardar(orden)

    return orden
