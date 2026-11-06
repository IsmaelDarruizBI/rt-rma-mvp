"""Clave de idempotencia de los comandos que crean registros (E6, B1).

Encabezado opcional ``Idempotency-Key`` (DE6-1). Sin clave, o con la
persistencia JSON (que no registra acciones), el endpoint se comporta
exactamente como antes. Con clave y PostgreSQL, ``con_clave`` corre todo en
una sola transaccion:

1. registra la accion del comando con su clave y la huella de la operacion
   y sus parametros (DE6-2, DE6-3);
2. si la clave ya esta confirmada con la misma huella, devuelve la
   respuesta guardada -codigo y cuerpo- sin ejecutar nada (DE6-4); con otra
   huella, 422 ``CLAVE_REUTILIZADA``; si otra solicitud con la clave sigue en
   curso, espera a que termine;
3. si no, ejecuta el caso de uso (que se une a la transaccion), arma la
   respuesta y la guarda en la misma transaccion: se confirma con el
   comando o no se confirma.

Un rechazo funcional revierte el comando y queda RECHAZADO en otra
transaccion, para auditoria (DE6-6); no bloquea un reintento.

COMMIT incierto (B2, DE6-5): si se pierde la conexion al confirmar, se busca
la accion con otra conexion. Confirmada: se devuelve su respuesta. Si no
aparece: 503 ``PERSISTENCIA_RESULTADO_INCIERTO``, sin afirmar nada; el
reintento con la misma clave devuelve lo confirmado o ejecuta una vez.

Los errores tecnicos no se registran. El ``operacion_id`` del cuerpo
sigue con sus reglas: es parte de los parametros y de la huella.

Diseno: ``docs/postgresql/e4-e7-diseno-integrado.md`` (secciones 6 y 20).
"""

import functools
import hashlib
import inspect
import json
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Header, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.application import ApplicationContext
from app.repositories import (
    PersistenciaResultadoInciertoError,
    RespuestaGuardada,
)
from app.services import (
    DomainError,
    EntidadNoEncontradaError,
    PrecondicionInvalidaError,
    RecursoNoDisponibleError,
)

ENCABEZADO = "Idempotency-Key"

ClaveDep = Annotated[
    str | None,
    Header(
        alias=ENCABEZADO,
        min_length=1,
        max_length=200,
        description=(
            "Opcional. Un reintento con la misma clave devuelve la respuesta "
            "ya confirmada en lugar de repetir la operacion."
        ),
    ),
]


def huella(operacion: str, parametros: dict[str, Any]) -> str:
    """SHA-256 de la operacion y sus parametros normalizados (DE6-3)."""
    texto = json.dumps(
        {"operacion": operacion, "parametros": jsonable_encoder(parametros)},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def con_clave(
    contexto: ApplicationContext,
    clave: str | None,
    *,
    operacion: str,
    usuario_id: str,
    parametros: dict[str, Any],
    ejecutar: Callable[[], Any],
    estado: int = status.HTTP_200_OK,
    orden_id: str | None = None,
) -> Any:
    """Ejecuta el endpoint con la clave, si la hay (ver el modulo)."""
    registro = contexto.acciones
    if clave is None or registro is None:
        return ejecutar()
    datos = {
        "operacion": operacion,
        "usuario_id": usuario_id,
        "clave": clave,
        "huella": huella(operacion, parametros),
    }
    try:
        with contexto.transaccion():
            guardada = registro.iniciar(**datos)
            if guardada is None:
                cuerpo = _cuerpo(ejecutar())
                guardada = RespuestaGuardada(estado=estado, cuerpo=cuerpo)
                registro.completar(
                    respuesta=guardada, orden_id=orden_id or _orden(cuerpo)
                )
    except DomainError as error:
        registro.rechazar(
            **datos, motivo=str(error), respuesta=_rechazo(error)
        )
        raise
    except PersistenciaResultadoInciertoError:
        # B2 (DE6-5): con otra conexion, si la accion quedo confirmada, se
        # devuelve su respuesta. Si no aparece, sigue incierto: no se
        # afirma que no se guardo (el COMMIT pudo estar terminando).
        guardada = registro.recuperar(**datos)
        if guardada is None:
            raise
    return JSONResponse(guardada.cuerpo, status_code=guardada.estado)


def _cuerpo(resultado: Any) -> Any:
    """Lo mismo que FastAPI serializa para la respuesta."""
    if isinstance(resultado, BaseModel):
        return resultado.model_dump(mode="json", by_alias=True)
    return jsonable_encoder(resultado)


def _orden(cuerpo: Any) -> str | None:
    """La Orden de la respuesta, si la respuesta es una Orden."""
    if isinstance(cuerpo, dict) and isinstance(cuerpo.get("id"), str):
        return cuerpo["id"]
    return None


def _rechazo(error: DomainError) -> RespuestaGuardada:
    """Lo que respondio la API al rechazo (``api/errores.py``)."""
    if isinstance(error, EntidadNoEncontradaError):
        estado, codigo = status.HTTP_404_NOT_FOUND, "NO_ENCONTRADO"
    elif isinstance(error, RecursoNoDisponibleError):
        estado, codigo = status.HTTP_409_CONFLICT, "RECURSO_NO_DISPONIBLE"
    elif isinstance(error, PrecondicionInvalidaError):
        estado, codigo = status.HTTP_409_CONFLICT, error.codigo
    else:
        estado, codigo = status.HTTP_409_CONFLICT, "CONFLICTO_FUNCIONAL"
    return RespuestaGuardada(
        estado=estado,
        cuerpo={"error": {"codigo": codigo, "mensaje": str(error)}},
    )


def idempotente(operacion: str, *, estado: int = status.HTTP_200_OK):
    """Endpoint con clave de idempotencia opcional (ver el modulo).

    Agrega a la firma el encabezado ``Idempotency-Key``. El cuerpo del
    endpoint no cambia: recibe ``contexto`` y ``cuerpo`` con su
    ``usuario_id`` (o el ``usuario_id`` de la consulta), el alcance de
    la clave, y, si es de una Orden, ``orden_id``. ``estado``: el codigo
    de la ruta (201 en las altas).
    """

    def decorar(endpoint: Callable[..., Any]) -> Callable[..., Any]:
        firma = inspect.signature(endpoint)
        clave = inspect.Parameter(
            "clave_idempotencia",
            inspect.Parameter.KEYWORD_ONLY,
            default=None,
            annotation=ClaveDep,
        )

        @functools.wraps(endpoint)
        def envoltura(*args, clave_idempotencia=None, **kwargs):
            cuerpo = kwargs.get("cuerpo")
            return con_clave(
                kwargs["contexto"],
                clave_idempotencia,
                operacion=operacion,
                usuario_id=(
                    cuerpo.usuario_id if cuerpo else kwargs["usuario_id"]
                ),
                parametros={
                    nombre: valor
                    for nombre, valor in kwargs.items()
                    if nombre != "contexto"
                },
                ejecutar=lambda: endpoint(*args, **kwargs),
                estado=estado,
                orden_id=kwargs.get("orden_id"),
            )

        envoltura.__signature__ = firma.replace(
            parameters=[*firma.parameters.values(), clave]
        )
        return envoltura

    return decorar


def id_de_foto(usuario_id: str, clave: str) -> str:
    """Con clave, el id de la foto (y el nombre de su objeto) sale de ella:
    un reintento sobrescribe el mismo objeto, no sube otro (seccion 6.2)."""
    resumen = hashlib.sha256(f"{usuario_id}:{clave}".encode()).hexdigest()
    return f"FOT-{resumen[:12]}"
