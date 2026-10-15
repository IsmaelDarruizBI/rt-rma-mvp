"""Situacion operativa de la Orden: que pasa, a quien le toca, que sigue.

Lectura para la pantalla, derivada de lo que la Orden ya expone: los
grupos de acciones (``application.acciones``), la custodia, la
autorizacion del cliente, el resolver de PROC-REP-211 y la cuenta. No es
otra maquina de estados: no se persiste, no habilita nada y no decide
ninguna regla. Cada tarea apunta a las acciones que la resuelven tal como
la API ya las ofrece; si dos son igual de relevantes se listan las dos,
sin inventar una prioridad.

    situacion_operativa   codigo, titulo, descripcion, responsable, desde,
                          tareas, avisos (bloqueos secundarios) y las seis
                          etapas del negocio

Los textos son de presentacion (en castellano, para el empleado); los
codigos son estables para la UI y los tests.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    EstadoCustodia,
    EstadoReparacionDetail,
    EstadoWorkflow,
    OrdenReparacion,
    RolUsuario,
)
from app.domain.politicas import CondicionComercial, politica_de
from app.services import (
    ResultadoEvaluacionOrden,
    control_tecnico_completo,
    credito_pendiente,
    definicion_finalizada,
    detalles_bloqueados_por_recursos,
    detalles_pendientes_de_autorizacion,
    ejecucion_activa,
    estado_custodia,
    finalizada_sin_reparacion,
    lista_para_cierre,
    pendiente_de_retrabajo,
    requiere_definicion,
    situacion_de_la_orden,
    toma_activa,
)

from .acciones import AccionDisponible
from .progreso import nodos_alcanzados


class CodigoSituacion:
    """Valores de ``SituacionOperativa.codigo``."""

    PENDIENTE_RECEPCION = "PENDIENTE_RECEPCION"
    PENDIENTE_DEFINICION = "PENDIENTE_DEFINICION"
    ESPERANDO_AUTORIZACION = "ESPERANDO_AUTORIZACION"
    ESPERANDO_RECURSOS = "ESPERANDO_RECURSOS"
    PENDIENTE_PRIORIDAD = "PENDIENTE_PRIORIDAD"
    EN_COLA = "EN_COLA"
    TOMADA = "TOMADA"
    EN_REPARACION = "EN_REPARACION"
    REQUIERE_REVISION_TECNICA = "REQUIERE_REVISION_TECNICA"
    CONTROL_TECNICO = "CONTROL_TECNICO"
    PENDIENTE_NOTIFICACION = "PENDIENTE_NOTIFICACION"
    PENDIENTE_COBRO = "PENDIENTE_COBRO"
    LISTA_PARA_ENTREGAR = "LISTA_PARA_ENTREGAR"
    CANCELADA_PENDIENTE_DEVOLUCION = "CANCELADA_PENDIENTE_DEVOLUCION"
    CERRADA = "CERRADA"
    SIN_TAREAS = "SIN_TAREAS"


class EstadoEtapa:
    """Valores de ``EtapaOperativa.estado``."""

    COMPLETA = "COMPLETA"
    EN_CURSO = "EN_CURSO"
    PENDIENTE = "PENDIENTE"
    NO_APLICA = "NO_APLICA"


@dataclass(frozen=True)
class TareaOperativa:
    """Algo que hay que hacer ahora y las acciones que lo resuelven."""

    titulo: str
    motivo: str
    responsable: str
    acciones: tuple[AccionDisponible, ...]


@dataclass(frozen=True)
class AvisoOperativo:
    """Un bloqueo secundario que la situacion principal no debe ocultar."""

    codigo: str
    titulo: str
    responsable: str | None = None
    acciones: tuple[AccionDisponible, ...] = ()


@dataclass(frozen=True)
class EtapaOperativa:
    """Una de las seis etapas del negocio, con su estado actual.

    Cada etapa se evalua por separado: el proceso no es lineal y dos
    pueden estar en curso a la vez (por ejemplo, un trabajo en el taller y
    otro esperando al cliente).
    """

    codigo: str
    titulo: str
    estado: str
    detalle: str | None = None


@dataclass(frozen=True)
class SituacionOperativa:
    """Que esta pasando con la Orden, quien debe actuar y que sigue."""

    codigo: str
    titulo: str
    descripcion: str
    responsable: str | None
    desde: datetime | None
    tareas: tuple[TareaOperativa, ...] = ()
    avisos: tuple[AvisoOperativo, ...] = ()
    etapas: tuple[EtapaOperativa, ...] = ()


_NOMBRE_ROL = {
    RolUsuario.RECEPCION: "Recepción",
    RolUsuario.TECNICO: "Técnico",
    RolUsuario.COORDINADOR_RMA: "Coordinación RMA",
    RolUsuario.ADMINISTRADOR: "Administración",
}
_NODOS_RECURSOS = ("PROC-REP-100", "PROC-REP-120")
_NODOS_REVISION_POSTERIOR = ("PROC-REP-125", "PROC-REP-126")


def responsable_de(acciones: Iterable[AccionDisponible]) -> str:
    """Quien puede resolver las acciones, en palabras del negocio.

    El titular de la toma cuando la accion es de una persona; "Cualquier
    usuario" para un paso de sistema o sin rol definido; si no, los roles
    autorizados, sin jerarquia entre ellos.
    """
    acciones = list(acciones)
    if any(accion.usuario_id for accion in acciones):
        return "Técnico titular"
    if any(
        not accion.requiere_actor or not accion.roles for accion in acciones
    ):
        return "Cualquier usuario"
    roles = {rol for accion in acciones for rol in accion.roles}
    return _unir([_NOMBRE_ROL[rol] for rol in _NOMBRE_ROL if rol in roles])


def _unir(partes: Sequence[str], conector: str = "o") -> str:
    if len(partes) <= 1:
        return "".join(partes)
    return f"{', '.join(partes[:-1])} {conector} {partes[-1]}"


def _importe(valor: Decimal) -> str:
    """$ 80.000,00, como lo muestra la UI."""
    texto = f"{valor:,.2f}".replace(",", "_").replace(".", ",")
    return f"$ {texto.replace('_', '.')}"


def _ultimo_paso(orden: OrdenReparacion, *nodos: str) -> datetime | None:
    """Fecha del ultimo paso del historial en alguno de esos nodos."""
    return next(
        (
            paso.fecha
            for paso in reversed(orden.historial)
            if paso.process_id in nodos
        ),
        None,
    )


def _tarea(
    titulo: str, motivo: str, acciones: Sequence[AccionDisponible]
) -> TareaOperativa:
    return TareaOperativa(
        titulo=titulo,
        motivo=motivo,
        responsable=responsable_de(acciones),
        acciones=tuple(acciones),
    )


@dataclass(frozen=True)
class _Datos:
    """La Orden y las acciones que ya calculo la capa de aplicacion."""

    orden: OrdenReparacion
    acciones: Sequence[AccionDisponible]
    autorizacion: Sequence[AccionDisponible]
    financieras: Sequence[AccionDisponible]
    custodia: Sequence[AccionDisponible]
    nombres: Mapping[str, str] = field(default_factory=dict)

    @staticmethod
    def _de(grupo: Sequence[AccionDisponible], codigos: tuple[str, ...]):
        return [accion for accion in grupo if accion.codigo in codigos]

    def flujo(self, *codigos: str) -> list[AccionDisponible]:
        return self._de(self.acciones, codigos)

    def cliente(self, *codigos: str) -> list[AccionDisponible]:
        return self._de(self.autorizacion, codigos)

    def dinero(self, *codigos: str) -> list[AccionDisponible]:
        return self._de(self.financieras, codigos)

    def equipo(self, *codigos: str) -> list[AccionDisponible]:
        return self._de(self.custodia, codigos)

    def nombre(self, detalle_id: str) -> str:
        return self.nombres.get(detalle_id, detalle_id)

    def nombres_de(self, detalle_ids: Iterable[str]) -> str:
        return _unir([self.nombre(d) for d in detalle_ids], "y")

    @property
    def cobrable(self) -> bool:
        politica = politica_de(self.orden.origen)
        return politica.condicion_comercial == CondicionComercial.COBRABLE


@dataclass(frozen=True)
class _Principal:
    codigo: str
    titulo: str
    descripcion: str
    desde: datetime | None = None
    tareas: tuple[TareaOperativa, ...] = ()
    responsable: str | None = None


def situacion_operativa(
    orden: OrdenReparacion,
    *,
    acciones: Sequence[AccionDisponible],
    acciones_autorizacion: Sequence[AccionDisponible] = (),
    acciones_financieras: Sequence[AccionDisponible] = (),
    acciones_custodia: Sequence[AccionDisponible] = (),
    nombres_de_detalle: Mapping[str, str] | None = None,
) -> SituacionOperativa:
    """La situacion de la Orden para quien la abre.

    ``codigo`` y ``titulo`` dicen que esta pasando; ``responsable``, a
    quien le toca; ``tareas``, que hay que hacer y con que acciones (las
    mismas que la API ya ofrece, con sus roles); ``avisos``, lo que queda
    pendiente aparte de lo principal; ``desde``, cuando empezo la
    situacion, solo si el historial lo registra.
    """
    datos = _Datos(
        orden=orden,
        acciones=acciones,
        autorizacion=acciones_autorizacion,
        financieras=acciones_financieras,
        custodia=acciones_custodia,
        nombres=nombres_de_detalle or {},
    )
    principal = _principal(datos)
    responsable = principal.responsable or (
        principal.tareas[0].responsable if principal.tareas else None
    )
    return SituacionOperativa(
        codigo=principal.codigo,
        titulo=principal.titulo,
        descripcion=principal.descripcion,
        responsable=responsable,
        desde=principal.desde,
        tareas=principal.tareas,
        avisos=_avisos(datos, principal.codigo),
        etapas=_etapas(datos),
    )


# --- Situacion principal -----------------------------------------------------


def _principal(datos: _Datos) -> _Principal:
    orden = datos.orden
    if orden.esta_cerrada:
        return _cerrada(datos)
    if orden.estado_workflow is EstadoWorkflow.CANCELADA:
        return _cancelada(datos)
    if lista_para_cierre(orden):
        cierre = _cierre(datos)
        if cierre is not None:
            return cierre
    for derivar in (
        _control,
        _en_reparacion,
        _revision,
        _tomada,
        _recursos,
        _autorizacion,
        _definicion,
        _prioridad,
        _cola,
    ):
        principal = derivar(datos)
        if principal is not None:
            return principal
    return _Principal(
        codigo=CodigoSituacion.SIN_TAREAS,
        titulo="Sin tareas pendientes",
        descripcion="No hay acciones disponibles para la Orden en este "
        "momento.",
    )


def _cerrada(datos: _Datos) -> _Principal:
    orden = datos.orden
    salida = orden.entrega or orden.devolucion
    if orden.estado_workflow is EstadoWorkflow.ENTREGADA:
        titulo = (
            "Entregada sin reparación"
            if finalizada_sin_reparacion(orden)
            else "Entregada"
        )
        descripcion = (
            f"El equipo se entregó a {salida.recibido_por}."
            if salida
            else "El equipo se entregó al cliente."
        )
    elif orden.estado_workflow is EstadoWorkflow.CANCELADA:
        titulo = "Cancelada"
        if orden.devolucion is not None:
            descripcion = (
                "Cancelada. El equipo se devolvió a "
                f"{orden.devolucion.recibido_por}."
            )
        elif estado_custodia(orden) is EstadoCustodia.NO_RECIBIDO:
            descripcion = "Cancelada. El equipo nunca ingresó al local."
        else:
            descripcion = "Cancelada y cerrada."
    else:
        titulo = "Devuelta a Gestión RT"
        descripcion = "El equipo volvió a Gestión RT."
    return _Principal(
        codigo=CodigoSituacion.CERRADA,
        titulo=titulo,
        descripcion=descripcion,
        desde=salida.fecha if salida else None,
    )


def _cancelada(datos: _Datos) -> _Principal:
    orden = datos.orden
    devolver = datos.flujo("REGISTRAR_DEVOLUCION")
    custodia = datos.equipo(
        "CONFIRMAR_RECEPCION", "REGISTRAR_EQUIPO_NO_RECIBIDO"
    )
    dinero = datos.dinero("REGISTRAR_DEVOLUCION_DINERO")
    tareas: list[TareaOperativa] = []
    faltan: list[str] = []
    if devolver:
        tareas.append(
            _tarea(
                "Registrar la devolución del equipo",
                "El equipo sigue en el local: se devuelve sin cobro.",
                devolver,
            )
        )
        faltan.append("devolver el equipo")
    if custodia:
        tareas.append(
            _tarea(
                "Definir qué pasó con el equipo",
                "Confirmar que está en el local (y después devolverlo) o "
                "registrar que nunca ingresó.",
                custodia,
            )
        )
        faltan.append("definir si el equipo está en el local")
    if dinero:
        credito = _importe(credito_pendiente(orden))
        tareas.append(
            _tarea(
                "Devolver el dinero al cliente",
                f"Hay {credito} a favor del cliente.",
                dinero,
            )
        )
        faltan.append(f"devolverle {credito} al cliente")
    if not tareas:
        return _Principal(
            codigo=CodigoSituacion.SIN_TAREAS,
            titulo="Cancelada",
            descripcion="La Orden se canceló.",
            desde=_ultimo_paso(orden, "PROC-REP-305", "PROC-REP-306"),
        )
    titulo = (
        "Cancelada: devolver el equipo"
        if devolver
        else (
            "Cancelada: definir la custodia del equipo"
            if custodia
            else "Cancelada: devolver dinero"
        )
    )
    return _Principal(
        codigo=CodigoSituacion.CANCELADA_PENDIENTE_DEVOLUCION,
        titulo=titulo,
        descripcion=f"La Orden se canceló. Para cerrarla falta "
        f"{_unir(faltan, 'y')}.",
        desde=_ultimo_paso(orden, "PROC-REP-305", "PROC-REP-306"),
        tareas=tuple(tareas),
    )


def _cierre(datos: _Datos) -> _Principal | None:
    """Reparacion lista (o concluida sin reparacion): avisar, cobrar,
    entregar o devolver a Gestion RT."""
    orden = datos.orden
    sin_reparacion = finalizada_sin_reparacion(orden)
    lista_desde = _ultimo_paso(orden, "PROC-REP-240", "PROC-REP-069")
    avisada_desde = _ultimo_paso(orden, "PROC-REP-260", "PROC-REP-290")
    notificar = datos.flujo("NOTIFICAR")
    if notificar:
        return _Principal(
            codigo=CodigoSituacion.PENDIENTE_NOTIFICACION,
            titulo="Pendiente de aviso al cliente",
            descripcion=(
                "La revisión concluyó sin reparación: falta avisarle al "
                "cliente."
                if sin_reparacion
                else "La reparación está lista: falta avisarle al cliente."
            ),
            desde=lista_desde,
            tareas=(
                _tarea(
                    "Avisar al cliente",
                    "Para que pase a retirar el equipo.",
                    notificar,
                ),
            ),
        )
    informar = datos.flujo("INFORMAR_RT")
    if informar:
        return _Principal(
            codigo=CodigoSituacion.PENDIENTE_NOTIFICACION,
            titulo="Pendiente de informar a Gestión RT",
            descripcion="El trabajo terminó: falta informar el resultado "
            "a Gestión RT.",
            desde=lista_desde,
            tareas=(
                _tarea(
                    "Informar el resultado a Gestión RT",
                    "Después se devuelve el equipo a Gestión RT.",
                    informar,
                ),
            ),
        )
    cobro = datos.dinero("REGISTRAR_PAGO")
    if cobro and datos.cobrable and orden.saldo > 0:
        return _Principal(
            codigo=CodigoSituacion.PENDIENTE_COBRO,
            titulo="Pendiente de cobro",
            descripcion="El cliente ya fue avisado; falta cobrar "
            f"{_importe(orden.saldo)} para poder entregar.",
            desde=avisada_desde,
            tareas=(
                _tarea(
                    "Registrar el pago pendiente",
                    "La entrega exige la cuenta saldada.",
                    cobro,
                ),
            ),
        )
    entregar = datos.flujo("ENTREGAR")
    if entregar:
        return _Principal(
            codigo=CodigoSituacion.LISTA_PARA_ENTREGAR,
            titulo="Lista para entregar",
            descripcion="El cliente fue avisado y la cuenta está saldada: "
            "puede retirar el equipo.",
            desde=avisada_desde,
            tareas=(
                _tarea(
                    "Entregar el equipo",
                    "Registrar quién lo retira; se emiten el comprobante y "
                    "la garantía.",
                    entregar,
                ),
            ),
        )
    devolver_rt = datos.flujo("DEVOLVER_RT")
    if devolver_rt:
        return _Principal(
            codigo=CodigoSituacion.LISTA_PARA_ENTREGAR,
            titulo="Lista para devolver a Gestión RT",
            descripcion="El resultado ya se informó: falta devolver el "
            "equipo a Gestión RT.",
            desde=avisada_desde,
            tareas=(
                _tarea(
                    "Devolver el equipo a Gestión RT",
                    "Cierra la Orden.",
                    devolver_rt,
                ),
            ),
        )
    return None


def _control(datos: _Datos) -> _Principal | None:
    control = datos.flujo("APROBAR_CONTROL", "RECHAZAR_CONTROL")
    if not control:
        return None
    fines = [
        ejecucion.fin
        for ejecucion in datos.orden.ejecuciones
        if ejecucion.fin is not None
    ]
    return _Principal(
        codigo=CodigoSituacion.CONTROL_TECNICO,
        titulo="Control de la reparación",
        descripcion="El taller terminó los trabajos: falta controlarlos.",
        desde=max(fines) if fines else None,
        tareas=(
            _tarea(
                "Controlar la reparación",
                "Cada trabajo realizado se aprueba, o se rechaza para "
                "retrabajo.",
                control,
            ),
        ),
    )


def _en_reparacion(datos: _Datos) -> _Principal | None:
    completar = datos.flujo("COMPLETAR_EJECUCION")
    ejecucion = ejecucion_activa(datos.orden)
    if not completar or ejecucion is None:
        return None
    trabajo = datos.nombre(ejecucion.reparacion_detail_id)
    return _Principal(
        codigo=CodigoSituacion.EN_REPARACION,
        titulo="En reparación",
        descripcion=f"El técnico está trabajando en «{trabajo}».",
        desde=ejecucion.inicio,
        tareas=(
            _tarea(
                "Completar la reparación",
                "Al terminar, registrar lo realizado y los insumos usados.",
                completar,
            ),
        ),
    )


def _revision(datos: _Datos) -> _Principal | None:
    revisar = datos.flujo("REVISAR_DETALLE", "REALIZAR_REVISION")
    redefinir = datos.flujo("REDEFINIR_DETALLE")
    if not revisar and not redefinir:
        return None
    tareas = []
    if revisar:
        tareas.append(
            _tarea(
                "Revisar el equipo",
                "El técnico revisa el equipo y deja su diagnóstico.",
                revisar,
            )
        )
    if redefinir:
        tareas.append(
            _tarea(
                "Redefinir el trabajo",
                "Con la revisión hecha, Recepción define el trabajo que "
                "corresponde.",
                redefinir,
            )
        )
    posterior = datos.orden.current_process in _NODOS_REVISION_POSTERIOR
    return _Principal(
        codigo=CodigoSituacion.REQUIERE_REVISION_TECNICA,
        titulo="Requiere revisión técnica",
        descripcion=(
            "Un trabajo necesita revisión técnica antes de seguir."
            if posterior
            else "El equipo ingresó sin diagnóstico: lo revisa el taller."
        ),
        desde=_ultimo_paso(datos.orden, "PROC-REP-125", "PROC-REP-055"),
        tareas=tuple(tareas),
    )


def _tomada(datos: _Datos) -> _Principal | None:
    iniciar = datos.flujo("INICIAR_DETALLE")
    toma = toma_activa(datos.orden)
    if not iniciar or toma is None:
        return None
    confirmar = datos.equipo("CONFIRMAR_RECEPCION")
    if confirmar and all(accion.bloqueo for accion in iniciar):
        return _Principal(
            codigo=CodigoSituacion.PENDIENTE_RECEPCION,
            titulo="Pendiente de recepción",
            descripcion="El técnico ya tomó la Orden, pero no puede empezar "
            "hasta que se confirme que el equipo está en el local.",
            desde=toma.inicio,
            tareas=(
                _tarea(
                    "Confirmar la recepción física del equipo",
                    "La reparación no puede empezar sin el equipo en "
                    "custodia.",
                    confirmar,
                ),
            ),
        )
    return _Principal(
        codigo=CodigoSituacion.TOMADA,
        titulo="Tomada por el técnico",
        descripcion="El técnico tomó la Orden y puede empezar un trabajo.",
        desde=toma.inicio,
        tareas=(
            _tarea(
                "Iniciar la reparación",
                "Elegir el trabajo; al iniciarlo se reservan los insumos.",
                iniciar,
            ),
        ),
    )


def _recursos(datos: _Datos) -> _Principal | None:
    orden = datos.orden
    if orden.current_process not in _NODOS_RECURSOS:
        return None
    tareas = []
    for accion in datos.flujo("ESPERAR_RECURSOS", "REVALIDAR_RECURSOS"):
        if accion.codigo == "ESPERAR_RECURSOS":
            tareas.append(
                _tarea(
                    "Dejar la Orden esperando repuestos",
                    "Sin forzar el trabajo: se revalida cuando ingrese stock.",
                    [accion],
                )
            )
        else:
            tareas.append(
                _tarea(
                    "Revalidar cuando ingresen los repuestos",
                    "Comprueba el stock actual; no reserva nada.",
                    [accion],
                )
            )
    forzar = datos.flujo("OVERRIDE_RECURSOS")
    if forzar:
        tareas.append(
            _tarea(
                "Forzar el trabajo sin stock",
                "Decisión de Coordinación: el impacto en el inventario se "
                "confirma antes de registrarlo.",
                forzar,
            )
        )
    bloqueados = detalles_bloqueados_por_recursos(orden)
    return _Principal(
        codigo=CodigoSituacion.ESPERANDO_RECURSOS,
        titulo="Esperando repuestos",
        descripcion=(
            f"Faltan insumos para {datos.nombres_de(bloqueados)}."
            if bloqueados
            else "Faltan insumos para los trabajos."
        ),
        desde=_ultimo_paso(orden, *_NODOS_RECURSOS),
        tareas=tuple(tareas),
        responsable=_NOMBRE_ROL[RolUsuario.COORDINADOR_RMA],
    )


def _autorizacion(datos: _Datos) -> _Principal | None:
    decision = datos.cliente("REGISTRAR_DECISION_CLIENTE")
    if not decision or (
        situacion_de_la_orden(datos.orden)
        is not ResultadoEvaluacionOrden.PENDIENTE_AUTORIZACION
    ):
        return None
    pendientes = sorted(detalles_pendientes_de_autorizacion(datos.orden))
    return _Principal(
        codigo=CodigoSituacion.ESPERANDO_AUTORIZACION,
        titulo="Esperando autorización del cliente",
        descripcion="El cliente tiene que aceptar o rechazar "
        f"{datos.nombres_de(pendientes)}.",
        desde=_ultimo_paso(datos.orden, "PROC-REP-129"),
        tareas=(
            _tarea(
                "Registrar la decisión del cliente",
                "Sin su respuesta esos trabajos no avanzan.",
                decision,
            ),
        ),
    )


def _definicion(datos: _Datos) -> _Principal | None:
    definir = datos.flujo(
        "AGREGAR_DETALLE",
        "FINALIZAR_DEFINICION",
        "ENVIAR_A_REVISION",
        "AGREGAR_DETALLE_DESDE_REVISION",
        "FINALIZAR_SIN_REPARACION",
    )
    if not definir:
        return None
    orden = datos.orden
    tarea = _tarea(
        "Definir la reparación",
        (
            "Cargar los trabajos y finalizar la definición."
            if orden.reparaciones_detail
            else "Cargar los trabajos a realizar o enviar el equipo a "
            "revisión técnica."
        ),
        definir,
    )
    confirmar = datos.equipo("CONFIRMAR_RECEPCION")
    if confirmar:
        return _Principal(
            codigo=CodigoSituacion.PENDIENTE_RECEPCION,
            titulo="Pendiente de recepción",
            descripcion="Orden recién ingresada: falta confirmar que el "
            "equipo quedó en el local y definir la reparación.",
            desde=orden.created_at,
            tareas=(
                _tarea(
                    "Confirmar la recepción física del equipo",
                    "Sin el equipo en custodia la reparación no puede "
                    "empezar.",
                    confirmar,
                ),
                tarea,
            ),
        )
    return _Principal(
        codigo=CodigoSituacion.PENDIENTE_DEFINICION,
        titulo="Pendiente de definición",
        descripcion="Falta definir qué trabajos se van a hacer.",
        desde=_ultimo_paso(orden, "PROC-REP-065") or orden.created_at,
        tareas=(tarea,),
    )


def _prioridad(datos: _Datos) -> _Principal | None:
    encolar = datos.flujo("ENCOLAR")
    if not encolar:
        return None
    return _Principal(
        codigo=CodigoSituacion.PENDIENTE_PRIORIDAD,
        titulo="Pendiente de prioridad",
        descripcion="Lista para el taller: falta asignarle prioridad e "
        "ingresarla a la cola.",
        desde=_ultimo_paso(datos.orden, "PROC-REP-140"),
        tareas=(
            _tarea(
                "Priorizar la Orden",
                "Define el orden de atención en la cola del taller.",
                encolar,
            ),
        ),
    )


def _cola(datos: _Datos) -> _Principal | None:
    tomar = datos.flujo("TOMAR")
    if not tomar:
        return None
    return _Principal(
        codigo=CodigoSituacion.EN_COLA,
        titulo=f"En cola (prioridad {datos.orden.prioridad})",
        descripcion="Esperando que un técnico la tome.",
        desde=_ultimo_paso(datos.orden, "PROC-REP-170"),
        tareas=(
            _tarea(
                "Tomar la Orden para repararla",
                "El técnico elige su estación de trabajo.",
                tomar,
            ),
        ),
    )


# --- Bloqueos secundarios ----------------------------------------------------


def _aviso(
    codigo: str, titulo: str, acciones: Sequence[AccionDisponible] = ()
) -> AvisoOperativo:
    return AvisoOperativo(
        codigo=codigo,
        titulo=titulo,
        responsable=responsable_de(acciones) if acciones else None,
        acciones=tuple(acciones),
    )


def _avisos(datos: _Datos, principal: str) -> tuple[AvisoOperativo, ...]:
    """Lo pendiente aparte de la situacion principal (estados mixtos)."""
    orden = datos.orden
    if orden.esta_cerrada or orden.estado_workflow is EstadoWorkflow.CANCELADA:
        return ()
    avisos: list[AvisoOperativo] = []
    confirmar = datos.equipo("CONFIRMAR_RECEPCION")
    if confirmar and principal != CodigoSituacion.PENDIENTE_RECEPCION:
        avisos.append(
            _aviso(
                "RECEPCION_PENDIENTE",
                "Falta confirmar la recepción física del equipo: sin ella "
                "no puede empezar la reparación.",
                confirmar,
            )
        )
    # Solo despues de presentarle los trabajos al cliente (definicion
    # finalizada): antes nadie espera su decision.
    pendientes = sorted(detalles_pendientes_de_autorizacion(orden))
    if (
        pendientes
        and definicion_finalizada(orden)
        and principal != CodigoSituacion.ESPERANDO_AUTORIZACION
    ):
        avisos.append(
            _aviso(
                "AUTORIZACION_PENDIENTE",
                "Esperando la decisión del cliente sobre "
                f"{datos.nombres_de(pendientes)}.",
                datos.cliente("REGISTRAR_DECISION_CLIENTE"),
            )
        )
    bloqueados = detalles_bloqueados_por_recursos(orden)
    if bloqueados and principal != CodigoSituacion.ESPERANDO_RECURSOS:
        avisos.append(
            _aviso(
                "SIN_REPUESTOS",
                f"Sin repuestos para {datos.nombres_de(bloqueados)}.",
                [
                    accion
                    for accion in datos.flujo("OVERRIDE_RECURSOS")
                    if accion.detalle_id in bloqueados
                ],
            )
        )
    revision = [
        d.id for d in orden.reparaciones_detail if requiere_definicion(d)
    ]
    if revision and principal != CodigoSituacion.REQUIERE_REVISION_TECNICA:
        avisos.append(
            _aviso(
                "REVISION_PENDIENTE",
                f"{datos.nombres_de(revision)} requiere revisión técnica.",
            )
        )
    retrabajo = [
        d.id for d in orden.reparaciones_detail if pendiente_de_retrabajo(d)
    ]
    if retrabajo:
        avisos.append(
            _aviso(
                "RETRABAJO",
                f"Retrabajo pendiente: {datos.nombres_de(retrabajo)} (el "
                "control lo rechazó).",
            )
        )
    if (
        lista_para_cierre(orden)
        and principal != CodigoSituacion.PENDIENTE_COBRO
        and datos.cobrable
        and orden.saldo > 0
    ):
        avisos.append(
            _aviso(
                "SALDO_PENDIENTE",
                f"Saldo pendiente de cobro: {_importe(orden.saldo)}.",
                datos.dinero("REGISTRAR_PAGO"),
            )
        )
    credito = credito_pendiente(orden)
    if credito > 0:
        avisos.append(
            _aviso(
                "CREDITO_A_FAVOR",
                f"Hay {_importe(credito)} a favor del cliente para devolver.",
                datos.dinero("REGISTRAR_DEVOLUCION_DINERO"),
            )
        )
    return tuple(avisos)


# --- Etapas del negocio ------------------------------------------------------


def _etapa(
    codigo: str, titulo: str, estado: str, detalle: str | None = None
) -> EtapaOperativa:
    return EtapaOperativa(
        codigo=codigo, titulo=titulo, estado=estado, detalle=detalle
    )


def _etapas(datos: _Datos) -> tuple[EtapaOperativa, ...]:
    """Ingreso, Autorizacion, Repuestos, Taller, Control y Entrega.

    Cada una se deriva por separado de lo que la Orden registra; ninguna
    se infiere de la posicion de las otras.
    """
    return (
        _etapa_ingreso(datos),
        _etapa_autorizacion(datos),
        _etapa_repuestos(datos),
        _etapa_taller(datos),
        _etapa_control(datos),
        _etapa_entrega(datos),
    )


def _es_cancelada(orden: OrdenReparacion) -> bool:
    return orden.estado_workflow is EstadoWorkflow.CANCELADA


def _etapa_ingreso(datos: _Datos) -> EtapaOperativa:
    orden = datos.orden
    custodia = estado_custodia(orden)
    if custodia is EstadoCustodia.NO_RECIBIDO:
        return _etapa(
            "INGRESO", "Ingreso", EstadoEtapa.NO_APLICA, "Equipo no recibido"
        )
    recibido = (
        custodia
        in (
            EstadoCustodia.EN_CUSTODIA,
            EstadoCustodia.ENTREGADO,
            EstadoCustodia.DEVUELTO,
        )
        or not politica_de(orden.origen).requiere_confirmacion_recepcion
    )
    definida = definicion_finalizada(orden) or finalizada_sin_reparacion(orden)
    # En una cancelada ya no importa la definicion: solo si el equipo esta.
    if recibido and (definida or _es_cancelada(orden)):
        return _etapa("INGRESO", "Ingreso", EstadoEtapa.COMPLETA)
    if _es_cancelada(orden):
        if datos.equipo("CONFIRMAR_RECEPCION", "REGISTRAR_EQUIPO_NO_RECIBIDO"):
            return _etapa(
                "INGRESO",
                "Ingreso",
                EstadoEtapa.EN_CURSO,
                "Falta definir si el equipo está en el local",
            )
        return _etapa("INGRESO", "Ingreso", EstadoEtapa.NO_APLICA, "Cancelada")
    return _etapa(
        "INGRESO",
        "Ingreso",
        EstadoEtapa.EN_CURSO,
        (
            "Falta confirmar la recepción"
            if not recibido
            else "Falta definir los trabajos"
        ),
    )


def _etapa_autorizacion(datos: _Datos) -> EtapaOperativa:
    orden = datos.orden
    titulo = "Autorización"
    if not politica_de(orden.origen).requiere_autorizacion_cliente:
        return _etapa(
            "AUTORIZACION", titulo, EstadoEtapa.NO_APLICA, "No requiere"
        )
    if finalizada_sin_reparacion(orden):
        return _etapa(
            "AUTORIZACION", titulo, EstadoEtapa.NO_APLICA, "Sin reparación"
        )
    if not definicion_finalizada(orden) and not _es_cancelada(orden):
        return _etapa("AUTORIZACION", titulo, EstadoEtapa.PENDIENTE)
    pendientes = detalles_pendientes_de_autorizacion(orden)
    if pendientes and not _es_cancelada(orden):
        cantidad = len(pendientes)
        return _etapa(
            "AUTORIZACION",
            titulo,
            EstadoEtapa.EN_CURSO,
            f"{cantidad} trabajo{'s' if cantidad > 1 else ''} esperando "
            "al cliente",
        )
    decididos = [
        detalle
        for detalle in orden.reparaciones_detail
        if detalle.autorizaciones
    ]
    if decididos:
        return _etapa("AUTORIZACION", titulo, EstadoEtapa.COMPLETA)
    if _es_cancelada(orden):
        return _etapa(
            "AUTORIZACION", titulo, EstadoEtapa.NO_APLICA, "Cancelada"
        )
    return _etapa("AUTORIZACION", titulo, EstadoEtapa.PENDIENTE)


def _etapa_repuestos(datos: _Datos) -> EtapaOperativa:
    orden = datos.orden
    titulo = "Repuestos"
    if finalizada_sin_reparacion(orden):
        return _etapa(
            "REPUESTOS", titulo, EstadoEtapa.NO_APLICA, "Sin reparación"
        )
    bloqueados = detalles_bloqueados_por_recursos(orden)
    if bloqueados and not _es_cancelada(orden):
        return _etapa(
            "REPUESTOS",
            titulo,
            EstadoEtapa.EN_CURSO,
            f"Faltan para {datos.nombres_de(bloqueados)}",
        )
    if "PROC-REP-080" in nodos_alcanzados(orden):
        return _etapa("REPUESTOS", titulo, EstadoEtapa.COMPLETA)
    if _es_cancelada(orden):
        return _etapa("REPUESTOS", titulo, EstadoEtapa.NO_APLICA, "Cancelada")
    return _etapa("REPUESTOS", titulo, EstadoEtapa.PENDIENTE)


def _etapa_taller(datos: _Datos) -> EtapaOperativa:
    orden = datos.orden
    titulo = "Taller"
    if finalizada_sin_reparacion(orden):
        return _etapa(
            "TALLER", titulo, EstadoEtapa.NO_APLICA, "Sin reparación"
        )
    vigentes = [
        detalle
        for detalle in orden.reparaciones_detail
        if detalle.estado is not EstadoReparacionDetail.CANCELADO
    ]
    completos = [
        detalle
        for detalle in vigentes
        if detalle.estado is EstadoReparacionDetail.COMPLETO
    ]
    retrabajo = any(pendiente_de_retrabajo(d) for d in vigentes)
    if vigentes and len(completos) == len(vigentes) and not retrabajo:
        return _etapa("TALLER", titulo, EstadoEtapa.COMPLETA)
    if _es_cancelada(orden):
        return _etapa(
            "TALLER",
            titulo,
            EstadoEtapa.COMPLETA if completos else EstadoEtapa.NO_APLICA,
            "Cancelada",
        )
    if ejecucion_activa(orden) is not None:
        return _etapa("TALLER", titulo, EstadoEtapa.EN_CURSO, "En reparación")
    if toma_activa(orden) is not None:
        return _etapa(
            "TALLER", titulo, EstadoEtapa.EN_CURSO, "Tomada por el técnico"
        )
    if retrabajo:
        return _etapa(
            "TALLER", titulo, EstadoEtapa.EN_CURSO, "Retrabajo pendiente"
        )
    if completos:
        return _etapa(
            "TALLER",
            titulo,
            EstadoEtapa.EN_CURSO,
            f"{len(completos)} de {len(vigentes)} trabajos realizados",
        )
    if orden.estado_workflow is EstadoWorkflow.EN_COLA:
        return _etapa("TALLER", titulo, EstadoEtapa.EN_CURSO, "En cola")
    return _etapa("TALLER", titulo, EstadoEtapa.PENDIENTE)


def _etapa_control(datos: _Datos) -> EtapaOperativa:
    orden = datos.orden
    titulo = "Control"
    if finalizada_sin_reparacion(orden):
        return _etapa(
            "CONTROL", titulo, EstadoEtapa.NO_APLICA, "Sin reparación"
        )
    retrabajo = any(
        pendiente_de_retrabajo(d) for d in orden.reparaciones_detail
    )
    if control_tecnico_completo(orden) and not retrabajo:
        return _etapa("CONTROL", titulo, EstadoEtapa.COMPLETA)
    if datos.flujo("APROBAR_CONTROL"):
        return _etapa("CONTROL", titulo, EstadoEtapa.EN_CURSO)
    if _es_cancelada(orden):
        return _etapa("CONTROL", titulo, EstadoEtapa.NO_APLICA, "Cancelada")
    return _etapa("CONTROL", titulo, EstadoEtapa.PENDIENTE)


def _etapa_entrega(datos: _Datos) -> EtapaOperativa:
    orden = datos.orden
    titulo = "Entrega"
    if _es_cancelada(orden):
        if orden.devolucion is not None:
            return _etapa(
                "ENTREGA",
                titulo,
                EstadoEtapa.COMPLETA,
                "Devuelto sin reparar",
            )
        if datos.flujo("REGISTRAR_DEVOLUCION"):
            return _etapa(
                "ENTREGA",
                titulo,
                EstadoEtapa.EN_CURSO,
                "Devolver el equipo",
            )
        return _etapa("ENTREGA", titulo, EstadoEtapa.NO_APLICA, "Cancelada")
    if orden.esta_cerrada:
        return _etapa(
            "ENTREGA",
            titulo,
            EstadoEtapa.COMPLETA,
            (
                "Entregado"
                if orden.estado_workflow is EstadoWorkflow.ENTREGADA
                else "Devuelto a Gestión RT"
            ),
        )
    if lista_para_cierre(orden):
        return _etapa("ENTREGA", titulo, EstadoEtapa.EN_CURSO)
    return _etapa("ENTREGA", titulo, EstadoEtapa.PENDIENTE)
