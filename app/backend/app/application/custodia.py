"""Recepcion fisica del equipo: datos del ingreso y custodia.

    registrar_recepcion            registra o corrige los datos del ingreso
                                   (antes de confirmar; regulariza una Orden
                                   anterior)
    confirmar_recepcion            el equipo quedo en el local (custodia)
    registrar_no_recepcion         el equipo nunca ingreso (Orden cancelada)
    agregar_observacion_recepcion  observacion complementaria
    registrar_imei_real            el IMEI real de un equipo que ingreso sin
                                   el, hasta la entrega (DEC-AJ-06)

Acciones transversales (``ACC-REP-023/024/025/027``): no mueven
``current_process`` por si mismas. Las reglas viven en
``services.custodia``.
"""

from collections.abc import Collection

from app.domain.identidad import candidatos, normalizar
from app.domain.models import DatosRecepcion, Equipo, OrdenReparacion
from app.services import (
    agregar_nota_recepcion,
    cerrar_cancelada_si_corresponde,
    confirmar_recepcion_fisica,
    exigir_fuera_del_ingreso_inicial,
    registrar_datos_recepcion,
    registrar_equipo_no_recibido,
)
from app.services import registrar_imei_real as registrar_imei_real_servicio

from .catalogo_equipos import equipo_desde_catalogo
from .contexto import ApplicationContext
from .modificacion import orden_para_modificar
from .piezas import conciliar
from .precio_trabajo import redeterminar_precios


def registrar_recepcion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    datos: DatosRecepcion,
    equipo: Equipo | None = None,
    motivo: str | None = None,
    conservar: Collection[str] = (),
) -> OrdenReparacion:
    """Recepcion registra o corrige los datos del ingreso.

    El check-in no es parte del ingreso: se registra antes de la entrega
    (``cierre.registrar_checkin``) y la correccion conserva el que haya.
    ``equipo`` puede cambiar a otro producto del catalogo, a carga manual o
    mantener el producto que tenia (sin volver a consultarlo).

    ``conservar``: datos de ``DatosRecepcion`` que el pedido no trae y que
    quedan como estaban (los agregados despues, como el trabajo solicitado
    o la verificacion de funcionalidades: un cliente anterior que no los
    conoce no los borra).

    DEC-AJ-12 (D-12.6): si cambia el modelo tecnico del equipo, el precio
    de los trabajos que dependen del modelo y todavia esperan la
    autorizacion del cliente se vuelve a determinar; los demas lo
    conservan con un aviso.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        if conservar and orden.recepcion is not None:
            datos = datos.model_copy(
                update={
                    campo: getattr(orden.recepcion.datos, campo)
                    for campo in conservar
                }
            )
        if equipo is not None:
            equipo = equipo_desde_catalogo(
                contexto, equipo, actual=orden.equipo
            )
        modelo_anterior = orden.equipo.modelo_tecnico_id
        orden = registrar_datos_recepcion(
            orden,
            usuario=usuario,
            fecha=fecha,
            datos=datos,
            equipo=equipo,
            motivo=motivo,
        )
        # DEC-AJ-12 (D-12.6): otro modelo, otro precio antes de autorizar.
        orden = redeterminar_precios(
            contexto,
            orden,
            modelo_anterior=modelo_anterior,
            usuario=usuario,
            fecha=fecha,
        )
        # DEC-AJ-14: las piezas elegidas que no sirven para el modelo nuevo
        # se anulan (o se reemplazan por la unica compatible); las
        # reservadas o consumidas no cambian (se sustituyen a mano).
        if orden.equipo.modelo_tecnico_id != modelo_anterior:
            orden = conciliar(
                contexto, orden, usuario_id=usuario.id, fecha=fecha
            )
        contexto.ordenes.guardar(orden)
    return orden


def confirmar_recepcion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    observaciones: str | None = None,
) -> OrdenReparacion:
    """Recepcion confirma que el equipo quedo fisicamente en el local.

    En el ingreso inicial de CLIENTE_EXTERNO no: la confirmacion va dentro
    del comprobante de ingreso y autorizacion.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        exigir_fuera_del_ingreso_inicial(orden, "confirmar la recepcion")
        orden = confirmar_recepcion_fisica(
            orden, usuario=usuario, fecha=fecha, observaciones=observaciones
        )
        contexto.ordenes.guardar(orden)
    return orden


def registrar_no_recepcion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    motivo: str,
) -> OrdenReparacion:
    """Registra "Equipo no recibido" en una Orden cancelada.

    Sin equipo que devolver, la Orden pasa por la verificacion financiera
    (PROC-REP-268): cierra, o espera la devolucion del saldo a favor.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = registrar_equipo_no_recibido(
            orden, usuario=usuario, fecha=fecha, motivo=motivo
        )
        orden = cerrar_cancelada_si_corresponde(orden, fecha=fecha)
        contexto.ordenes.guardar(orden)
    return orden


def agregar_observacion_recepcion(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    texto: str,
    interna: bool = False,
) -> OrdenReparacion:
    """Agrega una observacion complementaria del ingreso.

    ``interna``: solo para el personal; nunca sale en un documento.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = agregar_nota_recepcion(
            orden, usuario=usuario, fecha=fecha, texto=texto, interna=interna
        )
        contexto.ordenes.guardar(orden)
    return orden


def registrar_imei_real(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    imei: str,
    motivo: str,
    confirmado: bool = False,
) -> OrdenReparacion:
    """DEC-AJ-06: registra el IMEI real de un equipo que ingreso sin el,
    tambien con la custodia confirmada y hasta la entrega.

    Busca dentro de la transaccion los otros Equipos con ese IMEI
    (DEC-MI-11): nunca los vincula; sin ``confirmado`` avisa y no registra
    nada. El IMEI viaja en el cuerpo del pedido, nunca en la URL (P1-18).
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()

    with orden_para_modificar(contexto, orden_id) as orden:
        encontrados = []
        if normalizar(imei):
            _, encontrados = candidatos(
                contexto.ordenes.listar_por_identificacion_equipo(
                    imei=imei, numero_serie=None
                ),
                imei=imei,
                numero_serie=None,
            )
        coincidencias = [
            candidato.equipo_id
            for candidato in encontrados
            if candidato.equipo_id != orden.equipo.id
        ]
        orden = registrar_imei_real_servicio(
            orden,
            usuario=usuario,
            fecha=fecha,
            imei=imei,
            motivo=motivo,
            coincidencias=coincidencias,
            confirmado=confirmado,
        )
        contexto.ordenes.guardar(orden)
    return orden
