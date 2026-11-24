"""Reglas de Compras (DEC-MI-09).

Ninguna compra es automatica: una sugerencia por faltante se convierte en
solicitud solo si alguien la confirma. Las Ordenes de compra no se
aprueban: se crean y se confirman (quien y cuando). Las recepciones nunca
superan lo pendiente; el ingreso de stock de cada linea lo arma el
llamador con el inventario (lote o serie si el insumo lo exige).
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    CambioConfiguracion,
    EntidadConfiguracion,
    Insumo,
    Usuario,
)
from app.domain.models.compras import (
    CostoCompra,
    EstadoOrdenCompra,
    EstadoSolicitud,
    ItemOrdenCompra,
    LineaRecepcion,
    OrdenCompra,
    OrigenSolicitud,
    Proveedor,
    RecepcionCompra,
    SolicitudCompra,
    SugerenciaCompra,
)
from app.domain.models.lotes import ControlInsumo

from . import permisos
from .autorizacion import validar_alguno_de
from .configuracion import texto
from .exceptions import PrecondicionInvalidaError
from .stock_minimo import cantidad_a_reponer

CERO = Decimal("0")
CAMPOS_PROVEEDOR = (
    "nombre",
    "cuit",
    "telefono",
    "email",
    "contacto",
    "activo",
)


def _texto(valor: str | None) -> str | None:
    valor = (valor or "").strip()
    return valor or None


# --- Proveedores -------------------------------------------------------------


def cambios_de_proveedor(
    anterior: Proveedor | None,
    nuevo: Proveedor,
    *,
    usuario: Usuario,
    fecha: datetime,
) -> list[CambioConfiguracion]:
    validar_alguno_de(usuario, permisos.PROVEEDOR_GESTIONAR)
    cambios = [
        CambioConfiguracion(
            entidad=EntidadConfiguracion.PROVEEDOR,
            clave=nuevo.id,
            campo=campo,
            valor_anterior=(
                texto(getattr(anterior, campo)) if anterior else None
            ),
            valor_nuevo=texto(getattr(nuevo, campo)),
            usuario_id=usuario.id,
            fecha=fecha,
        )
        for campo in CAMPOS_PROVEEDOR
        if (anterior is None and getattr(nuevo, campo) is not None)
        or (
            anterior is not None
            and texto(getattr(anterior, campo)) != texto(getattr(nuevo, campo))
        )
    ]
    if not cambios:
        raise PrecondicionInvalidaError(
            f"El proveedor {nuevo.id} ya tiene esos valores: no hay cambios."
        )
    return cambios


# --- Solicitudes -------------------------------------------------------------


def nueva_solicitud(
    *,
    solicitud_id: str,
    insumo: Insumo,
    cantidad: Decimal,
    motivo: str,
    origen: OrigenSolicitud,
    ordenes: Sequence[str],
    usuario: Usuario,
    fecha: datetime,
) -> SolicitudCompra:
    validar_alguno_de(usuario, permisos.COMPRA_SOLICITAR)
    if not insumo.activo:
        raise PrecondicionInvalidaError(
            f"El insumo {insumo.id} no esta vigente: no se compra."
        )
    if cantidad <= CERO:
        raise PrecondicionInvalidaError("La cantidad es mayor que cero.")
    motivo = _texto(motivo)
    if motivo is None:
        raise PrecondicionInvalidaError("La solicitud exige un motivo.")
    return SolicitudCompra(
        id=solicitud_id,
        insumo_id=insumo.id,
        cantidad=cantidad,
        origen=origen,
        motivo=motivo,
        ordenes=sorted(set(ordenes)),
        usuario_id=usuario.id,
        fecha=fecha,
    )


def descartar_solicitud(
    solicitud: SolicitudCompra,
    *,
    motivo: str,
    usuario: Usuario,
    fecha: datetime,
) -> SolicitudCompra:
    validar_alguno_de(usuario, permisos.COMPRA_SOLICITAR)
    if solicitud.estado is not EstadoSolicitud.PENDIENTE:
        raise PrecondicionInvalidaError(
            f"La solicitud {solicitud.id} ya no esta pendiente."
        )
    motivo = _texto(motivo)
    if motivo is None:
        raise PrecondicionInvalidaError("Descartar exige un motivo.")
    return solicitud.model_copy(
        update={
            "estado": EstadoSolicitud.DESCARTADA,
            "descartada_por": usuario.id,
            "descartada_en": fecha,
            "motivo_descarte": motivo,
        }
    )


def sugerencias(
    *,
    disponibles: Mapping[str, Decimal],
    demanda: Mapping[str, tuple[Decimal, list[str]]],
    en_camino: Mapping[str, Decimal],
    minimos: Mapping[str, Decimal] | None = None,
) -> list[SugerenciaCompra]:
    """Por insumo con faltante o bajo su minimo (DEC-AJ-11).

    - Sin minimo: lo que piden los Detalles bloqueados por recursos menos
      lo disponible y lo que ya esta en camino (como siempre).
    - Con minimo: ``demanda + minimo - disponible - en camino``, es decir,
      cubrir la demanda y reponer hasta el minimo.

    ``minimos`` trae solo los insumos vigentes con minimo. Lo que esta en
    camino (solicitudes pendientes y Ordenes de compra abiertas) se
    descuenta, asi una sugerencia ya pedida no vuelve a aparecer.
    """
    minimos = minimos or {}
    candidatos = (
        set(demanda)
        | {i for i, d in disponibles.items() if d < 0}
        | {
            i
            for i, minimo in minimos.items()
            if disponibles.get(i, CERO) < minimo
        }
    )
    resultado = []
    for insumo_id in sorted(candidatos):
        requerido, ordenes = demanda.get(insumo_id, (CERO, []))
        disponible = disponibles.get(insumo_id, CERO)
        camino = en_camino.get(insumo_id, CERO)
        minimo = minimos.get(insumo_id)
        por_faltante, por_minimo = cantidad_a_reponer(
            stock_minimo=minimo,
            demanda=requerido,
            disponible=disponible,
            en_camino=camino,
        )
        sugerido = por_faltante + por_minimo
        if sugerido <= CERO:
            continue
        resultado.append(
            SugerenciaCompra(
                insumo_id=insumo_id,
                disponible=disponible,
                demanda_bloqueada=requerido,
                en_camino=camino,
                sugerido=sugerido,
                ordenes=sorted(set(ordenes)),
                stock_minimo=minimo,
                por_faltante=por_faltante,
                por_minimo=por_minimo,
                motivo=(
                    OrigenSolicitud.STOCK_MINIMO
                    if por_minimo > CERO
                    else OrigenSolicitud.FALTANTE
                ),
            )
        )
    return resultado


# --- Ordenes de compra -------------------------------------------------------


def nueva_orden_compra(
    *,
    orden_compra_id: str,
    proveedor: Proveedor,
    items: Sequence[ItemOrdenCompra],
    solicitudes: Sequence[SolicitudCompra],
    insumos: Mapping[str, Insumo],
    observaciones: str | None,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenCompra:
    validar_alguno_de(usuario, permisos.OC_CREAR)
    if not proveedor.activo:
        raise PrecondicionInvalidaError(
            f"El proveedor {proveedor.nombre} no esta vigente."
        )
    if not items:
        raise PrecondicionInvalidaError(
            "La orden de compra necesita al menos un insumo."
        )
    vistos: set[str] = set()
    for item in items:
        insumo = insumos.get(item.insumo_id)
        if insumo is None:
            raise PrecondicionInvalidaError(
                f"No existe el insumo {item.insumo_id}."
            )
        if not insumo.activo:
            raise PrecondicionInvalidaError(
                f"El insumo {insumo.id} no esta vigente: no se compra."
            )
        if item.insumo_id in vistos:
            raise PrecondicionInvalidaError(
                f"El insumo {item.insumo_id} esta dos veces: una linea por "
                "insumo."
            )
        vistos.add(item.insumo_id)
    for solicitud in solicitudes:
        if solicitud.estado is not EstadoSolicitud.PENDIENTE:
            raise PrecondicionInvalidaError(
                f"La solicitud {solicitud.id} ya no esta pendiente."
            )
        if solicitud.insumo_id not in vistos:
            raise PrecondicionInvalidaError(
                f"La solicitud {solicitud.id} es de {solicitud.insumo_id}, "
                "que la orden de compra no incluye."
            )
    return OrdenCompra(
        id=orden_compra_id,
        proveedor_id=proveedor.id,
        items=list(items),
        solicitudes=[s.id for s in solicitudes],
        creada_por=usuario.id,
        creada_en=fecha,
        observaciones=_texto(observaciones),
    )


def confirmar_orden_compra(
    orden: OrdenCompra, *, usuario: Usuario, fecha: datetime
) -> OrdenCompra:
    """Sin aprobacion: confirmar registra quien y cuando, y la deja lista
    para recibir."""
    validar_alguno_de(usuario, permisos.OC_CONFIRMAR)
    if orden.estado is not EstadoOrdenCompra.BORRADOR:
        raise PrecondicionInvalidaError(
            f"La orden de compra {orden.id} ya no es un borrador."
        )
    return orden.model_copy(
        update={"confirmada_por": usuario.id, "confirmada_en": fecha}
    )


def cancelar_orden_compra(
    orden: OrdenCompra, *, motivo: str, usuario: Usuario, fecha: datetime
) -> OrdenCompra:
    """DF-5: cancelar una OC confirmada (o un borrador ajeno) exige
    ``OC_CANCELAR``; quien puede crear OC descarta su propio borrador."""
    propio = (
        orden.estado is EstadoOrdenCompra.BORRADOR
        and orden.creada_por == usuario.id
    )
    validar_alguno_de(
        usuario,
        tuple(dict.fromkeys((*permisos.OC_CANCELAR, *permisos.OC_CREAR)))
        if propio
        else permisos.OC_CANCELAR,
    )
    if orden.estado not in (
        EstadoOrdenCompra.BORRADOR,
        EstadoOrdenCompra.CONFIRMADA,
    ):
        raise PrecondicionInvalidaError(
            "Solo se cancela una orden de compra sin recepciones."
        )
    motivo = _texto(motivo)
    if motivo is None:
        raise PrecondicionInvalidaError("Cancelar exige un motivo.")
    return orden.model_copy(
        update={
            "cancelada_por": usuario.id,
            "cancelada_en": fecha,
            "motivo_cancelacion": motivo,
        }
    )


def nueva_recepcion(
    orden: OrdenCompra,
    *,
    recepcion_id: str,
    lineas: Sequence[LineaRecepcion],
    insumos: Mapping[str, Insumo],
    remito: str | None,
    observaciones: str | None,
    usuario: Usuario,
    fecha: datetime,
) -> RecepcionCompra:
    """Una recepcion parcial o total; los movimientos los agrega el
    llamador al registrar los ingresos."""
    validar_alguno_de(usuario, permisos.COMPRA_RECIBIR)
    if orden.estado not in (
        EstadoOrdenCompra.CONFIRMADA,
        EstadoOrdenCompra.PARCIAL,
    ):
        raise PrecondicionInvalidaError(
            f"La orden de compra {orden.id} no espera recepciones "
            f"({orden.estado.value})."
        )
    if not lineas:
        raise PrecondicionInvalidaError("La recepcion no tiene lineas.")
    remito = _texto(remito)
    if remito and any(
        (r.remito or "").lower() == remito.lower() for r in orden.recepciones
    ):
        raise PrecondicionInvalidaError(
            f"El remito {remito} ya se recibio en {orden.id}: no se recibe "
            "dos veces."
        )
    recibidas: dict[str, Decimal] = {}
    normalizadas = []
    for linea in lineas:
        if orden.pedido(linea.insumo_id) == CERO:
            raise PrecondicionInvalidaError(
                f"{linea.insumo_id} no esta en la orden de compra {orden.id}."
            )
        recibidas[linea.insumo_id] = (
            recibidas.get(linea.insumo_id, CERO) + linea.cantidad
        )
        insumo = insumos[linea.insumo_id]
        lote = _texto(linea.lote)
        series = [s.strip() for s in linea.series if s.strip()]
        if insumo.control is ControlInsumo.SERIE:
            if len(series) != linea.cantidad or len(set(series)) != len(
                series
            ):
                raise PrecondicionInvalidaError(
                    f"{insumo.id} se controla por serie: un numero de serie "
                    f"distinto por unidad ({linea.cantidad})."
                )
            lote = None
        elif insumo.control is ControlInsumo.LOTE:
            if lote is None:
                raise PrecondicionInvalidaError(
                    f"{insumo.id} se controla por lote: indica el lote."
                )
            series = []
        else:
            lote, series = None, []
        acordado = next(
            i.costo_unitario for i in orden.items if i.insumo_id == insumo.id
        )
        diferencia = _texto(linea.diferencia)
        if linea.costo_unitario != acordado and diferencia is None:
            diferencia = (
                f"Costo real {linea.costo_unitario}, acordado {acordado}."
            )
        normalizadas.append(
            linea.model_copy(
                update={
                    "lote": lote,
                    "series": series,
                    "diferencia": diferencia,
                    "movimientos": [],
                }
            )
        )
    for insumo_id, cantidad in recibidas.items():
        if cantidad > orden.pendiente(insumo_id):
            raise PrecondicionInvalidaError(
                f"De {insumo_id} quedan {orden.pendiente(insumo_id)} "
                f"pendientes: no se reciben {cantidad}."
            )
    return RecepcionCompra(
        id=recepcion_id,
        usuario_id=usuario.id,
        fecha=fecha,
        remito=remito,
        lineas=normalizadas,
        observaciones=_texto(observaciones),
    )


def costos(
    ordenes: Iterable[OrdenCompra], insumo_id: str | None = None
) -> list[CostoCompra]:
    """Costos historicos (uno por linea de recepcion), del mas reciente al
    mas antiguo. El primero es el ultimo costo de compra."""
    resultado = [
        CostoCompra(
            insumo_id=linea.insumo_id,
            orden_compra_id=orden.id,
            recepcion_id=recepcion.id,
            proveedor_id=orden.proveedor_id,
            cantidad=linea.cantidad,
            costo_unitario=linea.costo_unitario,
            fecha=recepcion.fecha,
        )
        for orden in ordenes
        for recepcion in orden.recepciones
        for linea in recepcion.lineas
        if insumo_id is None or linea.insumo_id == insumo_id
    ]
    return sorted(resultado, key=lambda c: c.fecha, reverse=True)


def en_camino(
    ordenes: Iterable[OrdenCompra], solicitudes: Iterable[SolicitudCompra]
) -> dict[str, Decimal]:
    """Lo pedido y no recibido mas las solicitudes pendientes.

    Cuenta lo que falta recibir de las ordenes de compra en borrador,
    confirmadas o parciales, y las solicitudes PENDIENTE (las EN_ORDEN ya
    estan en su orden de compra). Es tambien la «reposicion solicitada» del
    stock minimo (DEC-AJ-11, punto 7 de 11.1)."""
    total: dict[str, Decimal] = {}
    for orden in ordenes:
        if orden.estado in (
            EstadoOrdenCompra.CONFIRMADA,
            EstadoOrdenCompra.PARCIAL,
            EstadoOrdenCompra.BORRADOR,
        ):
            for item in orden.items:
                total[item.insumo_id] = total.get(item.insumo_id, CERO) + max(
                    orden.pendiente(item.insumo_id), CERO
                )
    for solicitud in solicitudes:
        if solicitud.estado is EstadoSolicitud.PENDIENTE:
            total[solicitud.insumo_id] = (
                total.get(solicitud.insumo_id, CERO) + solicitud.cantidad
            )
    return total
