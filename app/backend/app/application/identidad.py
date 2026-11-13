"""Identidad del Equipo (DEC-MI-11): identificar, historial y correccion.

Identificar solo lee: por IMEI y, si no hay, por numero de serie. El
historial de una identidad son todas sus Ordenes. La correccion cambia la
identidad a la que se vincula una Orden abierta, con motivo y auditoria.
"""

from app.domain.identidad import CandidatoEquipo, candidatos, normalizar
from app.domain.models import Equipo, OrdenReparacion
from app.services import EntidadNoEncontradaError, nuevo_id
from app.services.identidad import (
    corregir_vinculo,
    exigir_vinculo_por_identidad,
)

from .contexto import ApplicationContext
from .modificacion import orden_para_modificar


def identificar(
    contexto: ApplicationContext,
    *,
    imei: str | None,
    numero_serie: str | None,
) -> tuple[str | None, list[CandidatoEquipo]]:
    if not normalizar(imei) and not normalizar(numero_serie):
        return None, []
    with contexto.lectura():
        ordenes = contexto.ordenes.listar_por_identificacion_equipo(
            imei=imei, numero_serie=numero_serie
        )
    return candidatos(ordenes, imei=imei, numero_serie=numero_serie)


def ordenes_del_equipo(
    contexto: ApplicationContext, equipo_id: str
) -> list[OrdenReparacion]:
    with contexto.lectura():
        ordenes = contexto.ordenes.listar_por_equipo(equipo_id)
    return sorted(ordenes, key=lambda o: o.created_at, reverse=True)


def equipo_registrado(
    contexto: ApplicationContext, equipo_id: str
) -> Equipo | None:
    """Los datos del Equipo con ese ID en su Orden mas reciente."""
    ordenes = contexto.ordenes.listar_por_equipo(equipo_id)
    if not ordenes:
        return None
    return max(ordenes, key=lambda o: o.created_at).equipo


def validar_equipo_del_ingreso(
    contexto: ApplicationContext, equipo: Equipo
) -> None:
    """Un ingreso que reusa la identidad de un Equipo debe compartir su
    IMEI o su numero de serie (dentro de la transaccion del ingreso)."""
    exigir_vinculo_por_identidad(
        equipo, equipo_registrado(contexto, equipo.id)
    )


def corregir_vinculo_equipo(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    equipo_id: str | None,
    motivo: str,
) -> OrdenReparacion:
    """``equipo_id`` en ``None``: «Ninguno», una identidad nueva."""
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with orden_para_modificar(contexto, orden_id) as orden:
        existente = (
            equipo_registrado(contexto, equipo_id) if equipo_id else None
        )
        if equipo_id and existente is None:
            raise EntidadNoEncontradaError(f"No existe el Equipo {equipo_id}")
        orden = corregir_vinculo(
            orden,
            nuevo_equipo_id=equipo_id or nuevo_id("EQP"),
            existente=existente,
            motivo=motivo,
            usuario=usuario,
            fecha=fecha,
        )
        contexto.ordenes.guardar(orden)
    return orden
