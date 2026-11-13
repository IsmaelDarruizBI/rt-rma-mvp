"""Reclamos de garantia rechazados y su continuacion paga (DEC-MI-02).

- Al rechazarse un reclamo (``GarantiaVencidaError``) se registra en una
  transaccion propia: la Orden de garantia no se crea y la Orden original
  no se toca. El codigo del reclamo viaja en el error.
- Recepcion lo puede continuar como reparacion paga de CLIENTE_EXTERNO, con
  confirmacion, una sola vez: cliente, equipo y falla de la Orden original.
- Lo consultan Recepcion, Coordinacion RMA y Administracion.
"""

from collections.abc import Mapping, Sequence

from app.domain.models import Cliente, OrdenReparacion
from app.domain.models.reclamos import ReclamoGarantia
from app.services import permisos
from app.services.autorizacion import validar_alguno_de
from app.services.exceptions import (
    GarantiaVencidaError,
    PrecondicionInvalidaError,
)
from app.services.identificadores import nuevo_id
from app.services.workflow import registrar_accion_funcional

from .contexto import ApplicationContext

ACCION_CONTINUACION_RECLAMO = "ACC-REP-MI02"


def registrar_reclamo_rechazado(
    contexto: ApplicationContext,
    error: GarantiaVencidaError,
    *,
    orden_origen: OrdenReparacion,
    detalle_origen_ids: Sequence[str],
    usuario_id: str,
    excepciones: Mapping[str, str] | None,
) -> ReclamoGarantia | None:
    """Registra el reclamo rechazado; ``None`` sin repositorio."""
    if contexto.reclamos is None:
        return None
    with contexto.transaccion():
        reclamo = ReclamoGarantia(
            id=contexto.reclamos.siguiente_id(),
            orden_origen_id=orden_origen.id,
            detalles_reclamados=list(detalle_origen_ids),
            equipo=orden_origen.equipo,
            usuario_id=usuario_id,
            fecha=contexto.ahora(),
            vigencias=list(getattr(error, "vigencias", [])),
            excepciones_pedidas={
                k: v.strip() for k, v in (excepciones or {}).items() if v
            },
            motivo=str(error),
        )
        contexto.reclamos.guardar(reclamo)
    return reclamo


def _repositorio(contexto: ApplicationContext):
    if contexto.reclamos is None:
        raise PrecondicionInvalidaError(
            "Los reclamos de garantia no estan disponibles en este entorno."
        )
    return contexto.reclamos


def listar_reclamos(contexto: ApplicationContext) -> list[ReclamoGarantia]:
    if contexto.reclamos is None:
        return []
    with contexto.lectura():
        return contexto.reclamos.listar()


def obtener_reclamo(
    contexto: ApplicationContext, reclamo_id: str
) -> ReclamoGarantia:
    with contexto.lectura():
        return _repositorio(contexto).obtener(reclamo_id)


def continuar_como_pago(
    contexto: ApplicationContext,
    *,
    reclamo_id: str,
    usuario_id: str,
    confirmado: bool,
    falla_reportada: str | None = None,
) -> tuple[OrdenReparacion, ReclamoGarantia]:
    """Crea la Orden paga de CLIENTE_EXTERNO que continua el reclamo.

    Exige la confirmacion explicita y que el reclamo no se haya continuado
    antes (evita Ordenes duplicadas). Precarga cliente, equipo y falla de
    la Orden original; la falla puede ajustarse.
    """
    from .ingreso import crear_orden

    repositorio = _repositorio(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    validar_alguno_de(usuario, permisos.RECLAMO_CONTINUAR)
    if not confirmado:
        raise PrecondicionInvalidaError(
            "Continuar el reclamo como reparacion paga exige confirmarlo."
        )
    with contexto.transaccion():
        reclamo = repositorio.obtener(reclamo_id)
        if reclamo.orden_continuacion_id is not None:
            raise PrecondicionInvalidaError(
                f"El reclamo {reclamo.id} ya se continuo en la Orden "
                f"{reclamo.orden_continuacion_id}."
            )
        origen = contexto.ordenes.obtener(reclamo.orden_origen_id)
        falla = (
            falla_reportada or ""
        ).strip() or origen.equipo.falla_reportada
        equipo = origen.equipo.model_copy(
            update={"id": nuevo_id("EQP"), "falla_reportada": falla}
        )
        cliente: Cliente = origen.cliente
        orden = crear_orden(
            contexto,
            usuario_id=usuario.id,
            cliente=cliente,
            equipo=equipo,
            cliente_reutilizado=True,
        )
        fecha = contexto.ahora()
        orden = registrar_accion_funcional(
            orden,
            accion_id=ACCION_CONTINUACION_RECLAMO,
            accion="CONTINUAR_RECLAMO_COMO_PAGO",
            fecha=fecha,
            usuario_id=usuario.id,
            observacion=(
                f"Continua el reclamo de garantia rechazado {reclamo.id} "
                f"(Orden original {reclamo.orden_origen_id})"
            ),
        )
        contexto.ordenes.guardar(orden)
        reclamo = reclamo.model_copy(
            update={
                "orden_continuacion_id": orden.id,
                "continuado_por": usuario.id,
                "continuado_en": fecha,
            }
        )
        repositorio.guardar(reclamo)
    return orden, reclamo
