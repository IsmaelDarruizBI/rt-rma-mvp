"""Accion del comando: el registro que exigen eventos y movimientos (E4).

En el esquema, cada evento del historial (``rma.evento_negocio``) y cada
movimiento de inventario referencian una ``rma.accion_usuario``
CONFIRMADA (columna ``accion_id NOT NULL``). Durante el Bloque A la crea
el repository la primera vez que la necesita en la transaccion (DA-3):
una sola por comando, sin clave de idempotencia, con el usuario de lo que
se esta registrando o, si no hay usuario, como proceso del sistema.

Se inserta dentro de la transaccion que la usa: si el comando se
revierte, la accion tambien (no quedan acciones huerfanas). En E6 la
capa de aplicacion la declarara de forma explicita, con su clave de
idempotencia y la respuesta del comando; esta misma fila es la que se
completara entonces.

Idempotencia (E6, B1): ``PostgresRegistroDeAcciones`` registra la accion
de un comando con clave antes de ejecutarlo; esa misma fila es la accion
del comando (``accion_del_comando`` la reutiliza). La unicidad la da
``accion_usuario_idempotencia`` (usuario y clave, entre las CONFIRMADAS).

Diseno: ``docs/postgresql/e4-e7-diseno-integrado.md`` (DA-3, secciones 6
y 20).
"""

import json
from typing import Any
from uuid import UUID

from app.repositories import (
    ClaveReutilizadaError,
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
    RespuestaGuardada,
)

from .consultas import ESCRITURA, LECTURA, consulta
from .ejecutor import EjecutorSql
from .transaccion import UnidadDeTrabajoPostgres

PROCESO_SISTEMA = "SISTEMA"
_CLAVE = "accion_del_comando"

_REGISTRAR = consulta(
    "acciones.registrar_tecnica",
    """
    INSERT INTO rma.accion_usuario
        (usuario_id, proceso, operacion, resultado, orden_id)
    VALUES
        (%(usuario)s, %(proceso)s, %(operacion)s, 'CONFIRMADA', %(orden)s)
    RETURNING id
    """,
    modo=ESCRITURA,
)


def accion_del_comando(
    unidad: UnidadDeTrabajoPostgres,
    ejecutor: EjecutorSql,
    *,
    operacion: str,
    usuario: UUID | None,
    orden: UUID | None,
) -> UUID:
    """La accion CONFIRMADA de la transaccion en curso; la crea la primera
    vez. ``usuario`` es el responsable (``None``: proceso del sistema)."""
    datos: dict[str, Any] = unidad.datos_de_transaccion()
    accion = datos.get(_CLAVE)
    if accion is None:
        fila = ejecutor.fila(
            _REGISTRAR,
            {
                "usuario": usuario,
                "proceso": None if usuario else PROCESO_SISTEMA,
                "operacion": operacion,
                "orden": orden,
            },
        )
        accion = datos[_CLAVE] = fila.id
    return accion


# --- Idempotencia (E6, B1) ---------------------------------------------------

_USUARIO = consulta(
    "acciones.usuario",
    "SELECT id FROM rma.usuario WHERE codigo = %(codigo)s",
    modo=ESCRITURA,
)
# La clave confirmada de otra solicitud en curso hace esperar al INSERT: si
# esa confirma, no se inserta nada y se lee su respuesta; si se revierte, se
# inserta esta.
_REGISTRAR_CON_CLAVE = consulta(
    "acciones.registrar_con_clave",
    """
    INSERT INTO rma.accion_usuario
        (usuario_id, operacion, clave_idempotencia, huella, resultado)
    VALUES (%(usuario)s, %(operacion)s, %(clave)s, %(huella)s, 'CONFIRMADA')
    ON CONFLICT (usuario_id, clave_idempotencia)
        WHERE clave_idempotencia IS NOT NULL AND resultado = 'CONFIRMADA'
        DO NOTHING
    RETURNING id
    """,
    modo=ESCRITURA,
)
_CONFIRMADA = consulta(
    "acciones.confirmada",
    """
    SELECT operacion, huella, respuesta FROM rma.accion_usuario
    WHERE usuario_id = %(usuario)s AND clave_idempotencia = %(clave)s
      AND resultado = 'CONFIRMADA'
    """,
    modo=ESCRITURA,
)
_COMPLETAR = consulta(
    "acciones.completar",
    """
    UPDATE rma.accion_usuario
    SET respuesta = %(respuesta)s::jsonb,
        orden_id = COALESCE(
            (SELECT id FROM rma.orden WHERE codigo = %(orden)s), orden_id
        )
    WHERE id = %(id)s
    """,
    modo=ESCRITURA,
)
_RECHAZAR = consulta(
    "acciones.rechazar",
    """
    INSERT INTO rma.accion_usuario
        (usuario_id, operacion, clave_idempotencia, huella, resultado,
         motivo_rechazo, respuesta)
    VALUES (%(usuario)s, %(operacion)s, %(clave)s, %(huella)s, 'RECHAZADA',
            %(motivo)s, %(respuesta)s::jsonb)
    """,
    modo=ESCRITURA,
)


_CONFIRMADA_DE = consulta(
    "acciones.confirmada_de",
    """
    SELECT a.huella, a.respuesta FROM rma.accion_usuario a
    JOIN rma.usuario u ON u.id = a.usuario_id
    WHERE u.codigo = %(usuario)s AND a.clave_idempotencia = %(clave)s
      AND a.resultado = 'CONFIRMADA'
    """,
    modo=LECTURA,
)


def _como_json(respuesta: RespuestaGuardada) -> str:
    return json.dumps(
        {"estado": respuesta.estado, "cuerpo": respuesta.cuerpo},
        ensure_ascii=False,
    )


class PostgresRegistroDeAcciones:
    """``RegistroDeAcciones`` sobre ``rma.accion_usuario``."""

    def __init__(self, unidad: UnidadDeTrabajoPostgres) -> None:
        self._unidad = unidad

    def iniciar(
        self, *, operacion: str, usuario_id: str, clave: str, huella: str
    ) -> RespuestaGuardada | None:
        if not self._unidad.en_curso():
            raise PersistenciaError(
                "Una operacion con clave de idempotencia exige la "
                "transaccion del comando."
            )
        ejecutor = self._unidad.ejecutor()
        usuario = self._usuario(ejecutor, usuario_id)
        fila = ejecutor.fila(
            _REGISTRAR_CON_CLAVE,
            {
                "usuario": usuario,
                "operacion": operacion,
                "clave": clave,
                "huella": huella,
            },
        )
        if fila is not None:
            # Es la accion del comando: eventos y movimientos la usan.
            self._unidad.datos_de_transaccion()[_CLAVE] = fila.id
            return None
        previa = ejecutor.fila(
            _CONFIRMADA, {"usuario": usuario, "clave": clave}
        )
        if previa.huella != huella:
            raise ClaveReutilizadaError(
                "La clave de idempotencia ya se uso para otra operacion o "
                "con otros datos: genera una clave nueva."
            )
        if previa.respuesta is None:
            raise PersistenciaError(
                f"La accion confirmada de la clave {clave} no tiene respuesta."
            )
        return RespuestaGuardada(
            estado=previa.respuesta["estado"],
            cuerpo=previa.respuesta["cuerpo"],
        )

    def completar(
        self, *, respuesta: RespuestaGuardada, orden_id: str | None
    ) -> None:
        accion = self._unidad.datos_de_transaccion().get(_CLAVE)
        if accion is None:
            raise PersistenciaError(
                "No hay una accion con clave en la transaccion en curso."
            )
        self._unidad.ejecutor().ejecutar(
            _COMPLETAR,
            {
                "id": accion,
                "respuesta": _como_json(respuesta),
                "orden": orden_id,
            },
        )

    def recuperar(
        self, *, operacion: str, usuario_id: str, clave: str, huella: str
    ) -> RespuestaGuardada | None:
        # Una lectura breve, con otra conexion: la del comando se perdio.
        with self._unidad.lectura() as lector:
            fila = lector.fila(
                _CONFIRMADA_DE, {"usuario": usuario_id, "clave": clave}
            )
        if fila is None or fila.huella != huella or fila.respuesta is None:
            return None
        return RespuestaGuardada(
            estado=fila.respuesta["estado"], cuerpo=fila.respuesta["cuerpo"]
        )

    def rechazar(
        self,
        *,
        operacion: str,
        usuario_id: str,
        clave: str,
        huella: str,
        motivo: str,
        respuesta: RespuestaGuardada,
    ) -> None:
        # Despues del ROLLBACK del comando: su propia transaccion.
        with self._unidad.transaccion():
            ejecutor = self._unidad.ejecutor()
            ejecutor.ejecutar(
                _RECHAZAR,
                {
                    "usuario": self._usuario(ejecutor, usuario_id),
                    "operacion": operacion,
                    "clave": clave,
                    "huella": huella,
                    "motivo": motivo,
                    "respuesta": _como_json(respuesta),
                },
            )

    @staticmethod
    def _usuario(ejecutor: EjecutorSql, codigo: str) -> UUID:
        fila = ejecutor.fila(_USUARIO, {"codigo": codigo})
        if fila is None:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe el Usuario {codigo}"
            )
        return fila.id
