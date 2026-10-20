"""Bandejas de trabajo por rol y cola de taller (solo lectura).

Lo que cada sector tiene que hacer sale de lo que la Orden ya publica: las
tareas y los avisos de su situacion operativa (``application.situacion``),
que apuntan a las acciones de ``application.acciones`` con sus roles y su
titular. No se deduce nada de los estados, no se persiste nada y no hay
otra maquina de estados:

- Una bandeja de TAREAS reune las Ordenes con una obligacion que el
  usuario elegido puede resolver: una tarea principal o un aviso (estado
  mixto) con una accion que puede ejecutar. Una Orden con obligaciones
  independientes figura en todas las que correspondan.
- Una bandeja de SEGUIMIENTO muestra lo que el sector necesita ver aunque
  hoy no le toque actuar (la cola para Coordinacion, lo que esta en manos
  de otro sector, los insumos con disponible negativo).
- La cola de taller son las Ordenes con la accion Tomar disponible,
  ordenadas por ``clave_de_prioridad``; "Mis ordenes tomadas", las de toma
  activa del usuario.

    bandejas_de_inicio   las del rol del usuario elegido
    bandejas_de_taller   tomadas, cola y lo que esta en el taller

Nada de esto autoriza: los comandos validan rol, titular y estado igual
que siempre.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.domain.models import (
    CondicionReparacionDetail,
    EstacionTrabajo,
    EstadoReparacionDetail,
    EstadoWorkflow,
    OrdenReparacion,
    RolUsuario,
    Usuario,
)
from app.domain.prioridad import clave_de_prioridad
from app.services import (
    SituacionInsumo,
    ejecucion_activa,
    es_ingreso_inicial,
    es_trabajable,
    faltantes_de_detalles_bloqueados,
    nombre_del_trabajo,
    pendiente_de_autorizacion,
    reservas_externas_a,
    situacion_inventario,
    toma_activa,
)
from app.services.tomas import estacion_habilitada_para

from .acciones import (
    ACCION_TOMAR,
    AccionDisponible,
    acciones_de_autorizacion,
    acciones_de_custodia,
    acciones_disponibles,
    acciones_financieras,
    puede_ejecutar,
)
from .contexto import ApplicationContext
from .finanzas import SituacionFinanciera, situacion_financiera
from .situacion import CodigoSituacion, SituacionOperativa, situacion_operativa


class TipoBandeja:
    """Valores de ``Bandeja.tipo``."""

    TAREAS = "TAREAS"
    SEGUIMIENTO = "SEGUIMIENTO"


class DestinoBandeja:
    """Pantalla donde se resuelve una bandeja, ademas de cada Orden."""

    INVENTARIO = "INVENTARIO"


@dataclass(frozen=True)
class TrabajoEnBandeja:
    """Un Detalle vigente de la Orden, con lo que el backend sabe de el."""

    detalle_id: str
    nombre: str
    estado: EstadoReparacionDetail
    trabajable: bool
    pendiente_autorizacion: bool
    condicion: CondicionReparacionDetail
    en_curso: bool
    # Nombres de los insumos que hoy no alcanzan (solo si esta bloqueado
    # por recursos).
    faltantes: tuple[str, ...] = ()
    # Ingreso inicial: la autorizacion llega con el comprobante de ingreso.
    pendiente_comprobante_ingreso: bool = False


@dataclass(frozen=True)
class ItemBandeja:
    """Una Orden en una bandeja y por que esta ahi."""

    orden: OrdenReparacion
    situacion: SituacionOperativa
    # Lo que hay que hacer en esta bandeja y quien puede hacerlo.
    tarea: str | None
    responsable: str | None
    puede_resolver: bool
    # Desde cuando, si el historial lo registra (la situacion principal).
    desde: datetime | None
    condiciones: tuple[str, ...]
    trabajos: tuple[TrabajoEnBandeja, ...]
    estaciones: tuple[EstacionTrabajo, ...] = ()
    puede_tomar: bool = False


@dataclass(frozen=True)
class Bandeja:
    codigo: str
    titulo: str
    descripcion: str
    tipo: str
    ordenes: tuple[ItemBandeja, ...] = ()
    insumos: tuple[SituacionInsumo, ...] = ()
    destino: str | None = None

    @property
    def cantidad(self) -> int:
        """Lo que la bandeja lista: Ordenes o insumos."""
        return len(self.ordenes) + len(self.insumos)


@dataclass(frozen=True)
class VistaBandejas:
    usuario: Usuario
    bandejas: tuple[Bandeja, ...]


# --- Lectura de las Ordenes --------------------------------------------------


@dataclass(frozen=True)
class _Orden:
    """Una Orden con las acciones y la situacion que ya calcula el backend."""

    orden: OrdenReparacion
    acciones: tuple[AccionDisponible, ...]
    situacion: SituacionOperativa
    nombres: Mapping[str, str]


@dataclass(frozen=True)
class _Obligacion:
    """Una tarea principal o un aviso de la situacion, con sus acciones."""

    titulo: str
    responsable: str | None
    acciones: tuple[AccionDisponible, ...]
    principal: bool


def _obligaciones(leida: _Orden) -> list[_Obligacion]:
    situacion = leida.situacion
    return [
        _Obligacion(
            titulo=tarea.titulo,
            responsable=tarea.responsable,
            acciones=tarea.acciones,
            principal=True,
        )
        for tarea in situacion.tareas
    ] + [
        _Obligacion(
            titulo=aviso.titulo,
            responsable=aviso.responsable,
            acciones=aviso.acciones,
            principal=False,
        )
        for aviso in situacion.avisos
    ]


class _Lectura:
    """Las Ordenes y los catalogos leidos una sola vez por consulta."""

    def __init__(self, contexto: ApplicationContext, usuario: Usuario):
        self.usuario = usuario
        catalogos = contexto.catalogos
        tipos = {
            tipo.id: tipo.nombre
            for tipo in catalogos.listar_tipos_reparacion()
        }
        self.ordenes = contexto.ordenes.listar()
        self.insumos = catalogos.listar_insumos()
        self.previstos = catalogos.listar_tipo_reparacion_insumos()
        self.estaciones = catalogos.listar_estaciones()
        self.compatibilidades = catalogos.listar_tipo_reparacion_estaciones()
        self.leidas = [self._leer(orden, tipos) for orden in self.ordenes]

    @staticmethod
    def _leer(orden: OrdenReparacion, tipos: Mapping[str, str]) -> _Orden:
        nombres = {
            detalle.id: nombre_del_trabajo(detalle, tipos)
            for detalle in orden.reparaciones_detail
        }
        acciones = acciones_disponibles(orden)
        situacion = situacion_operativa(
            orden,
            acciones=acciones,
            acciones_autorizacion=acciones_de_autorizacion(orden),
            acciones_financieras=acciones_financieras(orden),
            acciones_custodia=acciones_de_custodia(orden),
            nombres_de_detalle=nombres,
        )
        return _Orden(
            orden=orden,
            acciones=tuple(acciones),
            situacion=situacion,
            nombres=nombres,
        )

    def puede(self, acciones: Iterable[AccionDisponible]) -> bool:
        return any(puede_ejecutar(accion, self.usuario) for accion in acciones)

    # --- Una fila -------------------------------------------------------

    def _faltantes(self, orden: OrdenReparacion) -> dict[str, tuple[str, ...]]:
        """Insumos que hoy no alcanzan, por Detalle bloqueado (consulta)."""
        nombres = {insumo.id: insumo.nombre for insumo in self.insumos}
        faltantes = faltantes_de_detalles_bloqueados(
            orden,
            insumos=self.insumos,
            insumos_previstos=self.previstos,
            reservas_externas=reservas_externas_a(orden.id, self.ordenes),
        )
        return {
            detalle_id: tuple(nombres.get(i, i) for i in insumo_ids)
            for detalle_id, insumo_ids in faltantes.items()
        }

    def _trabajos(self, leida: _Orden) -> tuple[TrabajoEnBandeja, ...]:
        orden = leida.orden
        en_curso = ejecucion_activa(orden)
        en_ingreso = es_ingreso_inicial(orden)
        faltantes = (
            self._faltantes(orden)
            if any(
                detalle.condicion
                is CondicionReparacionDetail.BLOQUEADO_POR_RECURSOS
                for detalle in orden.reparaciones_detail
            )
            else {}
        )
        return tuple(
            TrabajoEnBandeja(
                detalle_id=detalle.id,
                nombre=leida.nombres.get(detalle.id, detalle.id),
                estado=detalle.estado,
                trabajable=es_trabajable(orden, detalle),
                pendiente_autorizacion=pendiente_de_autorizacion(
                    orden, detalle
                ),
                condicion=detalle.condicion,
                en_curso=(
                    en_curso is not None
                    and en_curso.reparacion_detail_id == detalle.id
                ),
                faltantes=faltantes.get(detalle.id, ()),
                pendiente_comprobante_ingreso=en_ingreso
                and pendiente_de_autorizacion(orden, detalle),
            )
            for detalle in orden.reparaciones_detail
            if detalle.estado is not EstadoReparacionDetail.CANCELADO
        )

    def _estaciones(
        self, orden: OrdenReparacion
    ) -> tuple[EstacionTrabajo, ...]:
        """Estaciones operativas que pueden tomarla: las que admiten algun
        Detalle trabajable, la misma regla de PROC-REP-172."""
        tipos = [
            detalle.tipo_reparacion_id
            for detalle in orden.reparaciones_detail
            if es_trabajable(orden, detalle)
        ]
        return tuple(
            estacion
            for estacion in self.estaciones
            if estacion.activa
            and any(
                estacion_habilitada_para(
                    tipo, estacion.id, self.compatibilidades
                )
                for tipo in tipos
            )
        )

    def item(
        self,
        leida: _Orden,
        *,
        tarea: str | None,
        responsable: str | None,
        puede_resolver: bool,
        desde: datetime | None,
        excluir_aviso: str | None = None,
        con_estaciones: bool = False,
    ) -> ItemBandeja:
        tomar = [a for a in leida.acciones if a.codigo == ACCION_TOMAR]
        return ItemBandeja(
            orden=leida.orden,
            situacion=leida.situacion,
            tarea=tarea,
            responsable=responsable,
            puede_resolver=puede_resolver,
            desde=desde,
            condiciones=tuple(
                aviso.titulo
                for aviso in leida.situacion.avisos
                if aviso.titulo != excluir_aviso
            ),
            trabajos=self._trabajos(leida),
            estaciones=(
                self._estaciones(leida.orden) if con_estaciones else ()
            ),
            puede_tomar=self.puede(tomar),
        )

    # --- Criterios ------------------------------------------------------

    def por_acciones(
        self, *codigos: str, exigir_permiso: bool = True
    ) -> list[ItemBandeja]:
        """Ordenes con una obligacion que se resuelve con esas acciones.

        Con ``exigir_permiso`` (bandejas de tareas) solo cuentan las que el
        usuario puede ejecutar. Una fila por Orden: la primera obligacion
        que coincide (la principal antes que los avisos).
        """
        items = []
        for leida in self.leidas:
            for obligacion in _obligaciones(leida):
                acciones = [
                    a for a in obligacion.acciones if a.codigo in codigos
                ]
                if not acciones:
                    continue
                propias = self.puede(acciones)
                if exigir_permiso and not propias:
                    continue
                items.append(
                    self.item(
                        leida,
                        tarea=obligacion.titulo,
                        responsable=obligacion.responsable,
                        puede_resolver=propias,
                        desde=(
                            leida.situacion.desde
                            if obligacion.principal
                            else None
                        ),
                        excluir_aviso=(
                            None if obligacion.principal else obligacion.titulo
                        ),
                    )
                )
                break
        return _por_antiguedad(items)

    def por_situacion(
        self, situaciones: Sequence[str], avisos: Sequence[str] = ()
    ) -> list[ItemBandeja]:
        """Ordenes en esa situacion principal o con ese aviso (mixtos)."""
        items = []
        for leida in self.leidas:
            situacion = leida.situacion
            if situacion.codigo in situaciones:
                acciones = [a for t in situacion.tareas for a in t.acciones]
                items.append(
                    self.item(
                        leida,
                        tarea=situacion.descripcion,
                        responsable=situacion.responsable,
                        puede_resolver=self.puede(acciones),
                        desde=situacion.desde,
                    )
                )
                continue
            aviso = next(
                (a for a in situacion.avisos if a.codigo in avisos), None
            )
            if aviso is not None:
                items.append(
                    self.item(
                        leida,
                        tarea=aviso.titulo,
                        responsable=aviso.responsable,
                        puede_resolver=self.puede(aviso.acciones),
                        desde=None,
                        excluir_aviso=aviso.titulo,
                    )
                )
        return _por_antiguedad(items)

    def cola(self) -> list[ItemBandeja]:
        """Ordenes con la accion Tomar disponible, por prioridad.

        ``acciones_disponibles`` solo ofrece Tomar en cola, sin toma activa
        y con algun Detalle trabajable: quedan afuera las cerradas, las
        canceladas, las no trabajables y las tomadas por otro tecnico.
        """
        items = []
        for leida in self.leidas:
            tomar = [a for a in leida.acciones if a.codigo == ACCION_TOMAR]
            if not tomar:
                continue
            tarea = next(
                (
                    t
                    for t in leida.situacion.tareas
                    if any(a.codigo == ACCION_TOMAR for a in t.acciones)
                ),
                None,
            )
            items.append(
                self.item(
                    leida,
                    tarea=tarea.titulo if tarea else None,
                    responsable=tarea.responsable if tarea else None,
                    puede_resolver=self.puede(tomar),
                    desde=leida.situacion.desde if tarea else None,
                    con_estaciones=True,
                )
            )
        return sorted(items, key=lambda item: clave_de_prioridad(item.orden))

    def tomadas(
        self, filtro: Callable[[str], bool] = lambda _: True
    ) -> list[ItemBandeja]:
        """Ordenes con toma activa cuyo titular cumple ``filtro``."""
        items = []
        for leida in self.leidas:
            toma = toma_activa(leida.orden)
            if toma is None or not filtro(toma.usuario_id):
                continue
            situacion = leida.situacion
            acciones = [a for t in situacion.tareas for a in t.acciones]
            items.append(
                self.item(
                    leida,
                    tarea=situacion.tareas[0].titulo
                    if situacion.tareas
                    else None,
                    responsable=situacion.responsable,
                    puede_resolver=self.puede(acciones),
                    desde=toma.inicio,
                )
            )
        # ``desde`` es el inicio de la toma: la mas antigua primero.
        return _por_antiguedad(items)

    def en_manos_de_otros(self) -> list[ItemBandeja]:
        """Ordenes abiertas cuya tarea principal resuelve otro sector."""
        items = []
        for leida in self.leidas:
            situacion = leida.situacion
            acciones = [a for t in situacion.tareas for a in t.acciones]
            if leida.orden.esta_cerrada or not acciones:
                continue
            if self.puede(acciones):
                continue
            items.append(
                self.item(
                    leida,
                    tarea=situacion.tareas[0].titulo,
                    responsable=situacion.responsable,
                    puede_resolver=False,
                    desde=situacion.desde,
                )
            )
        return _por_antiguedad(items)

    def saldos_abiertos(
        self, excluir: Iterable[ItemBandeja] = ()
    ) -> list[ItemBandeja]:
        """Ordenes abiertas con saldo pendiente que todavia no se cobran
        para entregar (``excluir``: las que ya estan en esa bandeja)."""
        ya = {item.orden.id for item in excluir}
        items = [
            self.item(
                leida,
                tarea=None,
                responsable=None,
                puede_resolver=False,
                desde=None,
            )
            for leida in self.leidas
            if leida.orden.id not in ya
            and not leida.orden.esta_cerrada
            and leida.orden.estado_workflow is not EstadoWorkflow.CANCELADA
            and situacion_financiera(leida.orden)
            is SituacionFinanciera.SALDO_PENDIENTE
        ]
        return _por_antiguedad(items)

    def insumos_negativos(self) -> list[SituacionInsumo]:
        return [
            situacion
            for situacion in situacion_inventario(self.insumos, self.ordenes)
            if situacion.disponible < 0
        ]


def _por_antiguedad(items: list[ItemBandeja]) -> list[ItemBandeja]:
    """La que espera hace mas tiempo primero (desde, o el ingreso)."""
    return sorted(
        items,
        key=lambda item: (
            item.desde or item.orden.created_at,
            item.orden.id,
        ),
    )


def _bandeja(
    codigo: str,
    titulo: str,
    descripcion: str,
    tipo: str,
    ordenes: Sequence[ItemBandeja] = (),
    *,
    insumos: Sequence[SituacionInsumo] = (),
    destino: str | None = None,
) -> Bandeja:
    return Bandeja(
        codigo=codigo,
        titulo=titulo,
        descripcion=descripcion,
        tipo=tipo,
        ordenes=tuple(ordenes),
        insumos=tuple(insumos),
        destino=destino,
    )


# --- Bandejas por rol --------------------------------------------------------


def _recepcion(lectura: _Lectura) -> list[Bandeja]:
    tareas = TipoBandeja.TAREAS
    return [
        _bandeja(
            "RECEPCION_FISICA",
            "Confirmar la recepción física",
            "Equipos ingresados que falta confirmar en el local (o "
            "registrar que nunca llegaron).",
            tareas,
            lectura.por_acciones(
                "CONFIRMAR_RECEPCION", "REGISTRAR_EQUIPO_NO_RECIBIDO"
            ),
        ),
        _bandeja(
            "DEFINICION",
            "Definir reparaciones",
            "Cargar los trabajos, generar el comprobante de ingreso, "
            "finalizar la definición o redefinir después de una revisión "
            "técnica.",
            tareas,
            lectura.por_acciones(
                "AGREGAR_DETALLE",
                "FINALIZAR_DEFINICION",
                "GENERAR_COMPROBANTE_INGRESO",
                "ENVIAR_A_REVISION",
                "AGREGAR_DETALLE_DESDE_REVISION",
                "FINALIZAR_SIN_REPARACION",
                "REDEFINIR_DETALLE",
            ),
        ),
        _bandeja(
            "AUTORIZACION",
            "Registrar la autorización del cliente",
            "Trabajos presentados al cliente que esperan su respuesta.",
            tareas,
            lectura.por_acciones("REGISTRAR_DECISION_CLIENTE"),
        ),
        _bandeja(
            "CONTROL",
            "Realizar el control técnico",
            "Trabajos terminados por el taller que falta aprobar o rechazar.",
            tareas,
            lectura.por_acciones("APROBAR_CONTROL", "RECHAZAR_CONTROL"),
        ),
        # Cada Origen trae su cierre (``politica_de``): el cliente se
        # avisa (PROC-REP-260) y a Gestion RT se le informa (PROC-REP-290).
        _bandeja(
            "AVISO",
            "Avisar al cliente",
            "Reparaciones listas (o concluidas sin reparación) que falta "
            "avisar al cliente.",
            tareas,
            lectura.por_acciones("NOTIFICAR"),
        ),
        _bandeja(
            "INFORMAR_RT",
            "Informar a Gestión RT",
            "Equipos internos terminados: falta informar el resultado a "
            "Gestión RT para devolverlos.",
            tareas,
            lectura.por_acciones("INFORMAR_RT"),
        ),
        _bandeja(
            "COBROS",
            "Registrar cobros o devoluciones de dinero",
            "Saldos a cobrar para poder entregar y dinero a favor del "
            "cliente.",
            tareas,
            lectura.por_acciones(
                "REGISTRAR_PAGO", "REGISTRAR_DEVOLUCION_DINERO"
            ),
        ),
        _bandeja(
            "ENTREGA",
            "Entregar equipos",
            "Avisadas y con la cuenta saldada: listas para retirar.",
            tareas,
            lectura.por_acciones("ENTREGAR", "DEVOLVER_RT"),
        ),
        _bandeja(
            "DEVOLUCION_EQUIPO",
            "Devolver equipos de órdenes canceladas",
            "El equipo sigue en el local: se devuelve sin cobro.",
            tareas,
            lectura.por_acciones("REGISTRAR_DEVOLUCION"),
        ),
        _bandeja(
            "PRIORIZAR",
            "Priorizar e ingresar a la cola",
            "Órdenes habilitadas que esperan su prioridad para el taller.",
            tareas,
            lectura.por_acciones("ENCOLAR"),
        ),
        _bandeja(
            "EN_OTROS_SECTORES",
            "En manos de otros sectores",
            "Órdenes abiertas cuyo próximo paso resuelve otro sector.",
            TipoBandeja.SEGUIMIENTO,
            lectura.en_manos_de_otros(),
        ),
    ]


def _tecnico(lectura: _Lectura) -> list[Bandeja]:
    return [
        _mis_tomadas(lectura),
        _cola(lectura),
        _bandeja(
            "REVISIONES",
            "Revisiones técnicas",
            "Equipos para diagnosticar o trabajos que necesitan revisión.",
            TipoBandeja.TAREAS,
            lectura.por_acciones("REALIZAR_REVISION", "REVISAR_DETALLE"),
        ),
    ]


def _coordinacion(lectura: _Lectura) -> list[Bandeja]:
    return [
        _bandeja(
            "RECURSOS",
            "Esperando repuestos",
            "Trabajos bloqueados por falta de insumos y lo que falta. Se "
            "revalidan desde Inventario o se fuerzan desde la Orden.",
            TipoBandeja.TAREAS,
            lectura.por_situacion(
                (CodigoSituacion.ESPERANDO_RECURSOS,), ("SIN_REPUESTOS",)
            ),
            destino=DestinoBandeja.INVENTARIO,
        ),
        _bandeja(
            "PRIORIZAR",
            "Priorizar e ingresar a la cola",
            "Órdenes habilitadas que esperan su prioridad para el taller.",
            TipoBandeja.TAREAS,
            lectura.por_acciones("ENCOLAR"),
        ),
        _bandeja(
            "REVISION_PENDIENTE",
            "Revisión técnica pendiente",
            "Equipos o trabajos que el taller tiene que revisar.",
            TipoBandeja.SEGUIMIENTO,
            lectura.por_situacion(
                (CodigoSituacion.REQUIERE_REVISION_TECNICA,),
                ("REVISION_PENDIENTE",),
            ),
        ),
        _cola(lectura),
        _en_taller(lectura),
        _insumos_negativos(lectura),
    ]


def _administracion(lectura: _Lectura) -> list[Bandeja]:
    cobros = lectura.por_acciones("REGISTRAR_PAGO")
    return [
        _bandeja(
            "COBROS",
            "Cobros pendientes para entregar",
            "Reparaciones listas con saldo a cobrar.",
            TipoBandeja.TAREAS,
            cobros,
        ),
        _bandeja(
            "CREDITO",
            "Dinero a devolver al cliente",
            "Órdenes con saldo a favor del cliente: la devolución está "
            "pendiente.",
            TipoBandeja.TAREAS,
            lectura.por_acciones("REGISTRAR_DEVOLUCION_DINERO"),
        ),
        _bandeja(
            "SALDOS",
            "Otras órdenes con saldo pendiente",
            "Trabajos en curso con saldo a cobrar (todavía no se entregan).",
            TipoBandeja.SEGUIMIENTO,
            lectura.saldos_abiertos(excluir=cobros),
        ),
        _insumos_negativos(lectura),
    ]


def _mis_tomadas(lectura: _Lectura) -> Bandeja:
    usuario_id = lectura.usuario.id
    return _bandeja(
        "MIS_TOMADAS",
        "Mis órdenes tomadas",
        "Órdenes con tu toma activa.",
        TipoBandeja.TAREAS,
        lectura.tomadas(lambda titular: titular == usuario_id),
    )


def _cola(lectura: _Lectura) -> Bandeja:
    items = lectura.cola()
    return _bandeja(
        "COLA",
        "Cola de taller",
        "Disponibles para tomar, de la más urgente (1) a la normal (4); a "
        "igual prioridad, la más antigua primero.",
        # Tomar es del Tecnico (``acciones_disponibles``): para el resto
        # de los roles la cola es seguimiento.
        (
            TipoBandeja.TAREAS
            if lectura.usuario.rol is RolUsuario.TECNICO
            else TipoBandeja.SEGUIMIENTO
        ),
        items,
    )


def _en_taller(lectura: _Lectura, *, excluir_propias: bool = False) -> Bandeja:
    usuario_id = lectura.usuario.id
    return _bandeja(
        "EN_TALLER",
        "Tomadas por otros técnicos" if excluir_propias else "En el taller",
        "Órdenes con una toma activa y su técnico.",
        TipoBandeja.SEGUIMIENTO,
        lectura.tomadas(
            lambda titular: not excluir_propias or titular != usuario_id
        ),
    )


def _insumos_negativos(lectura: _Lectura) -> Bandeja:
    return _bandeja(
        "INSUMOS_NEGATIVOS",
        "Insumos con disponible negativo",
        "Hay más reservado que en stock: reponer o corregir en Inventario.",
        TipoBandeja.SEGUIMIENTO,
        insumos=lectura.insumos_negativos(),
        destino=DestinoBandeja.INVENTARIO,
    )


_INICIO: dict[RolUsuario, Callable[[_Lectura], list[Bandeja]]] = {
    RolUsuario.RECEPCION: _recepcion,
    RolUsuario.TECNICO: _tecnico,
    RolUsuario.COORDINADOR_RMA: _coordinacion,
    RolUsuario.ADMINISTRADOR: _administracion,
}


def bandejas_de_inicio(
    contexto: ApplicationContext, *, usuario_id: str
) -> VistaBandejas:
    """Las bandejas del rol del usuario elegido. Solo lectura."""
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    lectura = _Lectura(contexto, usuario)
    return VistaBandejas(
        usuario=usuario, bandejas=tuple(_INICIO[usuario.rol](lectura))
    )


def bandejas_de_taller(
    contexto: ApplicationContext, *, usuario_id: str
) -> VistaBandejas:
    """El taller: las tomadas del tecnico, la cola y lo que esta tomado.

    Para un tecnico, primero sus Ordenes tomadas, despues la cola (con la
    accion Tomar si la puede ejecutar) y las revisiones; al final las que
    tienen otros tecnicos. Para los demas roles, la cola y todo lo que
    esta en el taller. Solo lectura.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    lectura = _Lectura(contexto, usuario)
    if usuario.rol is RolUsuario.TECNICO:
        bandejas = [
            *_tecnico(lectura),
            _en_taller(lectura, excluir_propias=True),
        ]
    else:
        bandejas = [
            _cola(lectura),
            _en_taller(lectura),
            _bandeja(
                "REVISION_PENDIENTE",
                "Revisión técnica pendiente",
                "Equipos o trabajos que el taller tiene que revisar.",
                TipoBandeja.SEGUIMIENTO,
                lectura.por_situacion(
                    (CodigoSituacion.REQUIERE_REVISION_TECNICA,),
                    ("REVISION_PENDIENTE",),
                ),
            ),
        ]
    return VistaBandejas(usuario=usuario, bandejas=tuple(bandejas))
