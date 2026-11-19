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
    PoliticaGarantiaRma,
    TipoReparacion,
)
from app.repositories.configuracion import ConfiguracionRepository
from app.services.autorizacion import validar_alguno_de
from app.services.configuracion import (
    ROLES_PRECIOS,
    ROLES_TIPO_REPARACION,
    cambio_de_tipos_habilitados,
    cambios_de_tipo,
)
from app.services.exceptions import (
    CodigoDuplicadoError,
    PrecondicionInvalidaError,
)

from .codigos import con_reintento_de_codigo
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
    codigo: str | None = None,
    nombre: str,
    precio: Decimal,
    puntaje: int,
    garantia_dias: int,
    garantia_con_checkin: int = 90,
    garantia_sin_checkin: int = 30,
    politica_garantia_rma: PoliticaGarantiaRma | None = None,
    activo: bool = True,
    nuevo: bool,
) -> TipoReparacion:
    """Alta o edicion de un Tipo, con auditoria.

    CFG-01: en el alta el codigo es opcional. Sin codigo lo genera la base
    (``TR-NNN``); un codigo informado (clientes anteriores, scripts) se
    respeta si no existe otro igual sin distinguir mayusculas.
    """
    repositorio = _repositorio(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    # El permiso antes de reservar un codigo: un rechazo no consume numeros.
    validar_alguno_de(usuario, ROLES_TIPO_REPARACION)
    if nuevo:
        validar_alguno_de(usuario, ROLES_PRECIOS)  # D3: el alta fija precio
    codigo = (codigo or "").strip() or None
    if not nuevo and codigo is None:
        raise PrecondicionInvalidaError("Falta el codigo del Tipo a editar.")
    codigo_informado = codigo

    def intento():
        codigo = codigo_informado
        with contexto.transaccion():
            anterior = None
            if not nuevo:
                anterior = contexto.catalogos.obtener_tipo_reparacion(codigo)
            elif codigo is None:
                codigo = repositorio.reservar_codigo("TR")
            elif any(
                t.id.upper() == codigo.upper()
                for t in contexto.catalogos.listar_tipos_reparacion()
            ):
                raise CodigoDuplicadoError(
                    f"Ya existe un Tipo de Reparacion {codigo}."
                )
            tipo = TipoReparacion(
                id=codigo,
                nombre=nombre.strip(),
                precio=precio,
                puntaje=puntaje,
                garantia_dias=garantia_dias,
                garantia_con_checkin=garantia_con_checkin,
                garantia_sin_checkin=garantia_sin_checkin,
                politica_garantia_rma=politica_garantia_rma,
                activo=activo,
            )
            cambios = cambios_de_tipo(
                anterior, tipo, usuario=usuario, fecha=fecha
            )
            repositorio.guardar_tipo_reparacion(
                tipo, nuevo=nuevo, cambios=cambios
            )
        return tipo

    return con_reintento_de_codigo(
        intento, generado=nuevo and codigo_informado is None
    )


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
