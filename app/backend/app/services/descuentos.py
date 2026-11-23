"""Ajuste Comercial sobre los trabajos de una Orden (BR-REP-016, DEC-AJ-10).

Recepcion, Coordinacion RMA o Administracion aplica, cambia o quita un
DESCUENTO o una CORTESIA, porcentual o de importe fijo, con su motivo, de la
Orden o de un trabajo. El precio snapshot de cada Detalle y el catalogo no
cambian: el ajuste es un concepto aparte y el total se deriva. Cada registro
queda en la Orden con quien, cuando, por que y la evidencia de sus importes
(precio original, importe aplicado y precio final, D-10.4), y cada operacion
va al historial de la Orden (EV-REP-041).

Permisos (D-10.1): cada clase tiene el suyo (``DESCUENTO`` y ``CORTESIA``).
Cambiar o quitar un ajuste vigente exige el permiso de la clase que se
reemplaza y el de la nueva: el permiso del DESCUENTO no modifica una
CORTESIA.

Reversion y correccion (D-10.2): con ``AJUSTE_REVERTIR`` (por defecto solo
Administracion) se revierte el ajuste vigente de un destino; vuelve a regir
el registro anterior no revertido. Corregir es revertir y registrar el
correcto en la misma operacion, enlazados con ``corrige_a``; exige ademas
el permiso de la clase nueva. Nunca despues de la entrega (D-10.3), nunca
sobre una Orden cancelada, y nunca tocando pagos ni devoluciones.

Con pagos registrados, un ajuste que deja el total por debajo de lo ya
cobrado deja saldo a favor del cliente, que se devuelve antes de entregar
(DC11, BR-REP-038, DEC-MI-03); la condicion de entrega ya lo exige
(``saldo == 0``).
"""

from datetime import datetime
from decimal import Decimal

from app.domain.models import (
    CausaRecalculo,
    ClaseAjuste,
    EstadoReparacionDetail,
    EstadoWorkflow,
    OrdenReparacion,
    RecalculoAjuste,
    RegistroDescuento,
    ReversionAjuste,
    TipoDescuento,
    Usuario,
    importe_de_descuento,
)
from app.domain.models.descuentos import sin_ceros

from . import permisos
from .autorizacion import validar_alguno_de
from .exceptions import EntidadNoEncontradaError, PrecondicionInvalidaError
from .identificadores import nuevo_id
from .pagos import es_cobrable
from .workflow import registrar_accion_funcional

ROLES_DESCUENTO = permisos.DESCUENTO
# DEC-IT1-02 (11/11/2026, BR-REP-016/039): otorgan, modifican y quitan la
# CORTESIA Recepcion, Coordinacion RMA y Administracion.
ROLES_CORTESIA = permisos.CORTESIA
# DEC-AJ-10 (D-10.2): revertir o corregir un ajuste equivocado.
ROLES_REVERSION_AJUSTE = permisos.AJUSTE_REVERTIR

# Historial de la Orden (EV-REP-041): la system action "Aplicar un ajuste
# comercial por Orden o por Detalle" (traceability/macro-integral.yaml).
ACCION_AJUSTE_COMERCIAL = "ACC-REP-072"
APLICAR = "APLICAR_AJUSTE_COMERCIAL"
CAMBIAR = "CAMBIAR_AJUSTE_COMERCIAL"
QUITAR = "QUITAR_AJUSTE_COMERCIAL"
REVERTIR = "REVERTIR_AJUSTE_COMERCIAL"
CORREGIR = "CORREGIR_AJUSTE_COMERCIAL"
RECALCULAR = "RECALCULAR_AJUSTE_COMERCIAL"

NOMBRE_CLASE = {
    ClaseAjuste.DESCUENTO: "Descuento",
    ClaseAjuste.CORTESIA: "Cortesia",
}


def roles_de_clase(clase: ClaseAjuste) -> permisos.Permiso:
    """El permiso de cada clase de ajuste (BR-REP-039)."""
    return ROLES_CORTESIA if clase is ClaseAjuste.CORTESIA else ROLES_DESCUENTO


def descripcion_de_descuento(registro: RegistroDescuento) -> str:
    """Como se expresa: "10 %" o "$ 5000"."""
    if registro.tipo is TipoDescuento.PORCENTAJE:
        return f"{registro.valor.normalize():f} %"
    return f"$ {registro.valor:.2f}"


def descuento_editable(orden: OrdenReparacion) -> bool:
    """La Orden admite ajustes: cobrable, abierta, no cancelada, con
    trabajos y todavia sin entregar (D-10.3)."""
    return (
        es_cobrable(orden)
        and not orden.esta_cerrada
        and orden.estado_workflow is not EstadoWorkflow.CANCELADA
        and orden.entrega is None
        and orden.subtotal > 0
    )


def _exigir_editable(orden: OrdenReparacion, que: str) -> None:
    if not descuento_editable(orden):
        raise PrecondicionInvalidaError(
            f"{que} solo en una Orden cobrable, abierta, no cancelada, con "
            "trabajos y antes de entregar el equipo."
        )


def _motivo(motivo: str, que: str) -> str:
    motivo = (motivo or "").strip()
    if not motivo:
        raise PrecondicionInvalidaError(f"{que} exige indicar el motivo.")
    return motivo


def _destino(detalle_id: str | None) -> str:
    return f"el trabajo {detalle_id}" if detalle_id else "la Orden"


def _detalle_ajustable(orden: OrdenReparacion, detalle_id: str | None):
    if detalle_id is None:
        return None
    detalle = next(
        (d for d in orden.reparaciones_detail if d.id == detalle_id), None
    )
    if detalle is None:
        raise PrecondicionInvalidaError(
            f"La Orden no tiene el trabajo {detalle_id}."
        )
    if detalle.estado is EstadoReparacionDetail.CANCELADO:
        raise PrecondicionInvalidaError(
            f"El trabajo {detalle_id} esta cancelado: no se cobra."
        )
    return detalle


def resumen_de_registro(registro: RegistroDescuento) -> str:
    """Una linea para el historial interno: clase, valor y destino, con la
    evidencia de los importes si la tiene."""
    nombre = NOMBRE_CLASE[registro.clase]
    if registro.tipo is None:
        texto = f"Sin {nombre.lower()} en {_destino(registro.detalle_id)}"
    else:
        texto = (
            f"{nombre} {descripcion_de_descuento(registro)} sobre "
            f"{_destino(registro.detalle_id)}"
        )
    if registro.precio_original is not None:
        texto += (
            f" (precio {registro.precio_original}, ajuste "
            f"{registro.importe_aplicado}, final {registro.precio_final})"
        )
    return texto


def _nuevo_registro(
    orden: OrdenReparacion,
    *,
    tipo: TipoDescuento | None,
    valor: Decimal | None,
    motivo: str,
    usuario: Usuario,
    fecha: datetime,
    clase: ClaseAjuste,
    detalle_id: str | None,
    corrige_a: str | None = None,
) -> RegistroDescuento:
    """Valida el importe y arma el registro con su evidencia (D-10.4): la
    base a la que se aplica en ``orden``, lo que descuenta y lo que queda."""
    base = orden.base_de_ajuste(detalle_id)
    if tipo is not None:
        if valor is None or valor <= 0:
            raise PrecondicionInvalidaError(
                "El ajuste debe ser mayor que cero."
            )
        if tipo is TipoDescuento.PORCENTAJE and valor > 100:
            raise PrecondicionInvalidaError(
                "Un ajuste porcentual no puede superar el 100 %."
            )
        if tipo is TipoDescuento.IMPORTE and valor > base:
            destino = (
                f"el precio del trabajo ({base})"
                if detalle_id
                else f"el subtotal de los trabajos ({base})"
            )
            raise PrecondicionInvalidaError(
                f"El descuento ({valor}) no puede superar {destino}."
            )
    else:
        valor = None
    registro = RegistroDescuento(
        id=nuevo_id("AJ"),
        tipo=tipo,
        valor=valor,
        motivo=motivo,
        usuario_id=usuario.id,
        fecha=fecha,
        clase=clase,
        detalle_id=detalle_id,
        corrige_a=corrige_a,
    )
    importe = importe_de_descuento(base, registro)
    registro.precio_original = sin_ceros(base)
    registro.importe_aplicado = sin_ceros(importe)
    registro.precio_final = sin_ceros(base - importe)
    return registro


def _con_historial(
    orden: OrdenReparacion,
    *,
    accion: str,
    usuario: Usuario,
    fecha: datetime,
    detalle_id: str | None,
    observacion: str,
) -> OrdenReparacion:
    return registrar_accion_funcional(
        orden,
        accion_id=ACCION_AJUSTE_COMERCIAL,
        accion=accion,
        fecha=fecha,
        usuario_id=usuario.id,
        reparacion_detail_id=detalle_id,
        observacion=observacion,
    )


def aplicar_descuento(
    orden: OrdenReparacion,
    *,
    tipo: TipoDescuento | None,
    valor: Decimal | None,
    motivo: str,
    usuario: Usuario,
    fecha: datetime,
    clase: ClaseAjuste = ClaseAjuste.DESCUENTO,
    detalle_id: str | None = None,
) -> OrdenReparacion:
    """Aplica, cambia o quita (``tipo`` en ``None``) un Ajuste Comercial.

    DC09 y DEC-MI-03: el ajuste es de la Orden (``detalle_id`` en ``None``)
    o de un Detalle no cancelado. Un solo ajuste vigente por destino (el
    ultimo registro no revertido), sin acumular. El de un Detalle descuenta
    sobre su precio; el de la Orden, sobre lo que queda despues de los
    ajustes de los Detalles, y no se prorratea entre ellos. Porcentaje
    entre 0 y 100; importe fijo hasta lo que queda del destino.

    D-10.1: aplicar exige el permiso de la clase; cambiar o quitar un ajuste
    vigente exige ademas el de la clase que se reemplaza. Quitar conserva la
    clase del vigente.
    """
    vigente = (
        orden.ajuste_de_detalle(detalle_id)
        if detalle_id is not None
        else orden.descuento_vigente
    )
    if tipo is not None:
        validar_alguno_de(usuario, roles_de_clase(clase))
    if vigente is not None:
        validar_alguno_de(usuario, roles_de_clase(vigente.clase))
    elif tipo is None:
        validar_alguno_de(usuario, roles_de_clase(clase))
    _exigir_editable(orden, "El ajuste comercial se aplica")
    _detalle_ajustable(orden, detalle_id)
    motivo = (motivo or "").strip()
    if not motivo:
        raise PrecondicionInvalidaError(
            "El descuento exige indicar el motivo (promocion, convenio o "
            "acuerdo comercial)."
        )
    if tipo is None and vigente is None:
        raise PrecondicionInvalidaError(
            "El trabajo no tiene descuento."
            if detalle_id
            else "La Orden no tiene descuento."
        )
    registro = _nuevo_registro(
        orden,
        tipo=tipo,
        valor=valor,
        motivo=motivo,
        usuario=usuario,
        fecha=fecha,
        clase=vigente.clase if tipo is None else clase,
        detalle_id=detalle_id,
    )
    accion = QUITAR if tipo is None else CAMBIAR if vigente else APLICAR
    nueva_orden = _con_historial(
        orden,
        accion=accion,
        usuario=usuario,
        fecha=fecha,
        detalle_id=detalle_id,
        observacion=f"{resumen_de_registro(registro)}. Motivo: {motivo}",
    )
    nueva_orden.descuentos.append(registro)
    return nueva_orden


# --- Reversion y correccion (D-10.2) ---------------------------------------


def registro_de_ajuste(
    orden: OrdenReparacion, ajuste_id: str
) -> RegistroDescuento:
    registro = next((d for d in orden.descuentos if d.id == ajuste_id), None)
    if registro is None:
        raise EntidadNoEncontradaError(
            f"La Orden {orden.id} no tiene el ajuste comercial {ajuste_id}."
        )
    return registro


def ajuste_revertible(
    orden: OrdenReparacion, registro: RegistroDescuento
) -> bool:
    """Es el ajuste vigente de su destino: el ultimo registro no revertido,
    y no quita el ajuste."""
    ultimo = orden.ultimo_registro_de(registro.detalle_id)
    return (
        ultimo is not None
        and ultimo.id == registro.id
        and registro.tipo is not None
    )


def _validar_revertible(
    orden: OrdenReparacion, ajuste_id: str
) -> RegistroDescuento:
    registro = registro_de_ajuste(orden, ajuste_id)
    if registro.revertido:
        raise PrecondicionInvalidaError(
            f"El ajuste {ajuste_id} ya fue revertido: no se revierte dos "
            "veces."
        )
    if not ajuste_revertible(orden, registro):
        raise PrecondicionInvalidaError(
            f"El ajuste {ajuste_id} no es el vigente de "
            f"{_destino(registro.detalle_id)}: solo se revierte o corrige el "
            "ajuste vigente."
        )
    return registro


def _validar_topes(orden: OrdenReparacion) -> None:
    """BR-REP-016: ningun ajuste vigente de importe fijo supera el importe
    al que se aplica (y por lo tanto el total nunca es negativo)."""
    destinos: list[str | None] = [
        d.id
        for d in orden.reparaciones_detail
        if d.estado is not EstadoReparacionDetail.CANCELADO
    ]
    destinos.append(None)
    for destino in destinos:
        vigente = orden.ajuste_vigente_de(destino)
        if vigente is None or vigente.tipo is not TipoDescuento.IMPORTE:
            continue
        base = orden.base_de_ajuste(destino)
        if vigente.valor > base:
            raise PrecondicionInvalidaError(
                f"El ajuste {vigente.id} de {_destino(destino)} "
                f"({vigente.valor}) superaria el importe al que se aplica "
                f"({base}). No se cambio nada."
            )
    if orden.total < 0:  # defensa: los topes lo aseguran
        raise PrecondicionInvalidaError(
            "El total de la Orden quedaria negativo. No se cambio nada."
        )


def _marcar_revertido(
    orden: OrdenReparacion,
    ajuste_id: str,
    *,
    usuario: Usuario,
    motivo: str,
    fecha: datetime,
) -> None:
    """Sobre una Orden que ya es copia."""
    registro_de_ajuste(orden, ajuste_id).reversion = ReversionAjuste(
        usuario_id=usuario.id, fecha=fecha, motivo=motivo
    )


def revertir_ajuste(
    orden: OrdenReparacion,
    *,
    ajuste_id: str,
    usuario: Usuario,
    motivo: str,
    fecha: datetime,
) -> OrdenReparacion:
    """Revierte el ajuste vigente de un destino, registrado por error.

    El registro se conserva con su reversion (quien, cuando y por que), deja
    de contar y vuelve a regir el anterior no revertido de ese destino; si
    ese anterior quito el ajuste, no queda ninguno. Pagos, devoluciones y
    las copias del recargo no cambian: si queda saldo a favor, se devuelve
    antes de entregar (DEC-MI-03).
    """
    validar_alguno_de(usuario, ROLES_REVERSION_AJUSTE)
    motivo = _motivo(motivo, "Revertir un ajuste comercial")
    _exigir_editable(orden, "Un ajuste comercial se revierte")
    registro = _validar_revertible(orden, ajuste_id)
    nueva_orden = _con_historial(
        orden,
        accion=REVERTIR,
        usuario=usuario,
        fecha=fecha,
        detalle_id=registro.detalle_id,
        observacion=(
            f"Revierte {registro.id}: {resumen_de_registro(registro)}. "
            f"Motivo: {motivo}"
        ),
    )
    _marcar_revertido(
        nueva_orden, ajuste_id, usuario=usuario, motivo=motivo, fecha=fecha
    )
    _validar_topes(nueva_orden)
    return nueva_orden


def corregir_ajuste(
    orden: OrdenReparacion,
    *,
    ajuste_id: str,
    tipo: TipoDescuento,
    valor: Decimal,
    clase: ClaseAjuste,
    usuario: Usuario,
    motivo: str,
    fecha: datetime,
) -> OrdenReparacion:
    """Revierte el ajuste vigente y registra el correcto, en una sola
    operacion: el nuevo apunta al revertido (``corrige_a``) y va al mismo
    destino. Exige el permiso de reversion y el de la clase nueva."""
    validar_alguno_de(usuario, ROLES_REVERSION_AJUSTE)
    validar_alguno_de(usuario, roles_de_clase(clase))
    motivo = _motivo(motivo, "Corregir un ajuste comercial")
    _exigir_editable(orden, "Un ajuste comercial se corrige")
    registro = _validar_revertible(orden, ajuste_id)
    nueva_orden = orden.model_copy(deep=True)
    _marcar_revertido(
        nueva_orden, ajuste_id, usuario=usuario, motivo=motivo, fecha=fecha
    )
    correcto = _nuevo_registro(
        nueva_orden,
        tipo=tipo,
        valor=valor,
        motivo=motivo,
        usuario=usuario,
        fecha=fecha,
        clase=clase,
        detalle_id=registro.detalle_id,
        corrige_a=registro.id,
    )
    nueva_orden = _con_historial(
        nueva_orden,
        accion=CORREGIR,
        usuario=usuario,
        fecha=fecha,
        detalle_id=registro.detalle_id,
        observacion=(
            f"Corrige {registro.id} ({resumen_de_registro(registro)}): "
            f"{resumen_de_registro(correcto)}. Motivo: {motivo}"
        ),
    )
    nueva_orden.descuentos.append(correcto)
    _validar_topes(nueva_orden)
    return nueva_orden


# --- Recalculos (D-10.4) ---------------------------------------------------


def registrar_recalculos(
    antes: OrdenReparacion,
    despues: OrdenReparacion,
    *,
    causa: CausaRecalculo,
    usuario_id: str,
    fecha: datetime,
) -> OrdenReparacion:
    """Deja evidencia de cada ajuste vigente cuyo importe efectivo cambio
    entre ``antes`` y ``despues`` por una redefinicion o una cancelacion.

    No escribe un ajuste nuevo: un ``RecalculoAjuste`` inmutable por ajuste,
    con el precio y el importe anteriores y nuevos, y su paso en el
    historial de la Orden. Sin cambios devuelve ``despues`` tal cual.
    """
    destinos: list[str | None] = [d.id for d in antes.reparaciones_detail]
    destinos.append(None)
    recalculos = []
    for destino in destinos:
        vigente = antes.ajuste_vigente_de(destino)
        if vigente is None:
            continue
        importe_anterior = antes.importe_de_ajuste(destino)
        importe_nuevo = despues.importe_de_ajuste(destino)
        if importe_anterior == importe_nuevo:
            continue
        recalculos.append(
            RecalculoAjuste(
                ajuste_id=vigente.id,
                causa=causa,
                detalle_id=destino,
                precio_anterior=sin_ceros(antes.base_de_ajuste(destino)),
                precio_nuevo=sin_ceros(despues.base_de_ajuste(destino)),
                importe_anterior=sin_ceros(importe_anterior),
                importe_nuevo=sin_ceros(importe_nuevo),
                usuario_id=usuario_id,
                fecha=fecha,
            )
        )
    for recalculo in recalculos:
        despues = registrar_accion_funcional(
            despues,
            accion_id=ACCION_AJUSTE_COMERCIAL,
            accion=RECALCULAR,
            fecha=fecha,
            usuario_id=usuario_id,
            reparacion_detail_id=recalculo.detalle_id,
            observacion=(
                f"Recalcula {recalculo.ajuste_id} por "
                f"{recalculo.causa.value.lower()}: precio "
                f"{recalculo.precio_anterior} -> {recalculo.precio_nuevo}, "
                f"ajuste {recalculo.importe_anterior} -> "
                f"{recalculo.importe_nuevo}"
            ),
        )
        despues.recalculos_ajuste.append(recalculo)
    return despues


def ajustes_a_recalcular(
    antes: OrdenReparacion, despues: OrdenReparacion
) -> list[str]:
    """Los ajustes vigentes cuyo importe efectivo cambiaria (para avisar
    antes de confirmar una redefinicion o una cancelacion)."""
    destinos: list[str | None] = [d.id for d in antes.reparaciones_detail]
    destinos.append(None)
    return [
        antes.ajuste_vigente_de(destino).id
        for destino in destinos
        if antes.ajuste_vigente_de(destino) is not None
        and antes.importe_de_ajuste(destino)
        != despues.importe_de_ajuste(destino)
    ]
