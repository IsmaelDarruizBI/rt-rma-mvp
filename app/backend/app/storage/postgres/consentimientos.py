"""Historial de consentimiento de comunicacion sobre PostgreSQL (DEC-MI-08).

``rma.consentimiento_comunicacion`` es inmutable: otorgar y revocar agregan
registros.
"""

from datetime import timezone

from app.domain.models.comunicaciones import ConsentimientoComunicacion
from app.repositories.exceptions import (
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
)

from .consultas import ESCRITURA, LECTURA, consulta
from .transaccion import UnidadDeTrabajoPostgres

_LISTAR = consulta(
    "consentimientos.listar",
    """
    SELECT c.finalidad, c.canal, c.otorgado, c.origen, u.codigo AS usuario,
           c.registrado_en
      FROM rma.consentimiento_comunicacion c
      JOIN rma.cliente k ON k.id = c.cliente_id
      JOIN rma.usuario u ON u.id = c.usuario_id
     WHERE k.codigo = %(cliente)s
     ORDER BY c.registrado_en, c.id
    """,
    modo=LECTURA,
)
_INSERTAR = consulta(
    "consentimientos.insertar",
    """
    INSERT INTO rma.consentimiento_comunicacion
        (cliente_id, finalidad, canal, otorgado, origen, usuario_id,
         registrado_en)
    SELECT k.id, %(finalidad)s, %(canal)s, %(otorgado)s, %(origen)s, u.id,
           %(fecha)s
      FROM rma.cliente k, rma.usuario u
     WHERE k.codigo = %(cliente)s AND u.codigo = %(usuario)s
    """,
    modo=ESCRITURA,
)


class PostgresConsentimientosRepository:
    def __init__(self, unidad: UnidadDeTrabajoPostgres) -> None:
        self._unidad = unidad

    def listar(self, cliente_id: str) -> list[ConsentimientoComunicacion]:
        with self._unidad.lectura() as lector:
            filas = lector.filas(_LISTAR, {"cliente": cliente_id})
        return [
            ConsentimientoComunicacion(
                cliente_id=cliente_id,
                finalidad=f.finalidad,
                canal=f.canal,
                otorgado=f.otorgado,
                origen=f.origen,
                usuario_id=f.usuario,
                fecha=f.registrado_en.astimezone(timezone.utc),
            )
            for f in filas
        ]

    def agregar(self, registro: ConsentimientoComunicacion) -> None:
        if not self._unidad.en_curso():
            raise PersistenciaError(
                "Registrar un consentimiento exige una transaccion."
            )
        insertadas = self._unidad.ejecutor().ejecutar(
            _INSERTAR,
            {
                "cliente": registro.cliente_id,
                "finalidad": registro.finalidad.value,
                "canal": registro.canal.value,
                "otorgado": registro.otorgado,
                "origen": registro.origen,
                "usuario": registro.usuario_id,
                "fecha": registro.fecha,
            },
        )
        if insertadas != 1:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe el cliente {registro.cliente_id}"
            )
