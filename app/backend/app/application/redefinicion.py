"""Tramo de revision posterior de un Detalle (EXC-REP-004).

    revisar_detalle     PROC-REP-126                     (ACT-TECH)
    redefinir_detalle   PROC-REP-127 -> 080 -> 090 [-> 140 | -> 100]
                                                         (ACT-RECEP)

PROC-REP-125 no es un comando: lo compone ``evaluar_situacion_orden``
cuando 211 da REQUIERE_REVISION. Entre 126 y 127 hay una frontera de
actor (Tecnico -> Recepcion), por eso son dos comandos. 127 encadena la
factibilidad en la misma operacion, como ``definir_reparacion`` y
``revalidar_recursos``: la Orden se guarda una sola vez.
"""

from app.domain.models import OrdenReparacion
from app.services import redefinir_detalle as redefinir_detalle_servicio
from app.services import revisar_detalle_pendiente

from .concurrencia import seccion_critica_inventario
from .contexto import ApplicationContext
from .ingreso import _validar_y_habilitar


def revisar_detalle(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    detalle_id: str,
    usuario_id: str,
    resultado: str,
) -> OrdenReparacion:
    """El tecnico revisa UN Detalle pendiente y registra el resultado."""
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    orden = contexto.ordenes.obtener(orden_id)
    orden = revisar_detalle_pendiente(
        orden,
        detalle_id=detalle_id,
        usuario=usuario,
        resultado=resultado,
        fecha=fecha,
    )

    contexto.ordenes.guardar(orden)
    return orden


def redefinir_detalle(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    detalle_id: str,
    usuario_id: str,
    tipo_reparacion_id: str,
) -> OrdenReparacion:
    """Recepcion redefine el Detalle y se revalida la factibilidad.

    127 -> 080 -> 090: con algun Detalle trabajable 090 "Si" -> 140
    (HABILITADA); si no, 090 "Ninguno" -> 100, desde donde siguen
    EXC-REP-001/002. Corre en la seccion critica de inventario porque la
    factibilidad lee el stock y las reservas de las demas Ordenes.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    tipo = contexto.catalogos.obtener_tipo_reparacion(tipo_reparacion_id)
    fecha = contexto.ahora()

    with seccion_critica_inventario():
        orden = contexto.ordenes.obtener(orden_id)
        orden = redefinir_detalle_servicio(
            orden,
            detalle_id=detalle_id,
            tipo_reparacion=tipo,
            usuario=usuario,
            fecha=fecha,
        )
        orden = _validar_y_habilitar(contexto, orden, fecha=fecha)

        contexto.ordenes.guardar(orden)

    return orden
