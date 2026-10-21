"""Recepcion fisica del equipo, custodia y su salida del local.

Reglas centrales:

- Comprobante != custodia. Emitir el comprobante de recepcion no prueba
  que el equipo este en el local: la custodia se confirma explicitamente
  (``confirmar_recepcion_fisica``), con usuario y fecha.
- Los datos del ingreso se corrigen solo antes de confirmar; cada
  correccion conserva la version anterior. Despues se agregan
  observaciones complementarias, nunca se reescribe lo confirmado.
- La custodia se decide de forma explicita, una sola vez: se confirma la
  recepcion, o se registra "Equipo no recibido" con motivo
  (``registrar_equipo_no_recibido``). Ninguna de las dos se deduce del
  comprobante ni de la falta de confirmacion.
- El equipo se entrega o se devuelve solo si esta en custodia. Una Orden
  anterior a este registro no tiene custodia presumida: se regulariza
  (datos de ingreso + confirmacion con motivo) antes de entregarla.
- RT_INTERNO conserva su circuito (``PoliticaOrigen``): el equipo llega
  desde Gestion RT y vuelve a ella sin confirmacion.

Las acciones de recepcion son transversales: dejan traza en el historial
(``ACC-REP-023/024/025/027``, IDs del MVP) y no mueven
``current_process``.
"""

from datetime import datetime

from app.domain.models import (
    ConfirmacionRecepcion,
    DatosRecepcion,
    EntregaEquipo,
    Equipo,
    EstadoCustodia,
    EstadoWorkflow,
    NoRecepcion,
    NotaRecepcion,
    OrdenReparacion,
    RecepcionEquipo,
    RegistroRecepcion,
    RolUsuario,
    TipoEntrega,
    Usuario,
    VersionRecepcion,
)
from app.domain.politicas import politica_de

from .autorizacion import validar_alguno_de
from .exceptions import PrecondicionInvalidaError
from .revisiones import finalizada_sin_reparacion
from .workflow import registrar_accion_funcional

ACCION_DATOS_RECEPCION = "ACC-REP-023"
ACCION_CONFIRMAR_RECEPCION = "ACC-REP-024"
ACCION_NOTA_RECEPCION = "ACC-REP-025"
ACCION_EQUIPO_NO_RECIBIDO = "ACC-REP-027"

# Nodos del historial que solo ocurren con el equipo en la mano: revision
# tecnica (065, 126), control final (220) y salida fisica (270).
_NODOS_CON_EQUIPO = (
    "PROC-REP-065",
    "PROC-REP-126",
    "PROC-REP-220",
    "PROC-REP-270",
)

# Quien registra el ingreso es Recepcion; Administracion puede corregirlo o
# regularizarlo. Pendiente de validacion del negocio.
ROLES_RECEPCION_EQUIPO = (
    RolUsuario.RECEPCION,
    RolUsuario.ADMINISTRADOR,
)


# --- Estado de custodia ------------------------------------------------------


def estado_custodia(orden: OrdenReparacion) -> EstadoCustodia:
    """Donde esta el equipo, derivado de la Orden (nunca persistido).

    No mira el comprobante de recepcion ni deduce nada de que la Orden este
    cerrada: solo la decision registrada sobre la recepcion (confirmada o
    "no recibido") y la salida del equipo. Sin decision, queda pendiente.
    """
    if orden.estado_workflow is EstadoWorkflow.ENTREGADA:
        return EstadoCustodia.ENTREGADO
    if orden.devolucion is not None:
        return EstadoCustodia.DEVUELTO
    if not politica_de(orden.origen).requiere_confirmacion_recepcion:
        # RT_INTERNO: llega por el circuito de Gestion RT (PROC-REP-020) y,
        # al terminar, vuelve a ella.
        if orden.esta_cerrada:
            return EstadoCustodia.DEVUELTO
        return EstadoCustodia.EN_CUSTODIA
    if orden.recepcion is not None and orden.recepcion.confirmada:
        return EstadoCustodia.EN_CUSTODIA
    if orden.recepcion is not None and orden.recepcion.no_recibido:
        return EstadoCustodia.NO_RECIBIDO
    if orden.recepcion is None:
        return EstadoCustodia.SIN_REGISTRO
    return EstadoCustodia.PENDIENTE_CONFIRMACION


def equipo_bajo_custodia(orden: OrdenReparacion) -> bool:
    """El equipo esta en el local y hay que entregarlo o devolverlo."""
    return estado_custodia(orden) is EstadoCustodia.EN_CUSTODIA


MENSAJE_SIN_CUSTODIA_PARA_EJECUTAR = (
    "Debe confirmarse la recepcion fisica del equipo antes de iniciar la "
    "reparacion"
)


def motivo_bloqueo_ejecucion(orden: OrdenReparacion) -> str | None:
    """Por que no puede empezar una Ejecucion fisica, o ``None``.

    Trabajar sobre el equipo exige tenerlo: custodia EN_CUSTODIA cuando la
    politica del Origen confirma la recepcion (CLIENTE_EXTERNO, garantia
    RMA). RT_INTERNO conserva su circuito: el equipo llega por Gestion RT.
    Nunca se presume la custodia de una Orden anterior.
    """
    estado = estado_custodia(orden)
    if estado is EstadoCustodia.EN_CUSTODIA:
        return None
    if estado is EstadoCustodia.NO_RECIBIDO:
        return (
            "Se registro que el equipo no se recibio: no se puede iniciar "
            "la reparacion"
        )
    if estado is EstadoCustodia.SIN_REGISTRO:
        return (
            f"{MENSAJE_SIN_CUSTODIA_PARA_EJECUTAR} (Orden anterior al "
            "registro de recepcion: regularizala)"
        )
    if estado is EstadoCustodia.PENDIENTE_CONFIRMACION:
        return MENSAJE_SIN_CUSTODIA_PARA_EJECUTAR
    return f"El equipo no esta en el local ({estado.value})"


def exigir_custodia_para_ejecutar(orden: OrdenReparacion) -> None:
    """Rechaza el inicio de una Ejecucion sin custodia confirmada.

    Se valida antes de generar reservas, la Ejecucion o cualquier paso:
    un rechazo no deja rastro operativo.
    """
    motivo = motivo_bloqueo_ejecucion(orden)
    if motivo is not None:
        raise PrecondicionInvalidaError(f"{motivo}.")


def custodia_por_definir(orden: OrdenReparacion) -> bool:
    """Todavia no se decidio si el equipo se recibio (o es una Orden
    anterior sin registro): no se puede asumir ni que esta ni que no."""
    return estado_custodia(orden) in (
        EstadoCustodia.PENDIENTE_CONFIRMACION,
        EstadoCustodia.SIN_REGISTRO,
    )


def custodia_resuelta(orden: OrdenReparacion) -> bool:
    """El equipo ya no condiciona el cierre: salio o nunca ingreso."""
    return estado_custodia(orden) in (
        EstadoCustodia.ENTREGADO,
        EstadoCustodia.DEVUELTO,
        EstadoCustodia.NO_RECIBIDO,
    )


def evidencias_de_equipo(orden: OrdenReparacion) -> list[str]:
    """Lo que en la Orden prueba que el equipo estuvo en el local.

    Recepcion confirmada, salida registrada (entrega o devolucion), tomas,
    ejecuciones, controles y revisiones tecnicas: todo eso exige tener el
    equipo. Con alguna de estas evidencias no se puede declarar que el
    equipo nunca ingreso.
    """
    evidencias = []
    if orden.recepcion is not None and orden.recepcion.confirmada:
        evidencias.append("la recepcion fisica ya se confirmo")
    if orden.entrega is not None or orden.devolucion is not None:
        evidencias.append("ya se registro la salida fisica del equipo")
    if orden.ejecuciones:
        evidencias.append(
            "hubo ejecucion tecnica ("
            + ", ".join(ejecucion.id for ejecucion in orden.ejecuciones)
            + ")"
        )
    if orden.tomas:
        evidencias.append("un tecnico tomo la Orden")
    nodos = sorted(
        {
            paso.process_id
            for paso in orden.historial
            if paso.process_id in _NODOS_CON_EQUIPO
        }
    )
    if nodos:
        evidencias.append(
            "el historial registra trabajo sobre el equipo ("
            + ", ".join(nodos)
            + ")"
        )
    return evidencias


def exigir_equipo_en_custodia(
    orden: OrdenReparacion,
    *,
    operacion: str,
) -> None:
    """Rechaza ``operacion`` si el equipo no esta en custodia confirmada."""
    estado = estado_custodia(orden)
    if estado is EstadoCustodia.EN_CUSTODIA:
        return
    if estado is EstadoCustodia.PENDIENTE_CONFIRMACION:
        motivo = (
            "la recepcion fisica del equipo no esta confirmada: confirmala "
            f"antes de {operacion}"
        )
    elif estado is EstadoCustodia.SIN_REGISTRO:
        motivo = (
            "la Orden es anterior al registro de recepcion y no hay "
            "custodia confirmada: regulariza la recepcion (datos del "
            f"ingreso y confirmacion) antes de {operacion}"
        )
    else:
        motivo = f"el equipo no esta en custodia ({estado.value})"
    raise PrecondicionInvalidaError(f"No se puede {operacion}: {motivo}.")


# --- Datos del ingreso -------------------------------------------------------


def _texto(valor: str | None) -> str | None:
    return (valor or "").strip() or None


def normalizar_datos_recepcion(datos: DatosRecepcion | None) -> DatosRecepcion:
    """Quita espacios y accesorios vacios; ``None`` es "sin datos"."""
    if datos is None:
        return DatosRecepcion()
    return DatosRecepcion(
        estado_fisico=_texto(datos.estado_fisico),
        accesorios=[
            accesorio.strip()
            for accesorio in datos.accesorios
            if accesorio.strip()
        ],
        observaciones=_texto(datos.observaciones),
        checkin=datos.checkin,
        notas_internas=_texto(datos.notas_internas),
    )


def checkin_de(orden: OrdenReparacion) -> bool | None:
    """El check-in vigente, o ``None`` si todavia no se registro."""
    return orden.recepcion.datos.checkin if orden.recepcion else None


def recepcion_inicial(
    *,
    usuario_id: str,
    fecha: datetime,
    datos: DatosRecepcion | None = None,
) -> RecepcionEquipo:
    """Registro de recepcion que nace con el alta de la Orden.

    Queda pendiente de confirmacion: crear la Orden no prueba que el
    equipo este en el local.
    """
    return RecepcionEquipo(
        registro=RegistroRecepcion.INGRESO,
        datos=normalizar_datos_recepcion(datos),
        registrado_por=usuario_id,
        registrado_en=fecha,
    )


def _exigir_recepcion_modificable(orden: OrdenReparacion) -> None:
    if orden.recepcion is not None and orden.recepcion.no_recibido:
        no_recibido = orden.recepcion.no_recibido
        cuando = f"{no_recibido.fecha:%Y-%m-%d %H:%M}"
        raise PrecondicionInvalidaError(
            f"Ya se registro que el equipo no se recibio ({cuando}, "
            f"{no_recibido.usuario_id}): la decision no se modifica."
        )
    if orden.recepcion is not None and orden.recepcion.confirmada:
        confirmacion = orden.recepcion.confirmacion
        cuando = f"{confirmacion.fecha:%Y-%m-%d %H:%M}"
        raise PrecondicionInvalidaError(
            f"La recepcion ya se confirmo el {cuando} "
            f"({confirmacion.usuario_id}): los datos confirmados no se "
            "modifican. Agrega una observacion complementaria."
        )
    estado = estado_custodia(orden)
    if estado in (EstadoCustodia.ENTREGADO, EstadoCustodia.DEVUELTO):
        raise PrecondicionInvalidaError(
            "El equipo ya salio del local: los datos del ingreso no se "
            "modifican."
        )


def registrar_datos_recepcion(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
    datos: DatosRecepcion,
    equipo: Equipo | None = None,
) -> OrdenReparacion:
    """Registra o corrige los datos del ingreso, antes de confirmarlo.

    ``equipo`` corrige marca, modelo, identificadores o falla declarada
    (conserva su ID). La version reemplazada queda en
    ``versiones_anteriores``. En una Orden anterior a este registro, el
    primer registro es una REGULARIZACION. Sin cambios, no registra nada.
    """
    validar_alguno_de(usuario, ROLES_RECEPCION_EQUIPO)
    _exigir_recepcion_modificable(orden)

    # El check-in no es un dato del ingreso: se registra antes de la
    # entrega (``services.garantias.registrar_checkin``). La correccion
    # conserva el que haya (una Orden anterior puede tenerlo del ingreso).
    datos = normalizar_datos_recepcion(datos).model_copy(
        update={"checkin": checkin_de(orden)}
    )
    equipo_nuevo = orden.equipo
    if equipo is not None:
        equipo_nuevo = equipo.model_copy(update={"id": orden.equipo.id})
        for campo in ("marca", "modelo", "falla_reportada"):
            if not (getattr(equipo_nuevo, campo) or "").strip():
                raise PrecondicionInvalidaError(
                    f"El equipo no puede quedar sin {campo}."
                )
        equipo_nuevo = equipo_nuevo.model_copy(
            update={
                "imei": _texto(equipo_nuevo.imei),
                "numero_serie": _texto(equipo_nuevo.numero_serie),
            }
        )

    recepcion = orden.recepcion
    if (
        recepcion is not None
        and recepcion.datos == datos
        and equipo_nuevo == orden.equipo
    ):
        return orden

    nueva_orden = orden.model_copy(deep=True)
    if recepcion is None:
        nueva_orden.recepcion = RecepcionEquipo(
            registro=RegistroRecepcion.REGULARIZACION,
            datos=datos,
            registrado_por=usuario.id,
            registrado_en=fecha,
        )
        observacion = "Regularizacion: datos del ingreso registrados despues"
    else:
        actual = nueva_orden.recepcion
        actual.versiones_anteriores.append(
            VersionRecepcion(
                equipo=orden.equipo.model_copy(deep=True),
                datos=recepcion.datos.model_copy(deep=True),
                registrado_por=recepcion.registrado_por,
                registrado_en=recepcion.registrado_en,
                reemplazado_por=usuario.id,
                reemplazado_en=fecha,
            )
        )
        actual.datos = datos
        actual.registrado_por = usuario.id
        actual.registrado_en = fecha
        observacion = (
            f"Correccion de los datos del ingreso (version "
            f"{len(actual.versiones_anteriores) + 1})"
        )
    nueva_orden.equipo = equipo_nuevo

    return registrar_accion_funcional(
        nueva_orden,
        accion_id=ACCION_DATOS_RECEPCION,
        accion="REGISTRAR_DATOS_RECEPCION",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion=observacion,
    )


def confirmar_recepcion_fisica(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
    observaciones: str | None = None,
) -> OrdenReparacion:
    """El equipo quedo fisicamente en el local: empieza la custodia.

    Exige el estado fisico registrado (se documenta en que condiciones se
    recibe). Una regularizacion exige ademas una observacion que la
    justifique. Se confirma una sola vez.
    """
    validar_alguno_de(usuario, ROLES_RECEPCION_EQUIPO)

    if not politica_de(orden.origen).requiere_confirmacion_recepcion:
        raise PrecondicionInvalidaError(
            f"Un equipo {orden.origen.value} llega por el circuito de "
            "Gestion RT: su politica no usa confirmacion de recepcion."
        )
    recepcion = orden.recepcion
    if recepcion is None:
        raise PrecondicionInvalidaError(
            "Registra primero los datos del ingreso (estado fisico y "
            "accesorios): la Orden es anterior al registro de recepcion."
        )
    _exigir_recepcion_modificable(orden)
    if not recepcion.datos.estado_fisico:
        raise PrecondicionInvalidaError(
            "No se confirma la recepcion sin registrar el estado fisico del "
            "equipo."
        )
    observaciones = _texto(observaciones)
    regularizacion = recepcion.registro is RegistroRecepcion.REGULARIZACION
    if regularizacion and observaciones is None:
        raise PrecondicionInvalidaError(
            "La regularizacion de la custodia exige una observacion que la "
            "justifique."
        )

    nueva_orden = orden.model_copy(deep=True)
    nueva_orden.recepcion.confirmacion = ConfirmacionRecepcion(
        usuario_id=usuario.id,
        fecha=fecha,
        observaciones=observaciones,
    )
    observacion = "Regularizacion de custodia" if regularizacion else None
    if observaciones:
        observacion = (
            f"{observacion}: {observaciones}" if observacion else observaciones
        )
    return registrar_accion_funcional(
        nueva_orden,
        accion_id=ACCION_CONFIRMAR_RECEPCION,
        accion="CONFIRMAR_RECEPCION_FISICA",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion=observacion,
    )


def registrar_equipo_no_recibido(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
    motivo: str,
) -> OrdenReparacion:
    """Recepcion o Administracion registran que el equipo nunca ingreso.

    Es la alternativa explicita a confirmar la recepcion, y la que permite
    cerrar una Orden CANCELADA sin devolucion fisica. Exige motivo, la
    Orden cancelada (en una Orden activa la recepcion queda pendiente hasta
    que llegue el equipo) y ninguna evidencia de que el equipo estuvo en el
    local: ante un historial contradictorio se rechaza para regularizar. Se
    registra una sola vez. En una Orden anterior sin registro de recepcion,
    lo crea como REGULARIZACION.
    """
    validar_alguno_de(usuario, ROLES_RECEPCION_EQUIPO)

    if not politica_de(orden.origen).requiere_confirmacion_recepcion:
        raise PrecondicionInvalidaError(
            f"Un equipo {orden.origen.value} llega por el circuito de "
            "Gestion RT: su politica no registra la recepcion."
        )
    if orden.estado_workflow is not EstadoWorkflow.CANCELADA:
        raise PrecondicionInvalidaError(
            '"Equipo no recibido" resuelve el cierre de una Orden cancelada; '
            f"esta Orden esta {orden.estado_workflow.value}. Mientras siga "
            "activa, la recepcion queda pendiente hasta que llegue el equipo."
        )
    if orden.recepcion is not None and orden.recepcion.confirmada:
        confirmacion = orden.recepcion.confirmacion
        cuando = f"{confirmacion.fecha:%Y-%m-%d %H:%M}"
        raise PrecondicionInvalidaError(
            'No se puede registrar "Equipo no recibido": la recepcion '
            f"fisica ya se confirmo el {cuando} ({confirmacion.usuario_id}). "
            "El equipo esta en custodia: corresponde registrar su devolucion."
        )
    _exigir_recepcion_modificable(orden)
    evidencias = evidencias_de_equipo(orden)
    if evidencias:
        raise PrecondicionInvalidaError(
            'No se puede registrar "Equipo no recibido": '
            + "; ".join(evidencias)
            + ". Regulariza la custodia (confirmar la recepcion y registrar "
            "la devolucion)."
        )
    motivo = _texto(motivo)
    if motivo is None:
        raise PrecondicionInvalidaError(
            '"Equipo no recibido" exige un motivo.'
        )

    nueva_orden = orden.model_copy(deep=True)
    if nueva_orden.recepcion is None:
        nueva_orden.recepcion = RecepcionEquipo(
            registro=RegistroRecepcion.REGULARIZACION,
            registrado_por=usuario.id,
            registrado_en=fecha,
        )
    nueva_orden.recepcion.no_recibido = NoRecepcion(
        usuario_id=usuario.id, fecha=fecha, motivo=motivo
    )
    return registrar_accion_funcional(
        nueva_orden,
        accion_id=ACCION_EQUIPO_NO_RECIBIDO,
        accion="REGISTRAR_EQUIPO_NO_RECIBIDO",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion=motivo,
    )


def agregar_nota_recepcion(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
    texto: str,
    interna: bool = False,
) -> OrdenReparacion:
    """Observacion complementaria del ingreso, antes o despues de confirmar.

    No reemplaza nada: se agrega con su usuario y fecha. Una nota
    ``interna`` es solo para el personal: nunca sale en un documento.
    """
    validar_alguno_de(usuario, ROLES_RECEPCION_EQUIPO)
    texto = _texto(texto)
    if texto is None:
        raise PrecondicionInvalidaError("La observacion no puede estar vacia.")
    if orden.recepcion is None:
        raise PrecondicionInvalidaError(
            "Registra primero los datos del ingreso: la Orden es anterior al "
            "registro de recepcion."
        )

    nueva_orden = orden.model_copy(deep=True)
    nueva_orden.recepcion.notas.append(
        NotaRecepcion(
            usuario_id=usuario.id, fecha=fecha, texto=texto, interna=interna
        )
    )
    return registrar_accion_funcional(
        nueva_orden,
        accion_id=ACCION_NOTA_RECEPCION,
        accion="AGREGAR_OBSERVACION_RECEPCION",
        fecha=fecha,
        usuario_id=usuario.id,
        observacion=f"Nota interna: {texto}" if interna else texto,
    )


# --- Salida del equipo -------------------------------------------------------


def tipo_de_entrega(orden: OrdenReparacion) -> TipoEntrega:
    """Que se entrega: reparacion terminada o devolucion sin reparacion."""
    if (
        orden.estado_workflow is EstadoWorkflow.CANCELADA
        or finalizada_sin_reparacion(orden)
    ):
        return TipoEntrega.DEVOLUCION_SIN_REPARACION
    return TipoEntrega.REPARACION_TERMINADA


def armar_entrega(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
    recibido_por: str | None,
    identificacion_receptor: str | None = None,
    observaciones: str | None = None,
) -> EntregaEquipo:
    """Registro de la salida fisica del equipo; exige quien lo retira."""
    recibido_por = _texto(recibido_por)
    if recibido_por is None:
        raise PrecondicionInvalidaError(
            "La entrega exige indicar quien retira el equipo."
        )
    return EntregaEquipo(
        tipo=tipo_de_entrega(orden),
        entregado_por=usuario.id,
        recibido_por=recibido_por,
        identificacion_receptor=_texto(identificacion_receptor),
        fecha=fecha,
        observaciones=_texto(observaciones),
    )
