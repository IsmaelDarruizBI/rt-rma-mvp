"""Ingreso inicial de CLIENTE_EXTERNO en un solo paso (MVP v2).

    generar_comprobante_ingreso   confirmacion fisica -> 050/060 -> 211 ->
                                  129 -> 046/047 (autorizacion inicial) ->
                                  080 -> 090 -> 140 | 100 -> comprobante de
                                  ingreso -> 150 (4) -> 170

Recepcion crea la Orden, carga los trabajos y genera el comprobante de
ingreso y autorizacion: este comando hace el resto. No es un circuito
nuevo: compone los mismos services de siempre, asi que el historial
conserva cada evento (confirmacion de custodia, PROC-REP-050/060, la
decision del cliente por Detalle, la factibilidad, la habilitacion y la
entrada a la cola).

Es una sola operacion: todo ocurre en memoria y se guarda una vez al
final. Si algo falla, nada queda a medias. Un reintento (doble clic) con
el comprobante ya emitido devuelve la Orden tal como esta.

Las autorizaciones posteriores (trabajos nuevos o una redefinicion)
siguen el circuito explicito de la decision del cliente.
"""

from app.domain.models import (
    CanalComunicacion,
    OrdenReparacion,
    ResultadoAutorizacion,
    RolUsuario,
    TipoDocumento,
    Usuario,
)
from app.services import (
    DecisionDetalle,
    PrecondicionInvalidaError,
    confirmar_recepcion_fisica,
    contenido_comprobante_ingreso,
    detalles_pendientes_de_autorizacion,
    emitir_comprobante_ingreso,
    es_ingreso_inicial,
    exigir_definicion_finalizable,
    faltantes_para_ingreso,
    generar_comprobante_recepcion,
    ultimo_documento,
    validar_actor,
)

from .autorizacion_cliente import aplicar_decision_cliente
from .cola import encolar_si_ingreso_automatico
from .concurrencia import seccion_critica_inventario
from .contexto import ApplicationContext
from .documentos import contexto_documentos
from .ingreso import _validar_y_habilitar
from .modificacion import orden_para_modificar

OBSERVACION_AUTORIZACION_INICIAL = "Autorizacion inicial en el ingreso"


def _exigir_ingreso_inicial(orden: OrdenReparacion, usuario: Usuario) -> None:
    validar_actor(usuario, RolUsuario.RECEPCION)
    if not es_ingreso_inicial(orden):
        raise PrecondicionInvalidaError(
            "El comprobante de ingreso y autorizacion es del ingreso inicial "
            "de Cliente Externo: esta Orden ya no esta en ese paso."
        )
    faltan = faltantes_para_ingreso(orden)
    if faltan:
        raise PrecondicionInvalidaError(
            "Para generar el comprobante falta: " + "; ".join(faltan) + "."
        )


def generar_comprobante_ingreso(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    canal: CanalComunicacion = CanalComunicacion.PRESENCIAL,
) -> OrdenReparacion:
    """Confirma, finaliza, autoriza, emite el comprobante y encola.

    ``canal`` es por donde el cliente autorizo los trabajos (en el
    mostrador, presencial). Autoriza todos los trabajos cargados: los que
    el cliente no quiera se quitan antes de generar el comprobante. No
    pide el check-in: se registra antes de la entrega (UAT-009).
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with (
        seccion_critica_inventario(),
        orden_para_modificar(contexto, orden_id) as orden,
    ):
        if ultimo_documento(orden, TipoDocumento.COMPROBANTE_INGRESO):
            return orden
        _exigir_ingreso_inicial(orden, usuario)

        if not orden.recepcion.confirmada:
            orden = confirmar_recepcion_fisica(
                orden, usuario=usuario, fecha=fecha
            )
        exigir_definicion_finalizable(orden, usuario=usuario)
        if not any(
            paso.process_id == "PROC-REP-050" for paso in orden.historial
        ):
            orden = generar_comprobante_recepcion(orden, fecha=fecha)
        orden = _validar_y_habilitar(contexto, orden, fecha=fecha)

        decisiones = [
            DecisionDetalle(
                detalle_id=detalle.id,
                version_definicion=detalle.version_definicion,
                resultado=ResultadoAutorizacion.AUTORIZADO,
            )
            for detalle in orden.reparaciones_detail
            if detalle.id in detalles_pendientes_de_autorizacion(orden)
        ]
        orden = aplicar_decision_cliente(
            contexto,
            orden,
            usuario=usuario,
            canal=canal,
            decisiones=decisiones,
            observaciones=OBSERVACION_AUTORIZACION_INICIAL,
            fecha=fecha,
        )
        orden, _, _ = emitir_comprobante_ingreso(
            orden,
            usuario=usuario,
            contenido=contenido_comprobante_ingreso(
                orden, contexto_documentos(contexto, orden)
            ),
            fecha=fecha,
        )
        orden = encolar_si_ingreso_automatico(
            orden, fecha=fecha, usuario_id=usuario.id
        )
        contexto.ordenes.guardar(orden)
    return orden
