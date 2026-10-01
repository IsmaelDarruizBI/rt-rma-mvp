"""Tramo del taller: tomar la Orden, iniciar un Detalle y completarlo.

Tres comandos, uno por accion humana de ACT-TECH:

    tomar_orden_en_estacion   PROC-REP-172 -> 180
    iniciar_detalle           PROC-REP-181 -> 174 -> 185
    completar_ejecucion       PROC-REP-190 -> 200 -> 210 -> 211

``iniciar_detalle`` y ``completar_ejecucion`` corren dentro de la
seccion critica de inventario: el primero reserva stock, el segundo lo
consume y reescribe el catalogo.
"""

from collections.abc import Callable, Sequence
from datetime import datetime

from app.domain.models import (
    EjecucionReparacion,
    InsumoUtilizado,
    OrdenReparacion,
)
from app.services import (
    EntidadNoEncontradaError,
    PrecondicionInvalidaError,
    ResultadoEvaluacionOrden,
    aplicar_movimientos_inventario,
    cargar_reservas_externas,
    ejecutar_detalle,
    evaluar_situacion_orden,
    registrar_ejecucion_completada,
    registrar_ejecucion_interrumpida,
    reservar_insumos_e_iniciar_ejecucion,
    seleccionar_detalle,
    tomar_orden,
    validar_compatibilidad_detalle,
    validar_estacion_trabajo,
)
from app.services import (
    liberar_orden as liberar_orden_servicio,
)

from .concurrencia import seccion_critica_inventario
from .contexto import ApplicationContext


def _motivo_del_ultimo_paso(orden: OrdenReparacion) -> str:
    """Observacion del paso que acaba de registrarse.

    Los nodos de validacion (PROC-REP-172 / PROC-REP-174) no lanzan:
    devuelven un booleano y dejan el motivo en el historial. Cuando el
    resultado es negativo el comando se aborta -esa version de la Orden
    nunca se guarda- y el motivo se recupera de aqui para poder
    explicarle al usuario que paso.
    """
    if not orden.historial:
        return "La validacion del proceso no se cumplio."
    return orden.historial[-1].observacion or (
        "La validacion del proceso no se cumplio."
    )


def tomar_orden_en_estacion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    estacion_id: str,
) -> OrdenReparacion:
    """El tecnico toma la Orden desde una Estacion (172 -> 180).

    PROC-REP-172 no lanza: devuelve valido/invalido. Si da invalido, el
    comando entero se descarta -no se persiste la Orden con el intento
    fallido- y se responde el motivo funcional como conflicto.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    orden = contexto.ordenes.obtener(orden_id)

    orden, valida = validar_estacion_trabajo(
        orden,
        usuario=usuario,
        estacion_id=estacion_id,
        estaciones=contexto.catalogos.listar_estaciones(),
        compatibilidades=(
            contexto.catalogos.listar_tipo_reparacion_estaciones()
        ),
        fecha=fecha,
    )
    if not valida:
        raise PrecondicionInvalidaError(
            f"No se puede tomar la Orden (PROC-REP-172): "
            f"{_motivo_del_ultimo_paso(orden)}."
        )

    orden = tomar_orden(
        orden, usuario=usuario, estacion_id=estacion_id, fecha=fecha
    )

    contexto.ordenes.guardar(orden)
    return orden


def iniciar_detalle(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    detalle_id: str,
    usuario_id: str,
) -> OrdenReparacion:
    """El tecnico inicia el Detalle y se reserva el stock (181/174/185).

    Es la unica reserva real del proceso (BR-REP-006, PROC-REP-185).
    Toda la secuencia -cargar la Orden, leer el stock fisico del
    catalogo, sumar las reservas activas de las demas Ordenes, revalidar
    la disponibilidad, generar las RESERVA y guardar- ocurre dentro de
    ``seccion_critica_inventario``, porque entre la lectura y la
    escritura no puede colarse otro tecnico pidiendo la misma unidad.

    La disponibilidad se vuelve a calcular aqui aunque PROC-REP-080 ya
    la haya consultado: entre una cosa y la otra pudieron pasar dias.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with seccion_critica_inventario():
        orden = contexto.ordenes.obtener(orden_id)

        orden = seleccionar_detalle(
            orden, detalle_id=detalle_id, usuario=usuario, fecha=fecha
        )
        orden, compatible = validar_compatibilidad_detalle(
            orden,
            detalle_id=detalle_id,
            compatibilidades=(
                contexto.catalogos.listar_tipo_reparacion_estaciones()
            ),
            fecha=fecha,
        )
        if not compatible:
            raise PrecondicionInvalidaError(
                f"La Estacion de la toma activa no esta habilitada para "
                f"el Detalle {detalle_id} (PROC-REP-174). El MVP no "
                "implementa el override de incompatibilidad."
            )

        orden = reservar_insumos_e_iniciar_ejecucion(
            orden,
            detalle_id=detalle_id,
            usuario=usuario,
            insumos=contexto.catalogos.listar_insumos(),
            insumos_previstos=(
                contexto.catalogos.listar_tipo_reparacion_insumos()
            ),
            fecha=fecha,
            reservas_externas=cargar_reservas_externas(
                orden.id, contexto.ordenes
            ),
        )

        contexto.ordenes.guardar(orden)

    return orden


def liberar_orden(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
) -> OrdenReparacion:
    """El tecnico libera la Orden sin terminarla (PROC-REP-212 "No" -> 213).

    Cierra la toma activa y devuelve la Orden a EN_COLA. No requiere la
    seccion critica de inventario: no reserva ni consume stock.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    orden = contexto.ordenes.obtener(orden_id)
    orden = liberar_orden_servicio(orden, usuario=usuario, fecha=fecha)

    contexto.ordenes.guardar(orden)
    return orden


def _buscar_ejecucion(
    orden: OrdenReparacion,
    ejecucion_id: str,
) -> EjecucionReparacion:
    for ejecucion in orden.ejecuciones:
        if ejecucion.id == ejecucion_id:
            return ejecucion
    raise EntidadNoEncontradaError(
        f"La Orden {orden.id} no tiene la Ejecucion {ejecucion_id}"
    )


def completar_ejecucion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    ejecucion_id: str,
    usuario_id: str,
    insumos_utilizados: Sequence[InsumoUtilizado],
    observaciones: str | None = None,
) -> tuple[OrdenReparacion, ResultadoEvaluacionOrden]:
    """El tecnico cierra la Ejecucion (190 -> 200 -> 210 -> 211).

    PROC-REP-210 se delega en ``aplicar_movimientos_inventario``, que ya
    resuelve los dos efectos -la Orden y el stock fisico del catalogo- y
    es idempotente: si esa Ejecucion ya aplico su inventario, no vuelve
    a consumir. Esa idempotencia se conserva tal cual; este comando no
    la reimplementa.

    Corre dentro de la seccion critica porque reescribe el stock fisico
    del catalogo, que es estado global compartido.

    Solo el tecnico propietario de la Ejecucion puede completarla: lo
    valida el service, no este comando.
    """
    return _cerrar_ejecucion(
        contexto,
        registrar_resultado=registrar_ejecucion_completada,
        orden_id=orden_id,
        ejecucion_id=ejecucion_id,
        usuario_id=usuario_id,
        insumos_utilizados=insumos_utilizados,
        observaciones=observaciones,
    )


def interrumpir_ejecucion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    ejecucion_id: str,
    usuario_id: str,
    insumos_utilizados: Sequence[InsumoUtilizado],
    observaciones: str | None = None,
) -> tuple[OrdenReparacion, ResultadoEvaluacionOrden]:
    """El tecnico interrumpe la Ejecucion (190 -> 200 Interrumpido -> 210
    -> 211), VAR-REP-003.

    Paralelo a ``completar_ejecucion``: la Ejecucion queda INTERRUMPIDO y
    el Detalle vuelve a DEFINIDO; lo realmente utilizado se consume y lo
    reservado que no se uso se libera (PROC-REP-210). El resultado de
    PROC-REP-211 sale del resolver (con un Detalle trabajable,
    ABIERTA_TRABAJABLE), no se fija aqui.

    NO cierra la toma: el tecnico puede iniciar una Ejecucion nueva
    (mismo u otro Detalle) o liberar la Orden (PROC-REP-212/213).
    """
    return _cerrar_ejecucion(
        contexto,
        registrar_resultado=registrar_ejecucion_interrumpida,
        orden_id=orden_id,
        ejecucion_id=ejecucion_id,
        usuario_id=usuario_id,
        insumos_utilizados=insumos_utilizados,
        observaciones=observaciones,
    )


def _cerrar_ejecucion(
    contexto: ApplicationContext,
    *,
    registrar_resultado: Callable[..., OrdenReparacion],
    orden_id: str,
    ejecucion_id: str,
    usuario_id: str,
    insumos_utilizados: Sequence[InsumoUtilizado],
    observaciones: str | None,
) -> tuple[OrdenReparacion, ResultadoEvaluacionOrden]:
    """190 -> 200 -> 210 -> 211 para cualquier resultado de PROC-REP-200."""
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha: datetime = contexto.ahora()

    with seccion_critica_inventario():
        orden = contexto.ordenes.obtener(orden_id)
        ejecucion = _buscar_ejecucion(orden, ejecucion_id)

        orden = ejecutar_detalle(
            orden,
            detalle_id=ejecucion.reparacion_detail_id,
            usuario=usuario,
            fecha=fecha,
        )
        orden = registrar_resultado(
            orden,
            ejecucion_id=ejecucion_id,
            insumos_utilizados=insumos_utilizados,
            usuario=usuario,
            fecha=fecha,
            observaciones=observaciones,
        )
        orden = aplicar_movimientos_inventario(
            orden,
            ejecucion_id=ejecucion_id,
            fecha=fecha,
            ordenes_repo=contexto.ordenes,
            catalogos_repo=contexto.catalogos,
        )
        orden, resultado = evaluar_situacion_orden(orden, fecha=fecha)

        contexto.ordenes.guardar(orden)

    return orden, resultado
