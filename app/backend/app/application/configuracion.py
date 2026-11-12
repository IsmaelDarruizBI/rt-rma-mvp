"""Administracion de catalogos con auditoria (DC23, DC23AUD, BR-REP-040).

Tipos de Reparacion (alta, edicion de precio, puntaje, garantia y nombre,
desactivacion) y Tipos habilitados de cada Mesa de trabajo. Cada comando
guarda el cambio y su auditoria en la misma transaccion. Solo con
PostgreSQL: DC23 pide la administracion sobre la persistencia definitiva.
"""

from collections.abc import Collection
from decimal import Decimal

from app.domain.models import (
    CambioConfiguracion,
    EntidadConfiguracion,
    TipoReparacion,
)
from app.repositories.configuracion import ConfiguracionRepository
from app.services.configuracion import (
    cambio_de_tipos_habilitados,
    cambios_de_tipo,
)
from app.services.exceptions import PrecondicionInvalidaError

from .contexto import ApplicationContext


def _repositorio(contexto: ApplicationContext) -> ConfiguracionRepository:
    if contexto.configuracion is None:
        raise PrecondicionInvalidaError(
            "La administracion de catalogos funciona sobre la base "
            "PostgreSQL (DC23); en el modo JSON los catalogos son de solo "
            "lectura."
        )
    return contexto.configuracion


def guardar_tipo_reparacion(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    codigo: str,
    nombre: str,
    precio: Decimal,
    puntaje: int,
    garantia_dias: int,
    activo: bool = True,
    nuevo: bool,
) -> TipoReparacion:
    repositorio = _repositorio(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    tipo = TipoReparacion(
        id=codigo.strip(),
        nombre=nombre.strip(),
        precio=precio,
        puntaje=puntaje,
        garantia_dias=garantia_dias,
        activo=activo,
    )
    with contexto.transaccion():
        anterior = None
        if not nuevo:
            anterior = contexto.catalogos.obtener_tipo_reparacion(tipo.id)
        elif any(
            t.id == tipo.id
            for t in contexto.catalogos.listar_tipos_reparacion()
        ):
            raise PrecondicionInvalidaError(
                f"Ya existe un Tipo de Reparacion {tipo.id}."
            )
        cambios = cambios_de_tipo(anterior, tipo, usuario=usuario, fecha=fecha)
        repositorio.guardar_tipo_reparacion(tipo, nuevo=nuevo, cambios=cambios)
    return tipo


def habilitar_tipos_en_mesa(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    estacion_id: str,
    tipo_ids: Collection[str],
) -> CambioConfiguracion:
    repositorio = _repositorio(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with contexto.transaccion():
        contexto.catalogos.obtener_estacion(estacion_id)
        anteriores = [
            c.tipo_reparacion_id
            for c in contexto.catalogos.listar_tipo_reparacion_estaciones()
            if c.estacion_id == estacion_id
        ]
        cambio = cambio_de_tipos_habilitados(
            estacion_id,
            anteriores,
            tipo_ids,
            tipos_existentes=contexto.catalogos.listar_tipos_reparacion(),
            usuario=usuario,
            fecha=fecha,
        )
        repositorio.guardar_tipos_de_mesa(estacion_id, set(tipo_ids), cambio)
    return cambio


def historial_de_cambios(
    contexto: ApplicationContext,
    *,
    entidad: EntidadConfiguracion | None = None,
    clave: str | None = None,
) -> list[CambioConfiguracion]:
    """La auditoria de la configuracion (la ruta la limita a
    Administracion). Sin PostgreSQL no hay cambios registrados."""
    if contexto.configuracion is None:
        return []
    return contexto.configuracion.listar_cambios(entidad=entidad, clave=clave)
