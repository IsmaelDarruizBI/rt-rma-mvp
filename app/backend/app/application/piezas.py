"""Requisitos de insumo y pieza elegida de cada trabajo (DEC-AJ-14, D-14.4).

    requisitos_de_insumo   los requisitos de los Tipos y las categorias
    conciliar              eleccion automatica y revision tras definir,
                           redefinir, cambiar el modelo o iniciar
    elegir_pieza           «Elegir pieza» / «Sustituir» (PIEZA_ELEGIR)
    piezas_por_detalle     lectura: requisitos y pieza de cada Detalle
    opciones_de_pieza      lectura: las piezas elegibles de un requisito

Las reglas viven en ``services.piezas``.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    CausaEleccionPieza,
    EstadoReparacionDetail,
    Insumo,
    OrdenReparacion,
)
from app.services import cargar_reservas_externas
from app.services.clasificacion_insumos import compatible
from app.services.exceptions import EntidadNoEncontradaError
from app.services.inventario import piezas_vigentes, stock_disponible
from app.services.piezas import (
    SIN_REQUISITOS,
    RequisitosInsumo,
    conciliar_piezas,
    eleccion_consistente,
    modelo_de,
    pieza_consumida,
    piezas_elegibles,
    requisitos_pendientes,
    reservas_pendientes_de,
)
from app.services.piezas import elegir_pieza as elegir_pieza_servicio
from app.services.tomas import buscar_detalle

from .contexto import ApplicationContext
from .modificacion import orden_para_modificar

CERO = Decimal("0")


def requisitos_de_insumo(contexto: ApplicationContext) -> RequisitosInsumo:
    """Los requisitos de todos los Tipos y, si hay alguno, las categorias
    (para incluir las subcategorias y nombrarlas). Sin requisitos,
    ``SIN_REQUISITOS``: todo como antes."""
    requisitos = tuple(contexto.catalogos.listar_tipo_reparacion_requisitos())
    if not requisitos:
        return SIN_REQUISITOS
    return RequisitosInsumo(
        requisitos=requisitos,
        categorias=tuple(contexto.operativa.listar_categorias_insumo()),
    )


def conciliar(
    contexto: ApplicationContext,
    orden: OrdenReparacion,
    *,
    usuario_id: str,
    fecha: datetime,
    requisitos: RequisitosInsumo | None = None,
    detalle_ids: Iterable[str] | None = None,
) -> OrdenReparacion:
    """Eleccion automatica y revision de las piezas de los Detalles
    pendientes (``services.piezas.conciliar_piezas``), dentro de la
    transaccion del comando. Sin requisitos ni piezas no lee nada mas."""
    requisitos = requisitos or requisitos_de_insumo(contexto)
    if not requisitos.requisitos and not any(
        detalle.piezas for detalle in orden.reparaciones_detail
    ):
        return orden
    return conciliar_piezas(
        orden,
        requisitos=requisitos,
        insumos=contexto.catalogos.listar_insumos(),
        usuario_id=usuario_id,
        fecha=fecha,
        detalle_ids=detalle_ids,
    )


def elegir_pieza(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    detalle_id: str,
    requisito_id: str,
    insumo_id: str,
    usuario_id: str,
    motivo: str | None = None,
) -> OrdenReparacion:
    """Elegir o sustituir la pieza de un requisito del trabajo.

    Con la pieza ya reservada (Detalle EN_PROGRESO), la liberacion y la
    reserva nueva se calculan y se guardan en la misma transaccion, con la
    Orden y los dos insumos bloqueados (DI-2): nadie toma la misma
    disponibilidad en el medio y el libro rechaza un disponible negativo.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with orden_para_modificar(contexto, orden_id) as orden:
        detalle = buscar_detalle(orden, detalle_id)
        requisitos = requisitos_de_insumo(contexto)
        externas = None
        if detalle.estado is EstadoReparacionDetail.EN_PROGRESO:
            anterior = piezas_vigentes(detalle).get(requisito_id)
            contexto.catalogos.bloquear_insumos(
                {insumo_id} | ({anterior.insumo_id} if anterior else set())
            )
            externas = cargar_reservas_externas(orden.id, contexto.ordenes)
        orden = elegir_pieza_servicio(
            orden,
            detalle_id=detalle_id,
            requisito_id=requisito_id,
            insumo_id=insumo_id,
            usuario=usuario,
            insumos=contexto.catalogos.listar_insumos(),
            requisitos=requisitos,
            fecha=fecha,
            motivo=motivo,
            reservas_externas=externas,
        )
        contexto.ordenes.guardar(orden)
    return orden


# --- Lectura ----------------------------------------------------------------


@dataclass(frozen=True)
class PiezaDelRequisito:
    """Un requisito del Tipo de un Detalle y su pieza (presentacion).

    ``estado``: ``ELEGIDA`` o ``PENDIENTE`` («Pendiente de elegir»).
    ``compatible_con_modelo``: la pieza sigue sirviendo para el modelo
    actual del equipo (si no, se sustituye). ``reservada``: tiene reserva
    pendiente en el Detalle; ``consumida``: ya se consumio (no se
    sustituye). ``requisito_vigente``: el Tipo lo sigue pidiendo (una
    eleccion de un requisito retirado se conserva).
    """

    requisito_id: str
    categoria_id: str
    categoria_nombre: str
    cantidad: Decimal
    estado: str
    requisito_vigente: bool
    insumo_id: str | None = None
    insumo_codigo: str | None = None
    insumo_nombre: str | None = None
    causa: CausaEleccionPieza | None = None
    compatibilidad_no_verificada: bool = False
    compatible_con_modelo: bool = True
    reservada: bool = False
    consumida: bool = False
    motivo: str | None = None
    elegida_por: str | None = None
    elegida_en: datetime | None = None


def piezas_de(
    orden: OrdenReparacion,
    *,
    requisitos: RequisitosInsumo,
    insumos: Iterable[Insumo],
) -> dict[str, list[PiezaDelRequisito]]:
    """Por Detalle: cada requisito vigente de su Tipo (con su pieza o
    pendiente) y cada pieza elegida de un requisito ya retirado."""
    por_id = {insumo.id: insumo for insumo in insumos}
    modelo = modelo_de(orden)
    resultado: dict[str, list[PiezaDelRequisito]] = {}
    for detalle in orden.reparaciones_detail:
        vigentes = piezas_vigentes(detalle)
        filas: list[PiezaDelRequisito] = []
        del_tipo = requisitos.del_tipo(detalle.tipo_reparacion_id)
        ids_del_tipo = {r.id for r in del_tipo}
        for requisito in del_tipo:
            eleccion = vigentes.get(requisito.id)
            if eleccion is None:
                filas.append(
                    PiezaDelRequisito(
                        requisito_id=requisito.id,
                        categoria_id=requisito.categoria_id,
                        categoria_nombre=requisitos.nombre_categoria(
                            requisito.categoria_id
                        ),
                        cantidad=requisito.cantidad,
                        estado="PENDIENTE",
                        requisito_vigente=True,
                    )
                )
        for requisito_id, eleccion in vigentes.items():
            insumo = por_id.get(eleccion.insumo_id or "")
            filas.append(
                PiezaDelRequisito(
                    requisito_id=requisito_id,
                    categoria_id=eleccion.categoria_id,
                    categoria_nombre=requisitos.nombre_categoria(
                        eleccion.categoria_id
                    ),
                    cantidad=eleccion.cantidad,
                    estado="ELEGIDA",
                    requisito_vigente=requisito_id in ids_del_tipo,
                    insumo_id=eleccion.insumo_id,
                    insumo_codigo=insumo.codigo if insumo else None,
                    insumo_nombre=insumo.nombre if insumo else None,
                    causa=eleccion.causa,
                    compatibilidad_no_verificada=(
                        eleccion.compatibilidad_no_verificada
                    ),
                    compatible_con_modelo=eleccion_consistente(
                        eleccion, insumo, modelo
                    ),
                    reservada=bool(
                        reservas_pendientes_de(
                            orden, detalle.id, eleccion.insumo_id or ""
                        )
                    ),
                    consumida=pieza_consumida(
                        orden, detalle.id, eleccion.insumo_id or ""
                    ),
                    motivo=eleccion.motivo,
                    elegida_por=eleccion.usuario_id,
                    elegida_en=eleccion.fecha,
                )
            )
        orden_requisitos = {r.id: i for i, r in enumerate(del_tipo)}
        filas.sort(
            key=lambda f: orden_requisitos.get(f.requisito_id, len(del_tipo))
        )
        if filas:
            resultado[detalle.id] = filas
    return resultado


def piezas_por_detalle(
    contexto: ApplicationContext, orden: OrdenReparacion
) -> dict[str, list[PiezaDelRequisito]]:
    """Lectura de la Orden: sin requisitos ni piezas, vacio (sin leer los
    insumos)."""
    requisitos = requisitos_de_insumo(contexto)
    if not requisitos.requisitos and not any(
        detalle.piezas for detalle in orden.reparaciones_detail
    ):
        return {}
    return piezas_de(
        orden,
        requisitos=requisitos,
        insumos=contexto.catalogos.listar_insumos(),
    )


@dataclass(frozen=True)
class OpcionDePieza:
    """Una pieza elegible para un requisito, con su disponible (fisico
    menos lo reservado por todas las Ordenes, incluida esta)."""

    insumo: Insumo
    disponible: Decimal
    compatibilidad_no_verificada: bool
    elegida: bool


@dataclass(frozen=True)
class OpcionesDePieza:
    requisito_id: str
    categoria_id: str
    categoria_nombre: str
    cantidad: Decimal
    modelo_equipo_id: str | None
    compatibilidad_no_verificada: bool
    opciones: list[OpcionDePieza]


def opciones_de_pieza(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    detalle_id: str,
    requisito_id: str,
) -> OpcionesDePieza:
    """Las piezas que se pueden elegir para un requisito del trabajo: las
    compatibles con el modelo del equipo (sin modelo tecnico, las
    universales o, si no hay, cualquiera de la categoria sin verificar)."""
    with contexto.lectura():
        orden = contexto.ordenes.obtener(orden_id)
        detalle = buscar_detalle(orden, detalle_id)
        requisitos = requisitos_de_insumo(contexto)
        requisito = requisitos.buscar(requisito_id)
        if requisito is None or (
            requisito.tipo_reparacion_id != detalle.tipo_reparacion_id
        ):
            raise EntidadNoEncontradaError(
                f"El Detalle {detalle_id} no tiene el requisito "
                f"{requisito_id}."
            )
        insumos = contexto.catalogos.listar_insumos()
        externas = cargar_reservas_externas(orden.id, contexto.ordenes)
    vigente = piezas_vigentes(detalle).get(requisito_id)
    categoria = vigente.categoria_id if vigente else requisito.categoria_id
    modelo = modelo_de(orden)
    elegibles, sin_verificar = piezas_elegibles(
        insumos, modelo, categoria, requisitos.categorias
    )
    return OpcionesDePieza(
        requisito_id=requisito_id,
        categoria_id=categoria,
        categoria_nombre=requisitos.nombre_categoria(categoria),
        cantidad=vigente.cantidad if vigente else requisito.cantidad,
        modelo_equipo_id=modelo,
        compatibilidad_no_verificada=sin_verificar,
        opciones=[
            OpcionDePieza(
                insumo=insumo,
                disponible=stock_disponible(
                    insumo,
                    orden.movimientos_insumo,
                    externas.get(insumo.id, CERO),
                ),
                compatibilidad_no_verificada=sin_verificar
                and not compatible(insumo, modelo),
                elegida=vigente is not None and vigente.insumo_id == insumo.id,
            )
            for insumo in elegibles
        ],
    )


__all__ = [
    "OpcionDePieza",
    "OpcionesDePieza",
    "PiezaDelRequisito",
    "conciliar",
    "elegir_pieza",
    "opciones_de_pieza",
    "piezas_de",
    "piezas_por_detalle",
    "requisitos_de_insumo",
    "requisitos_pendientes",
]
