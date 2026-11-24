"""Requisitos de insumo por Tipo y eleccion de la pieza concreta.

DEC-AJ-14 (D-14.4, modificada; precision 6 y puntos 1 y 2 de la resolucion
de la seccion 11.1 del discovery). Secuencia aprobada:

    Tipo definido -> modelo conocido -> insumos necesarios -> piezas
    compatibles elegidas -> disponibilidad -> reserva -> ejecucion

- **Requisitos:** el Tipo declara requisitos (una categoria o subcategoria y
  una cantidad, ``TipoReparacionRequisito``) junto a los insumos previstos
  concretos, que se conservan y funcionan como siempre.
- **Pieza elegida:** por requisito, el Detalle guarda la pieza concreta
  (``EleccionPieza``, append-only). La elige el sistema si hay una sola
  compatible y activa (``AUTOMATICA``); si no, quien prepara el trabajo
  (``PIEZA_ELEGIR``). Sin modelo tecnico se ofrecen las universales y, si
  no hay ninguna, cualquiera de la categoria con motivo y la marca
  «compatibilidad no verificada».
- **Factibilidad (PROC-REP-080):** sobre la pieza elegida; un requisito sin
  pieza cuenta como factible si alguna pieza elegible tiene disponible
  suficiente.
- **Reserva (PROC-REP-185):** reserva la pieza elegida con el motor de
  siempre (todo o nada; el override sigue igual). No se inicia con un
  requisito sin pieza.
- **Sustitucion:** antes de reservar cambia la eleccion (con motivo);
  despues de reservar y antes de consumir, libera la reserva de la pieza
  anterior y reserva la nueva en la misma operacion. No se sustituye una
  pieza ya consumida en el trabajo.
- **Sin requisitos:** todo funciona como antes.

El motor de reservas, movimientos y consumo no cambia: las piezas elegidas
entran a ``insumos_previstos_del_detalle`` (``services.inventario``) y desde
ahi a la factibilidad, la reserva y el formulario de consumo.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    CategoriaInsumo,
    CausaEleccionPieza,
    EleccionPieza,
    EstadoEjecucion,
    EstadoReparacionDetail,
    EstadoWorkflow,
    Insumo,
    MovimientoInsumo,
    OrdenReparacion,
    ReparacionDetail,
    TipoMovimientoInsumo,
    TipoReparacionInsumos,
    TipoReparacionRequisito,
    Usuario,
)

from . import permisos
from .autorizacion import validar_alguno_de
from .clasificacion_insumos import (
    categorias_por_id,
    compatible,
    en_categoria,
    insumos_compatibles,
)
from .exceptions import (
    EntidadNoEncontradaError,
    PrecondicionInvalidaError,
    RecursoNoDisponibleError,
)
from .identificadores import nuevo_id
from .inventario import (
    PREFIJO_SUSTITUCION,
    cantidad_pendiente,
    cantidad_reservable,
    faltantes_del_detalle,
    piezas_vigentes,
    reservas_activas,
    stock_disponible,
)
from .recursos import tiene_override_factibilidad
from .tomas import buscar_detalle
from .workflow import registrar_accion_funcional

CERO = Decimal("0")

# Accion funcional del historial (nueva, DEC-AJ-14): elegir, sustituir o
# revisar la pieza de un trabajo. En PostgreSQL, EV-REP-010 «Detalle
# definido» (la pieza es parte de la definicion o preparacion del trabajo);
# la sustitucion de una pieza reservada, EV-REP-024 «Movimientos de
# inventario generados».
ACCION_PIEZA = "ACC-REP-084"
ACCION_ELEGIR = "ELEGIR_PIEZA"
ACCION_ELEGIR_AUTOMATICA = "ELEGIR_PIEZA_AUTOMATICA"
ACCION_SUSTITUIR = "SUSTITUIR_PIEZA"
ACCION_SUSTITUIR_RESERVADA = "SUSTITUIR_PIEZA_RESERVADA"
ACCION_REVISAR = "REVISAR_PIEZA"

# Prefijo de los faltantes de un requisito sin pieza elegida y sin ninguna
# pieza elegible con disponible suficiente.
PREFIJO_SIN_PIEZA = "Sin pieza elegida"

_DETALLE_ABIERTO = (
    EstadoReparacionDetail.DEFINIDO,
    EstadoReparacionDetail.EN_PROGRESO,
)


class PiezaSinElegirError(PrecondicionInvalidaError):
    """No se inicia una Ejecucion con requisitos sin pieza elegida."""

    codigo = "PIEZA_SIN_ELEGIR"


@dataclass(frozen=True)
class RequisitosInsumo:
    """Los requisitos de todos los Tipos y las categorias para resolverlos.

    Vacio (``SIN_REQUISITOS``): ningun Tipo tiene requisitos y todo
    funciona como antes (el modo JSON sin el archivo de requisitos).
    """

    requisitos: tuple[TipoReparacionRequisito, ...] = ()
    categorias: tuple[CategoriaInsumo, ...] = ()

    def del_tipo(
        self, tipo_reparacion_id: str
    ) -> list[TipoReparacionRequisito]:
        """Los requisitos vigentes de un Tipo, en su orden."""
        return sorted(
            (
                requisito
                for requisito in self.requisitos
                if requisito.activo
                and requisito.tipo_reparacion_id == tipo_reparacion_id
            ),
            key=lambda r: (r.posicion, r.categoria_id),
        )

    def buscar(self, requisito_id: str) -> TipoReparacionRequisito | None:
        return next((r for r in self.requisitos if r.id == requisito_id), None)

    @property
    def por_categoria(self) -> dict[str, CategoriaInsumo]:
        return categorias_por_id(self.categorias)

    def nombre_categoria(self, categoria_id: str) -> str:
        """«Baterias» o «Modulos › OLED»; el codigo si no se conoce."""
        categorias = self.por_categoria
        categoria = categorias.get(categoria_id)
        if categoria is None:
            return categoria_id
        padre = categorias.get(categoria.padre_id or "")
        return (
            f"{padre.nombre} › {categoria.nombre}"
            if padre
            else (categoria.nombre)
        )


SIN_REQUISITOS = RequisitosInsumo()


def modelo_de(orden: OrdenReparacion) -> str | None:
    """El modelo tecnico del equipo (``MOD-…``), si tiene."""
    return orden.equipo.modelo_tecnico_id


def requisitos_pendientes(
    detalle: ReparacionDetail, requisitos: RequisitosInsumo
) -> list[TipoReparacionRequisito]:
    """Los requisitos vigentes del Tipo del Detalle sin pieza elegida."""
    vigentes = piezas_vigentes(detalle)
    return [
        requisito
        for requisito in requisitos.del_tipo(detalle.tipo_reparacion_id)
        if requisito.id not in vigentes
    ]


def ultima_eleccion(
    detalle: ReparacionDetail, requisito_id: str
) -> EleccionPieza | None:
    """El ultimo registro de ese requisito (con pieza o anulado)."""
    return next(
        (
            e
            for e in reversed(detalle.piezas)
            if e.requisito_id == requisito_id
        ),
        None,
    )


# --- Piezas elegibles -------------------------------------------------------


def piezas_elegibles(
    insumos: Iterable[Insumo],
    modelo_equipo_id: str | None,
    categoria_id: str,
    categorias: Iterable[CategoriaInsumo] = (),
) -> tuple[list[Insumo], bool]:
    """Las piezas activas que se pueden elegir para una categoria, y si su
    compatibilidad queda sin verificar.

    - Con modelo: las compatibles con ese modelo (universales incluidas).
    - Sin modelo tecnico: las universales; si no hay ninguna, cualquiera de
      la categoria, con «compatibilidad no verificada» (punto 2 de la
      resolucion de 11.1: exige motivo).
    """
    insumos = list(insumos)
    categorias = list(categorias)
    compatibles = insumos_compatibles(
        insumos, modelo_equipo_id, categoria_id, categorias=categorias
    )
    if compatibles or modelo_equipo_id is not None:
        return compatibles, False
    por_id = categorias_por_id(categorias)
    return (
        [
            insumo
            for insumo in insumos
            if insumo.activo and en_categoria(insumo, categoria_id, por_id)
        ],
        True,
    )


def eleccion_consistente(
    eleccion: EleccionPieza,
    insumo: Insumo | None,
    modelo_equipo_id: str | None,
) -> bool:
    """La pieza elegida sigue sirviendo para el modelo actual del equipo.

    Compatible con el modelo, o elegida sin verificar para un equipo que
    sigue sin modelo tecnico."""
    if insumo is None:
        return False
    if compatible(insumo, modelo_equipo_id):
        return True
    return modelo_equipo_id is None and eleccion.compatibilidad_no_verificada


def _movimientos_del_detalle(
    orden: OrdenReparacion, detalle_id: str, insumo_id: str
) -> list[MovimientoInsumo]:
    return [
        m
        for m in orden.movimientos_insumo
        if m.reparacion_detail_id == detalle_id and m.insumo_id == insumo_id
    ]


def pieza_consumida(
    orden: OrdenReparacion, detalle_id: str, insumo_id: str
) -> bool:
    """Hay CONSUMO o DESPERDICIO de esa pieza en el Detalle (BR-REP-005)."""
    return any(
        m.tipo
        in (TipoMovimientoInsumo.CONSUMO, TipoMovimientoInsumo.DESPERDICIO)
        for m in _movimientos_del_detalle(orden, detalle_id, insumo_id)
    )


def reservas_pendientes_de(
    orden: OrdenReparacion, detalle_id: str, insumo_id: str
) -> list[MovimientoInsumo]:
    """Las RESERVA del Detalle de ese insumo con cantidad pendiente."""
    return [
        reserva
        for reserva in reservas_activas(orden.movimientos_insumo)
        if reserva.reparacion_detail_id == detalle_id
        and reserva.insumo_id == insumo_id
    ]


# --- Factibilidad (PROC-REP-080) --------------------------------------------


def requisito_factible(
    requisito: TipoReparacionRequisito,
    *,
    insumos: Sequence[Insumo],
    modelo_equipo_id: str | None,
    categorias: Iterable[CategoriaInsumo],
    movimientos: Sequence[MovimientoInsumo],
    reservas_externas: Mapping[str, Decimal] | None = None,
) -> bool:
    """Punto 1 de la resolucion: un requisito sin pieza elegida es factible
    si alguna pieza elegible tiene disponible suficiente (sin reservar)."""
    ajenas = reservas_externas or {}
    candidatas, _ = piezas_elegibles(
        insumos, modelo_equipo_id, requisito.categoria_id, categorias
    )
    return any(
        stock_disponible(insumo, movimientos, ajenas.get(insumo.id, CERO))
        >= requisito.cantidad
        for insumo in candidatas
    )


def faltante_de_requisito(
    requisito: TipoReparacionRequisito, requisitos: RequisitosInsumo
) -> str:
    """Como se nombra un requisito sin pieza y sin disponible (no es un ID
    de insumo: Compras no lo cuenta como demanda de un SKU)."""
    return (
        f"{PREFIJO_SIN_PIEZA}: "
        f"{requisitos.nombre_categoria(requisito.categoria_id)}"
    )


def es_faltante_de_requisito(faltante: str) -> bool:
    return faltante.startswith(PREFIJO_SIN_PIEZA)


def faltantes_con_requisitos(
    orden: OrdenReparacion,
    detalle: ReparacionDetail,
    *,
    insumos: Sequence[Insumo],
    insumos_previstos: Sequence[TipoReparacionInsumos],
    reservas_externas: Mapping[str, Decimal] | None = None,
    requisitos: RequisitosInsumo | None = None,
) -> list[str]:
    """Lo que falta hoy para el Detalle (PROC-REP-080/185/186).

    Los insumos previstos concretos y las piezas elegidas, como siempre
    (``faltantes_del_detalle``); despues, cada requisito sin pieza elegida
    que no tenga ninguna pieza elegible con disponible suficiente.
    """
    faltantes = faltantes_del_detalle(
        detalle,
        orden.movimientos_insumo,
        insumos,
        insumos_previstos,
        reservas_externas,
    )
    requisitos = requisitos or SIN_REQUISITOS
    for requisito in requisitos_pendientes(detalle, requisitos):
        if not requisito_factible(
            requisito,
            insumos=insumos,
            modelo_equipo_id=modelo_de(orden),
            categorias=requisitos.categorias,
            movimientos=orden.movimientos_insumo,
            reservas_externas=reservas_externas,
        ):
            faltantes.append(faltante_de_requisito(requisito, requisitos))
    return faltantes


# --- Reserva (PROC-REP-185) -------------------------------------------------


def exigir_piezas_elegidas(
    orden: OrdenReparacion,
    detalle: ReparacionDetail,
    *,
    insumos: Sequence[Insumo],
    requisitos: RequisitosInsumo,
) -> None:
    """D-14.4 (precision c): no se inicia la Ejecucion con un requisito sin
    pieza elegida, ni con una pieza elegida dada de baja o que ya no sirve
    para el modelo del equipo (se sustituye antes)."""
    pendientes = requisitos_pendientes(detalle, requisitos)
    if pendientes:
        nombres = ", ".join(
            requisitos.nombre_categoria(r.categoria_id) for r in pendientes
        )
        raise PiezaSinElegirError(
            f"Falta elegir la pieza de {nombres} en el Detalle "
            f"{detalle.id}: se elige antes de iniciar (no se reservo nada)."
        )
    por_id = {insumo.id: insumo for insumo in insumos}
    modelo = modelo_de(orden)
    for eleccion in piezas_vigentes(detalle).values():
        insumo = por_id.get(eleccion.insumo_id or "")
        if insumo is None or not insumo.activo:
            raise PiezaSinElegirError(
                f"La pieza elegida {eleccion.insumo_id} del Detalle "
                f"{detalle.id} no esta vigente: sustituila antes de iniciar."
            )
        if not eleccion_consistente(eleccion, insumo, modelo):
            raise PiezaSinElegirError(
                f"La pieza elegida {insumo.codigo} del Detalle {detalle.id} "
                "no es compatible con el modelo actual del equipo: "
                "sustituila antes de iniciar."
            )


# --- Eleccion y sustitucion -------------------------------------------------


def _exigir_detalle_abierto(
    orden: OrdenReparacion, detalle: ReparacionDetail
) -> None:
    if orden.esta_cerrada or orden.estado_workflow is EstadoWorkflow.CANCELADA:
        raise PrecondicionInvalidaError(
            f"La Orden {orden.id} esta cerrada: no se eligen piezas."
        )
    if detalle.estado not in _DETALLE_ABIERTO:
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle.id} esta {detalle.estado.value}: su pieza "
            "ya no se elige ni se sustituye."
        )


def _texto_pieza(insumo: Insumo | None, insumo_id: str | None) -> str:
    if insumo is None:
        return insumo_id or "sin pieza"
    return f"{insumo.codigo} {insumo.nombre}"


def elegir_pieza(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    requisito_id: str,
    insumo_id: str,
    usuario: Usuario,
    insumos: Sequence[Insumo],
    requisitos: RequisitosInsumo,
    fecha: datetime,
    motivo: str | None = None,
    reservas_externas: Mapping[str, Decimal] | None = None,
) -> OrdenReparacion:
    """Elegir o sustituir la pieza de un requisito (``PIEZA_ELEGIR``).

    - Detalle DEFINIDO: registra la eleccion (``ELECCION``) o la
      sustitucion (``SUSTITUCION``, con motivo). No toca el inventario.
    - Detalle EN_PROGRESO (ya reservado, BR-REP-006): solo sustitucion, con
      motivo y en una sola operacion: LIBERACION_RESERVA de lo pendiente de
      la pieza anterior y RESERVA de la nueva, trazadas a la Ejecucion en
      curso y al Detalle. Sin disponible para la nueva se rechaza (nada
      cambia), salvo override vigente del Detalle, que reserva solo lo
      disponible (como al iniciar, P-06).
    - Nunca se sustituye una pieza ya consumida (o desperdiciada) en el
      Detalle.

    Solo piezas activas y elegibles para el modelo del equipo
    (``piezas_elegibles``); una sin compatibilidad verificada exige motivo.
    """
    validar_alguno_de(usuario, permisos.PIEZA_ELEGIR)
    detalle = buscar_detalle(orden, detalle_id)
    _exigir_detalle_abierto(orden, detalle)
    requisito = requisitos.buscar(requisito_id)
    if requisito is None or (
        requisito.tipo_reparacion_id != detalle.tipo_reparacion_id
    ):
        raise EntidadNoEncontradaError(
            f"El Detalle {detalle_id} no tiene el requisito {requisito_id}."
        )
    anterior = piezas_vigentes(detalle).get(requisito_id)
    if anterior is None and not requisito.activo:
        raise PrecondicionInvalidaError(
            f"El requisito {requisito_id} ya no esta vigente en el Tipo."
        )
    por_id = {insumo.id: insumo for insumo in insumos}
    insumo = por_id.get(insumo_id)
    if insumo is None:
        raise EntidadNoEncontradaError(f"Insumo inexistente: {insumo_id}")
    if anterior is not None and anterior.insumo_id == insumo_id:
        raise PrecondicionInvalidaError(
            f"{insumo.codigo} ya es la pieza elegida: no hay cambios."
        )
    if not insumo.activo:
        raise PrecondicionInvalidaError(
            f"El insumo {insumo.codigo} esta dado de baja: no se elige."
        )
    modelo = modelo_de(orden)
    elegibles, sin_verificar = piezas_elegibles(
        insumos, modelo, requisito.categoria_id, requisitos.categorias
    )
    if insumo not in elegibles:
        nombre = requisitos.nombre_categoria(requisito.categoria_id)
        if modelo is None:
            raise PrecondicionInvalidaError(
                f"{insumo.codigo} no se puede elegir para {nombre}: el "
                "equipo no tiene modelo tecnico y hay piezas universales "
                "de la categoria (o no es de la categoria)."
            )
        raise PrecondicionInvalidaError(
            f"{insumo.codigo} no es una pieza de {nombre} compatible con el "
            f"modelo {modelo} del equipo."
        )
    motivo = (motivo or "").strip() or None
    if anterior is not None and motivo is None:
        raise PrecondicionInvalidaError(
            "Sustituir la pieza elegida exige indicar el motivo."
        )
    if sin_verificar and motivo is None:
        raise PrecondicionInvalidaError(
            "El equipo no tiene modelo tecnico y la pieza no es universal: "
            "elegirla exige un motivo (compatibilidad no verificada)."
        )
    if anterior is not None and pieza_consumida(
        orden, detalle_id, anterior.insumo_id or ""
    ):
        raise PrecondicionInvalidaError(
            f"La pieza {anterior.insumo_id} ya se consumio en el Detalle "
            f"{detalle_id}: no se sustituye."
        )
    en_curso = detalle.estado is EstadoReparacionDetail.EN_PROGRESO
    if en_curso and anterior is None:
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} ya inicio su Ejecucion: la pieza se "
            "elige antes de iniciar."
        )

    ultimo = ultima_eleccion(detalle, requisito_id)
    eleccion = EleccionPieza(
        id=nuevo_id("PZA"),
        requisito_id=requisito.id,
        tipo_reparacion_id=detalle.tipo_reparacion_id,
        categoria_id=(
            anterior.categoria_id if anterior else requisito.categoria_id
        ),
        cantidad=anterior.cantidad if anterior else requisito.cantidad,
        insumo_id=insumo.id,
        causa=(
            CausaEleccionPieza.SUSTITUCION
            if anterior
            else CausaEleccionPieza.ELECCION
        ),
        compatibilidad_no_verificada=sin_verificar,
        modelo_equipo_id=modelo,
        motivo=motivo,
        usuario_id=usuario.id,
        fecha=fecha,
        # Encadena con el ultimo registro del requisito (tambien uno
        # anulado): la cadena de cada requisito es lineal.
        reemplaza_a=ultimo.id if ultimo else None,
    )
    texto_anterior = (
        _texto_pieza(por_id.get(anterior.insumo_id or ""), anterior.insumo_id)
        if anterior
        else None
    )
    descripcion = (
        f"{requisitos.nombre_categoria(eleccion.categoria_id)} x "
        f"{eleccion.cantidad}: "
        + (f"{texto_anterior} -> " if texto_anterior else "")
        + _texto_pieza(insumo, insumo.id)
        + (" (compatibilidad no verificada)" if sin_verificar else "")
        + (f". Motivo: {motivo}" if motivo else "")
    )

    if not en_curso:
        nueva = registrar_accion_funcional(
            orden,
            accion_id=ACCION_PIEZA,
            accion=ACCION_SUSTITUIR if anterior else ACCION_ELEGIR,
            fecha=fecha,
            usuario_id=usuario.id,
            reparacion_detail_id=detalle_id,
            observacion=descripcion,
        )
        buscar_detalle(nueva, detalle_id).piezas.append(eleccion)
        return nueva

    assert anterior is not None and anterior.insumo_id is not None
    return _sustituir_reservada(
        orden,
        detalle=detalle,
        anterior=anterior,
        eleccion=eleccion,
        insumo=insumo,
        insumos=insumos,
        usuario=usuario,
        fecha=fecha,
        descripcion=descripcion,
        reservas_externas=reservas_externas,
    )


def _sustituir_reservada(
    orden: OrdenReparacion,
    *,
    detalle: ReparacionDetail,
    anterior: EleccionPieza,
    eleccion: EleccionPieza,
    insumo: Insumo,
    insumos: Sequence[Insumo],
    usuario: Usuario,
    fecha: datetime,
    descripcion: str,
    reservas_externas: Mapping[str, Decimal] | None,
) -> OrdenReparacion:
    """Liberacion + reserva nueva en una sola operacion (todo o nada)."""
    ejecucion = next(
        (
            e
            for e in orden.ejecuciones
            if e.reparacion_detail_id == detalle.id
            and e.estado is EstadoEjecucion.EN_PROGRESO
        ),
        None,
    )
    if ejecucion is None:
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle.id} no tiene una Ejecucion en curso."
        )
    ajenas = reservas_externas or {}
    requerido = eleccion.cantidad
    disponible = stock_disponible(
        insumo, orden.movimientos_insumo, ajenas.get(insumo.id, CERO)
    )
    con_override = tiene_override_factibilidad(orden, detalle.id)
    if con_override:
        a_reservar = cantidad_reservable(requerido, disponible)
    else:
        if disponible < requerido:
            raise RecursoNoDisponibleError(
                f"{insumo.codigo} tiene disponible {disponible} y la pieza "
                f"necesita {requerido}: no se sustituyo (la reserva de la "
                "pieza anterior sigue igual)."
            )
        a_reservar = requerido

    # Lo pendiente de la pieza anterior en el Detalle, hasta la cantidad de
    # la eleccion (la pieza puede coincidir con un previsto concreto: el
    # resto sigue reservado). De la reserva mas reciente a la mas antigua.
    por_liberar = requerido
    movimientos: list[MovimientoInsumo] = []
    for reserva in reversed(
        reservas_pendientes_de(orden, detalle.id, anterior.insumo_id or "")
    ):
        if por_liberar <= CERO:
            break
        pendiente = cantidad_pendiente(reserva, orden.movimientos_insumo)
        liberada = min(pendiente, por_liberar)
        movimientos.append(
            MovimientoInsumo(
                id=nuevo_id("MOV"),
                tipo=TipoMovimientoInsumo.LIBERACION_RESERVA,
                insumo_id=reserva.insumo_id,
                reparacion_detail_id=detalle.id,
                ejecucion_id=ejecucion.id,
                cantidad=liberada,
                movimiento_origen_id=reserva.id,
                usuario_id=usuario.id,
                fecha=fecha,
                observacion=f"{PREFIJO_SUSTITUCION}: {descripcion}",
            )
        )
        por_liberar -= liberada
    if a_reservar > CERO:
        movimientos.append(
            MovimientoInsumo(
                id=nuevo_id("MOV"),
                tipo=TipoMovimientoInsumo.RESERVA,
                insumo_id=insumo.id,
                reparacion_detail_id=detalle.id,
                ejecucion_id=ejecucion.id,
                cantidad=a_reservar,
                usuario_id=usuario.id,
                fecha=fecha,
                observacion=f"{PREFIJO_SUSTITUCION}: {descripcion}",
            )
        )
    nota = ""
    if a_reservar < requerido:
        nota = (
            f". Reserva parcial por override: {a_reservar} de {requerido} "
            "(sin stock para el resto)"
        )
    nueva = registrar_accion_funcional(
        orden,
        accion_id=ACCION_PIEZA,
        accion=ACCION_SUSTITUIR_RESERVADA,
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle.id,
        ejecucion_id=ejecucion.id,
        observacion=descripcion + nota,
    )
    nueva.movimientos_insumo.extend(movimientos)
    buscar_detalle(nueva, detalle.id).piezas.append(eleccion)
    return nueva


# --- Eleccion automatica y revision por cambios -----------------------------


def conciliar_piezas(
    orden: OrdenReparacion,
    *,
    requisitos: RequisitosInsumo,
    insumos: Sequence[Insumo],
    usuario_id: str,
    fecha: datetime,
    detalle_ids: Iterable[str] | None = None,
) -> OrdenReparacion:
    """Deja las piezas de los Detalles pendientes (DEFINIDO) al dia.

    Corre al definir o redefinir trabajos, al cambiar el modelo del equipo
    y al iniciar una Ejecucion. Es idempotente: sin cambios devuelve la
    misma Orden.

    1. **Revision:** una pieza elegida para otro Tipo (el trabajo se
       redefinio) se anula (``REDEFINICION``); una que ya no sirve para el
       modelo del equipo se anula o, si hay una sola compatible, se
       reemplaza por ella (``CAMBIO_MODELO``). Nunca se toca una pieza con
       reserva pendiente o ya consumida en el Detalle: queda como esta (la
       pantalla avisa y se sustituye a mano).
    2. **Eleccion automatica:** cada requisito vigente sin pieza que tiene
       una sola pieza compatible y activa la recibe (``AUTOMATICA``). Sin
       modelo tecnico, una sola universal; si no hay universales no hay
       eleccion automatica (hace falta motivo).

    Los Detalles EN_PROGRESO, COMPLETO o CANCELADO no cambian.
    """
    if not requisitos.requisitos and not any(
        detalle.piezas for detalle in orden.reparaciones_detail
    ):
        return orden
    filtro = set(detalle_ids) if detalle_ids is not None else None
    modelo = modelo_de(orden)
    por_id = {insumo.id: insumo for insumo in insumos}
    nueva = orden
    for detalle in orden.reparaciones_detail:
        if detalle.estado is not EstadoReparacionDetail.DEFINIDO:
            continue
        if filtro is not None and detalle.id not in filtro:
            continue
        nueva = _conciliar_detalle(
            nueva,
            detalle.id,
            requisitos=requisitos,
            insumos=insumos,
            por_id=por_id,
            modelo=modelo,
            usuario_id=usuario_id,
            fecha=fecha,
        )
    return nueva


def _intocable(
    orden: OrdenReparacion, detalle_id: str, insumo_id: str
) -> bool:
    return bool(
        reservas_pendientes_de(orden, detalle_id, insumo_id)
    ) or pieza_consumida(orden, detalle_id, insumo_id)


def _conciliar_detalle(
    orden: OrdenReparacion,
    detalle_id: str,
    *,
    requisitos: RequisitosInsumo,
    insumos: Sequence[Insumo],
    por_id: Mapping[str, Insumo],
    modelo: str | None,
    usuario_id: str,
    fecha: datetime,
) -> OrdenReparacion:
    detalle = buscar_detalle(orden, detalle_id)
    registros: list[tuple[EleccionPieza, str, str]] = []

    def agregar(eleccion: EleccionPieza, accion: str, texto: str) -> None:
        registros.append((eleccion, accion, texto))

    # 1. Revision de las elecciones vigentes de cada requisito.
    ultimas: dict[str, EleccionPieza] = {}
    for eleccion in detalle.piezas:
        ultimas[eleccion.requisito_id] = eleccion
    reemplazadas: dict[str, EleccionPieza] = {}
    for requisito_id, eleccion in ultimas.items():
        if eleccion.insumo_id is None:
            continue
        if _intocable(orden, detalle_id, eleccion.insumo_id):
            continue
        nombre = requisitos.nombre_categoria(eleccion.categoria_id)
        insumo = por_id.get(eleccion.insumo_id)
        pieza = _texto_pieza(insumo, eleccion.insumo_id)
        if eleccion.tipo_reparacion_id != detalle.tipo_reparacion_id:
            agregar(
                eleccion.model_copy(
                    update={
                        "id": nuevo_id("PZA"),
                        "insumo_id": None,
                        "causa": CausaEleccionPieza.REDEFINICION,
                        "compatibilidad_no_verificada": False,
                        "modelo_equipo_id": modelo,
                        "motivo": None,
                        "usuario_id": usuario_id,
                        "fecha": fecha,
                        "reemplaza_a": eleccion.id,
                    }
                ),
                ACCION_REVISAR,
                f"{nombre}: {pieza} anulada (el trabajo se redefinio a "
                f"{detalle.tipo_reparacion_id})",
            )
            continue
        if eleccion_consistente(eleccion, insumo, modelo):
            continue
        reemplazadas[requisito_id] = eleccion
    # Las que ya no sirven para el modelo: reemplazo por la unica compatible
    # o anulacion.
    for requisito_id, eleccion in reemplazadas.items():
        nombre = requisitos.nombre_categoria(eleccion.categoria_id)
        pieza = _texto_pieza(
            por_id.get(eleccion.insumo_id or ""), eleccion.insumo_id
        )
        candidatas, sin_verificar = piezas_elegibles(
            insumos, modelo, eleccion.categoria_id, requisitos.categorias
        )
        unica = (
            candidatas[0]
            if len(candidatas) == 1 and not sin_verificar
            else None
        )
        agregar(
            eleccion.model_copy(
                update={
                    "id": nuevo_id("PZA"),
                    "insumo_id": unica.id if unica else None,
                    "causa": CausaEleccionPieza.CAMBIO_MODELO,
                    "compatibilidad_no_verificada": False,
                    "modelo_equipo_id": modelo,
                    "motivo": None,
                    "usuario_id": usuario_id,
                    "fecha": fecha,
                    "reemplaza_a": eleccion.id,
                }
            ),
            ACCION_REVISAR,
            f"{nombre}: {pieza} no es compatible con el modelo "
            f"{modelo or 'sin modelo tecnico'}"
            + (
                f"; se elige {_texto_pieza(unica, unica.id)}, la unica "
                "compatible"
                if unica
                else "; queda pendiente de elegir"
            ),
        )

    # 2. Eleccion automatica de los requisitos sin pieza.
    revisados = {e.requisito_id: e for e, _, _ in registros}
    con_pieza = {
        requisito_id
        for requisito_id, eleccion in ultimas.items()
        if eleccion.insumo_id is not None
        and eleccion.tipo_reparacion_id == detalle.tipo_reparacion_id
        and requisito_id not in revisados
    } | {r for r, e in revisados.items() if e.insumo_id is not None}
    for requisito in requisitos.del_tipo(detalle.tipo_reparacion_id):
        if requisito.id in con_pieza:
            continue
        candidatas, sin_verificar = piezas_elegibles(
            insumos, modelo, requisito.categoria_id, requisitos.categorias
        )
        if len(candidatas) != 1 or sin_verificar:
            continue
        unica = candidatas[0]
        previa = revisados.get(requisito.id) or ultimas.get(requisito.id)
        agregar(
            EleccionPieza(
                id=nuevo_id("PZA"),
                requisito_id=requisito.id,
                tipo_reparacion_id=detalle.tipo_reparacion_id,
                categoria_id=requisito.categoria_id,
                cantidad=requisito.cantidad,
                insumo_id=unica.id,
                causa=CausaEleccionPieza.AUTOMATICA,
                modelo_equipo_id=modelo,
                usuario_id=usuario_id,
                fecha=fecha,
                reemplaza_a=previa.id if previa else None,
            ),
            ACCION_ELEGIR_AUTOMATICA,
            f"{requisitos.nombre_categoria(requisito.categoria_id)} x "
            f"{requisito.cantidad}: {_texto_pieza(unica, unica.id)}, la "
            "unica pieza compatible",
        )

    if not registros:
        return orden
    nueva = orden
    for eleccion, accion, texto in registros:
        nueva = registrar_accion_funcional(
            nueva,
            accion_id=ACCION_PIEZA,
            accion=accion,
            fecha=fecha,
            usuario_id=usuario_id,
            reparacion_detail_id=detalle_id,
            observacion=texto,
        )
        buscar_detalle(nueva, detalle_id).piezas.append(eleccion)
    return nueva
