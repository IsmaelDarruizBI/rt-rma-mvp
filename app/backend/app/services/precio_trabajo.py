"""Precio de un trabajo: Tipo de Reparacion + Modelo de equipo (DEC-AJ-12).

Unica fuente de la regla. Todos los caminos que crean o redefinen un Detalle
(el trabajo inicial del ingreso, 070, 075, 127, 128 y la evaluacion
183/184, en todos los Origenes) toman el precio con ``resolver_precio``:

- «Otros» (BR-REP-047): su precio manual, origen ``OTROS``, sin cambios.
- Tipo de precio unico: el del Tipo, origen ``CATALOGO``. No admite precio
  manual (para bajarlo esta el Ajuste Comercial, BR-REP-016).
- Tipo con precio por modelo y precio para el modelo de la Orden:
  ``CATALOGO_MODELO``. Tampoco admite precio manual.
- Tipo con precio por modelo sin precio para el modelo, o equipo sin modelo
  tecnico: nunca el precio unico como respaldo (D-12.1). Con el permiso
  ``PRECIO_MANUAL``, precio y motivo: ``MANUAL``. Si no: ``PENDIENTE``, con
  precio 0, que no es un precio (punto 3 de 11.1).

Un precio ``PENDIENTE`` bloquea, en los Origenes con autorizacion del
cliente (Cliente Externo), el comprobante de ingreso y la autorizacion del
trabajo. En los no cobrables (RT_INTERNO, garantias) no bloquea. Se resuelve
con ``definir_precio``: un precio manual de quien tiene ``PRECIO_MANUAL`` o
el de catalogo, cuando Administracion lo carga. Cada definicion de precio es
una version nueva del Detalle marcada ``solo_precio``: la anterior no se
reescribe, la evaluacion tecnica sigue valiendo y la autorizacion del
cliente (que el precio pendiente impedia) se pide sobre la nueva.

Cambio de modelo (D-12.6, puntos 11 y precision d): antes de la
autorizacion del cliente, ``redeterminar_por_cambio_de_modelo`` vuelve a
resolver los trabajos con precio por modelo; un precio manual pasa al de
catalogo del modelo nuevo si existe y, si no, vuelve a quedar pendiente
(lo autorizado para otro modelo no se traslada). Despues de la
autorizacion, y en los Origenes sin autorizacion del cliente, el precio
queda como se definio y ``precio_de_otro_modelo`` lo avisa.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    TIPO_REPARACION_OTROS,
    CausaRecalculo,
    DefinicionAnteriorDetalle,
    EstadoReparacionDetail,
    OrdenReparacion,
    OrigenPrecio,
    ReparacionDetail,
    TipoReparacion,
    Usuario,
)
from app.domain.politicas import politica_de

from . import permisos
from .autorizacion import actor_valido, validar_alguno_de
from .autorizacion_cliente import EstadoAutorizacion, estado_autorizacion
from .exceptions import EntidadNoEncontradaError, PrecondicionInvalidaError
from .workflow import registrar_accion_funcional

# Accion funcional del historial: definir o volver a determinar el precio de
# un trabajo (en PostgreSQL, EV-REP-026 «Detalle redefinido»).
ACCION_PRECIO_TRABAJO = "ACC-REP-083"
ACCION_DEFINIR_PRECIO = "DEFINIR_PRECIO_TRABAJO"
ACCION_PRECIO_CAMBIO_MODELO = "REDETERMINAR_PRECIO_POR_CAMBIO_DE_MODELO"

# Los origenes cuyo precio depende del modelo del equipo.
ORIGENES_POR_MODELO = (
    OrigenPrecio.CATALOGO_MODELO,
    OrigenPrecio.MANUAL,
    OrigenPrecio.PENDIENTE,
)
_CENTAVO = Decimal("0.01")


class PrecioManualRechazadoError(PrecondicionInvalidaError):
    """El precio manual no corresponde o falta el permiso (409, con el
    codigo de una precondicion, como el resto de las reglas del precio)."""


class PrecioPendienteError(PrecondicionInvalidaError):
    """Hay trabajos con el precio pendiente de definir."""

    codigo = "PRECIO_PENDIENTE"


@dataclass(frozen=True)
class PrecioManual:
    """Precio manual pedido para un trabajo, con su motivo obligatorio."""

    precio: Decimal
    motivo: str


@dataclass(frozen=True)
class PrecioResuelto:
    """El precio de un trabajo y de donde salio (la copia del Detalle)."""

    precio: Decimal
    origen: OrigenPrecio
    modelo_equipo_id: str | None
    motivo: str | None = None
    definido_por: str | None = None
    definido_en: datetime | None = None


def modelo_de(orden: OrdenReparacion) -> str | None:
    """El modelo tecnico del equipo de la Orden (``MOD-…``), si tiene."""
    return orden.equipo.modelo_tecnico_id


def precio_de_catalogo(
    tipo: TipoReparacion, modelo_equipo_id: str | None
) -> Decimal | None:
    """El precio de catalogo de la combinacion, o ``None`` si no hay.

    Un Tipo con precio por modelo nunca devuelve su precio unico.
    """
    if not tipo.precio_por_modelo:
        return tipo.precio
    if modelo_equipo_id is None:
        return None
    return tipo.precios_modelo.get(modelo_equipo_id)


def puede_fijar_precio_manual(usuario: Usuario) -> bool:
    return actor_valido(usuario, permisos.PRECIO_MANUAL)


def _precio_valido(precio: Decimal) -> Decimal:
    if precio < 0:
        raise PrecioManualRechazadoError("El precio no puede ser negativo.")
    if precio != precio.quantize(_CENTAVO):
        raise PrecioManualRechazadoError(
            "El precio admite hasta dos decimales."
        )
    return precio


def resolver_precio(
    tipo: TipoReparacion,
    *,
    modelo_equipo_id: str | None,
    usuario: Usuario,
    fecha: datetime,
    manual: PrecioManual | None = None,
) -> PrecioResuelto:
    """El precio de ``tipo`` para el modelo, segun DEC-AJ-12 (ver modulo).

    Rechaza un precio manual que no corresponde: en «Otros» (su precio ya es
    manual), en un Tipo de precio unico, cuando hay precio de catalogo para
    la combinacion y sin el permiso ``PRECIO_MANUAL``.
    """
    base = {
        "modelo_equipo_id": modelo_equipo_id,
        "definido_por": usuario.id,
        "definido_en": fecha,
    }
    if tipo.id == TIPO_REPARACION_OTROS:
        if manual is not None:
            raise PrecioManualRechazadoError(
                "Una reparacion «Otros» lleva su propio precio: no admite "
                "ademas un precio manual con motivo."
            )
        return PrecioResuelto(
            precio=tipo.precio, origen=OrigenPrecio.OTROS, **base
        )
    catalogo = precio_de_catalogo(tipo, modelo_equipo_id)
    if not tipo.precio_por_modelo:
        if manual is not None:
            raise PrecioManualRechazadoError(
                f"«{tipo.nombre}» tiene un precio unico de catalogo: no "
                "admite un precio manual. Para bajarlo esta el ajuste "
                "comercial."
            )
        return PrecioResuelto(
            precio=catalogo, origen=OrigenPrecio.CATALOGO, **base
        )
    if catalogo is not None:
        if manual is not None:
            raise PrecioManualRechazadoError(
                f"«{tipo.nombre}» ya tiene precio de catalogo para este "
                "modelo: no admite un precio manual. Para bajarlo esta el "
                "ajuste comercial."
            )
        return PrecioResuelto(
            precio=catalogo, origen=OrigenPrecio.CATALOGO_MODELO, **base
        )
    if manual is None:
        return PrecioResuelto(
            precio=Decimal("0"), origen=OrigenPrecio.PENDIENTE, **base
        )
    if not puede_fijar_precio_manual(usuario):
        raise PrecioManualRechazadoError(
            "Fijar un precio manual cuando falta el de catalogo requiere el "
            "permiso «Autorizar un precio manual cuando falta el precio de "
            "catalogo». Sin precio, el trabajo queda con el precio "
            "pendiente de definir."
        )
    motivo = (manual.motivo or "").strip()
    if not motivo:
        raise PrecioManualRechazadoError("El precio manual exige un motivo.")
    return PrecioResuelto(
        precio=_precio_valido(manual.precio),
        origen=OrigenPrecio.MANUAL,
        motivo=motivo,
        **base,
    )


def copia_de_precio(tipo: TipoReparacion, resuelto: PrecioResuelto) -> dict:
    """Los campos de la copia del Detalle (D-12.4): nombre del Tipo, modelo,
    precio, origen, motivo y quien y cuando lo definio."""
    return {
        "precio": resuelto.precio,
        "nombre_trabajo": tipo.nombre,
        "modelo_equipo_id": resuelto.modelo_equipo_id,
        "origen_precio": resuelto.origen,
        "precio_motivo": resuelto.motivo,
        "precio_definido_por": resuelto.definido_por,
        "precio_definido_en": resuelto.definido_en,
    }


def definicion_anterior(
    detalle: ReparacionDetail, *, fecha: datetime, usuario_id: str
) -> DefinicionAnteriorDetalle:
    """La definicion vigente del Detalle, tal como queda al reemplazarla
    (BR-REP-015): con su copia de nombre, modelo y origen del precio."""
    return DefinicionAnteriorDetalle(
        tipo_reparacion_id=detalle.tipo_reparacion_id,
        precio=detalle.precio,
        puntaje=detalle.puntaje,
        garantia_dias=detalle.garantia_dias,
        reemplazada_en=fecha,
        usuario_id=usuario_id,
        nombre_trabajo=detalle.nombre_trabajo,
        modelo_equipo_id=detalle.modelo_equipo_id,
        origen_precio=detalle.origen_precio,
        precio_motivo=detalle.precio_motivo,
        precio_definido_por=detalle.precio_definido_por,
        precio_definido_en=detalle.precio_definido_en,
        solo_precio=detalle.solo_precio,
    )


# --- Precio pendiente --------------------------------------------------------


def precio_pendiente_bloquea(orden: OrdenReparacion) -> bool:
    """El precio pendiente bloquea solo donde el cliente autoriza y paga."""
    return politica_de(orden.origen).requiere_autorizacion_cliente


def detalles_con_precio_pendiente(orden: OrdenReparacion) -> list[str]:
    """Los trabajos no cancelados con el precio pendiente de definir."""
    return [
        detalle.id
        for detalle in orden.reparaciones_detail
        if detalle.precio_pendiente
        and detalle.estado is not EstadoReparacionDetail.CANCELADO
    ]


def exigir_precio_definido(
    orden: OrdenReparacion, detalle_ids: list[str] | None, accion: str
) -> None:
    """Rechaza ``accion`` si alguno de esos trabajos (todos si ``None``)
    tiene el precio pendiente, en un Origen donde eso bloquea."""
    if not precio_pendiente_bloquea(orden):
        return
    pendientes = [
        detalle_id
        for detalle_id in detalles_con_precio_pendiente(orden)
        if detalle_ids is None or detalle_id in detalle_ids
    ]
    if pendientes:
        raise PrecioPendienteError(
            f"No se puede {accion}: falta definir el precio de "
            f"{', '.join(pendientes)} («Precio pendiente de definir»)."
        )


def roles_para_tomar_precio_de_catalogo():
    """Quien puede tomar el precio de catalogo de un trabajo pendiente:
    quien puede editar los trabajos (Recepcion o el tecnico que los
    define), quien gestiona la autorizacion del cliente y quien tiene
    ``PRECIO_MANUAL``. No fija ningun importe: lo toma del catalogo."""
    return tuple(
        dict.fromkeys(
            [
                *permisos.DETALLE_DEFINIR_RECEPCION,
                *permisos.DETALLE_DEFINIR_TECNICO,
                *permisos.DECISION_CLIENTE,
                *permisos.PRECIO_MANUAL,
            ]
        )
    )


def _detalle(orden: OrdenReparacion, detalle_id: str) -> ReparacionDetail:
    detalle = next(
        (d for d in orden.reparaciones_detail if d.id == detalle_id), None
    )
    if detalle is None:
        raise EntidadNoEncontradaError(
            f"La Orden {orden.id} no tiene el Detalle {detalle_id}."
        )
    return detalle


def _nueva_version_de_precio(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    tipo: TipoReparacion,
    resuelto: PrecioResuelto,
    usuario_id: str,
    fecha: datetime,
) -> None:
    """Agrega una version del Detalle que solo cambia el precio (en sitio,
    sobre una copia de la Orden). El nombre del trabajo es el de su
    definicion; un Detalle anterior sin copia toma el del catalogo."""
    detalle = _detalle(orden, detalle_id)
    nombre = detalle.nombre_trabajo or tipo.nombre
    detalle.definiciones_anteriores.append(
        definicion_anterior(detalle, fecha=fecha, usuario_id=usuario_id)
    )
    for campo, valor in copia_de_precio(tipo, resuelto).items():
        setattr(detalle, campo, valor)
    detalle.nombre_trabajo = nombre
    detalle.solo_precio = True


def _observacion(anterior: ReparacionDetail, resuelto: PrecioResuelto) -> str:
    texto = (
        f"Precio {_origen_texto(anterior)} -> "
        f"{resuelto.origen.value} {resuelto.precio}"
    )
    if resuelto.motivo:
        texto += f": {resuelto.motivo}"
    return texto


def _origen_texto(detalle: ReparacionDetail) -> str:
    if detalle.precio_pendiente:
        return "PENDIENTE"
    origen = detalle.origen_precio.value if detalle.origen_precio else ""
    return f"{origen} {detalle.precio}".strip()


def definir_precio(
    orden: OrdenReparacion,
    *,
    detalle_id: str,
    tipo: TipoReparacion | None,
    usuario: Usuario,
    fecha: datetime,
    manual: PrecioManual | None = None,
) -> OrdenReparacion:
    """«Definir precio» de un trabajo con el precio pendiente.

    Sin ``manual`` toma el precio de catalogo, que tiene que existir ahora
    para el modelo de la Orden. Con ``manual``, el precio autorizado por
    quien tiene ``PRECIO_MANUAL``, con motivo (se rechaza si ya hay precio
    de catalogo). Agrega una version ``solo_precio`` y el paso del
    historial; nunca cambia el catalogo.
    """
    from .descuentos import registrar_recalculos

    detalle = _detalle(orden, detalle_id)
    if tipo is None:
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} no tiene un Tipo del catalogo."
        )
    if detalle.estado is EstadoReparacionDetail.CANCELADO:
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} esta CANCELADO."
        )
    if not detalle.precio_pendiente:
        raise PrecondicionInvalidaError(
            f"El Detalle {detalle_id} ya tiene precio: un precio definido "
            "se cambia redefiniendo el trabajo o con un ajuste comercial."
        )
    if tipo.id != detalle.tipo_reparacion_id:
        raise PrecondicionInvalidaError(
            "El Tipo no es el del trabajo: el precio se define para su Tipo."
        )
    if manual is None:
        validar_alguno_de(usuario, roles_para_tomar_precio_de_catalogo())
    else:
        validar_alguno_de(usuario, permisos.PRECIO_MANUAL)
    resuelto = resolver_precio(
        tipo,
        modelo_equipo_id=modelo_de(orden),
        usuario=usuario,
        fecha=fecha,
        manual=manual,
    )
    if resuelto.origen is OrigenPrecio.PENDIENTE:
        raise PrecondicionInvalidaError(
            f"«{tipo.nombre}» todavia no tiene precio de catalogo para el "
            "modelo de la Orden: falta que Administracion lo cargue o un "
            "precio manual autorizado."
        )
    nueva = registrar_accion_funcional(
        orden,
        accion_id=ACCION_PRECIO_TRABAJO,
        accion=ACCION_DEFINIR_PRECIO,
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion=_observacion(detalle, resuelto),
    )
    _nueva_version_de_precio(
        nueva,
        detalle_id=detalle_id,
        tipo=tipo,
        resuelto=resuelto,
        usuario_id=usuario.id,
        fecha=fecha,
    )
    return registrar_recalculos(
        orden,
        nueva,
        causa=CausaRecalculo.REDEFINICION,
        usuario_id=usuario.id,
        fecha=fecha,
    )


# --- Cambio de modelo (D-12.6) -----------------------------------------------


def _depende_del_modelo(detalle: ReparacionDetail) -> bool:
    return (
        detalle.estado is not EstadoReparacionDetail.CANCELADO
        and detalle.origen_precio in ORIGENES_POR_MODELO
    )


def redeterminar_por_cambio_de_modelo(
    orden: OrdenReparacion,
    *,
    tipos: Mapping[str, TipoReparacion],
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """Antes de la autorizacion del cliente, vuelve a determinar el precio
    de los trabajos con precio por modelo para el modelo actual de la Orden.

    Solo en los Origenes con autorizacion del cliente y en los trabajos que
    todavia la esperan; el resto conserva su precio (y lo avisa
    ``precio_de_otro_modelo``). Un precio manual no se traslada: toma el de
    catalogo del modelo nuevo o vuelve a quedar pendiente. Cada cambio es
    una version ``solo_precio`` con su paso en el historial.
    """
    from .descuentos import registrar_recalculos

    if not precio_pendiente_bloquea(orden):
        return orden
    modelo = modelo_de(orden)
    nueva = orden
    for detalle in orden.reparaciones_detail:
        if not _depende_del_modelo(detalle):
            continue
        if detalle.modelo_equipo_id == modelo:
            continue
        if estado_autorizacion(orden, detalle) is not (
            EstadoAutorizacion.PENDIENTE
        ):
            continue
        tipo = tipos.get(detalle.tipo_reparacion_id)
        if tipo is None:
            continue
        resuelto = resolver_precio(
            tipo, modelo_equipo_id=modelo, usuario=usuario, fecha=fecha
        )
        nueva = registrar_accion_funcional(
            nueva,
            accion_id=ACCION_PRECIO_TRABAJO,
            accion=ACCION_PRECIO_CAMBIO_MODELO,
            fecha=fecha,
            usuario_id=usuario.id,
            reparacion_detail_id=detalle.id,
            observacion="Cambio de modelo: " + _observacion(detalle, resuelto),
        )
        _nueva_version_de_precio(
            nueva,
            detalle_id=detalle.id,
            tipo=tipo,
            resuelto=resuelto,
            usuario_id=usuario.id,
            fecha=fecha,
        )
    if nueva is orden:
        return orden
    return registrar_recalculos(
        orden,
        nueva,
        causa=CausaRecalculo.REDEFINICION,
        usuario_id=usuario.id,
        fecha=fecha,
    )


def precio_de_otro_modelo(
    orden: OrdenReparacion, detalle: ReparacionDetail
) -> bool:
    """El precio del trabajo se determino para otro modelo del equipo (se
    conserva: lo autorizo el cliente o su Origen no lo pide). Se corrige
    redefiniendo el trabajo (127)."""
    return (
        detalle.estado is not EstadoReparacionDetail.CANCELADO
        and detalle.origen_precio
        in (OrigenPrecio.CATALOGO_MODELO, OrigenPrecio.MANUAL)
        and detalle.modelo_equipo_id != modelo_de(orden)
    )


def detalles_con_precio_de_otro_modelo(orden: OrdenReparacion) -> list[str]:
    return [
        detalle.id
        for detalle in orden.reparaciones_detail
        if precio_de_otro_modelo(orden, detalle)
    ]


def definiciones_tecnicas_iguales_desde(detalle: ReparacionDetail) -> int:
    """La primera version cuya definicion tecnica sigue vigente: las
    versiones ``solo_precio`` no cambian el trabajo, asi que la evaluacion
    tecnica de una anterior sigue valiendo (BR-REP-035)."""
    marcas = [d.solo_precio for d in detalle.definiciones_anteriores] + [
        detalle.solo_precio
    ]
    version = detalle.version_definicion
    while version > 1 and marcas[version - 1]:
        version -= 1
    return version
