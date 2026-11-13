"""Firmas de documentos sobre PostgreSQL (DEC-MI-06).

``rma.firma_documento`` es inmutable y referencia el documento emitido; no
toca la Orden, asi que admite firmas despues de la entrega.
"""

from datetime import timezone

from app.domain.models.firmas import FirmaDocumento
from app.repositories.exceptions import (
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
)

from .consultas import ESCRITURA, LECTURA, consulta
from .transaccion import UnidadDeTrabajoPostgres

_DE_LA_ORDEN = consulta(
    "firmas.de_la_orden",
    """
    SELECT f.codigo, o.codigo AS orden, d.codigo AS documento, f.forma,
           f.objeto_clave, f.tipo_contenido, f.tamano_bytes,
           u.codigo AS usuario, f.registrada_en, f.firmante
      FROM rma.firma_documento f
      JOIN rma.documento_emitido d ON d.id = f.documento_id
      JOIN rma.orden o ON o.id = d.orden_id
      JOIN rma.usuario u ON u.id = f.usuario_id
     WHERE o.codigo = %(orden)s
     ORDER BY f.registrada_en, f.codigo
    """,
    modo=LECTURA,
)
_INSERTAR = consulta(
    "firmas.insertar",
    """
    INSERT INTO rma.firma_documento
        (codigo, documento_id, forma, objeto_clave, tipo_contenido,
         tamano_bytes, usuario_id, registrada_en, firmante)
    SELECT %(codigo)s, d.id, %(forma)s, %(objeto)s, %(tipo)s, %(tamano)s,
           u.id, %(fecha)s, %(firmante)s
      FROM rma.documento_emitido d
      JOIN rma.orden o ON o.id = d.orden_id, rma.usuario u
     WHERE d.codigo = %(documento)s AND o.codigo = %(orden)s
       AND u.codigo = %(usuario)s
    ON CONFLICT (codigo) DO NOTHING
    """,
    modo=ESCRITURA,
)


class PostgresFirmasRepository:
    def __init__(self, unidad: UnidadDeTrabajoPostgres) -> None:
        self._unidad = unidad

    def de_la_orden(self, orden_id: str) -> list[FirmaDocumento]:
        with self._unidad.lectura() as lector:
            filas = lector.filas(_DE_LA_ORDEN, {"orden": orden_id})
        return [
            FirmaDocumento(
                id=f.codigo,
                orden_id=f.orden,
                documento_id=f.documento,
                forma=f.forma,
                objeto=f.objeto_clave,
                tipo_contenido=f.tipo_contenido,
                tamano_bytes=f.tamano_bytes,
                usuario_id=f.usuario,
                fecha=f.registrada_en.astimezone(timezone.utc),
                firmante=f.firmante,
            )
            for f in filas
        ]

    def agregar(self, firma: FirmaDocumento) -> None:
        if not self._unidad.en_curso():
            raise PersistenciaError(
                "Registrar una firma exige una transaccion."
            )
        insertadas = self._unidad.ejecutor().ejecutar(
            _INSERTAR,
            {
                "codigo": firma.id,
                "documento": firma.documento_id,
                "orden": firma.orden_id,
                "forma": firma.forma.value,
                "objeto": firma.objeto,
                "tipo": firma.tipo_contenido,
                "tamano": firma.tamano_bytes,
                "usuario": firma.usuario_id,
                "fecha": firma.fecha,
                "firmante": firma.firmante,
            },
        )
        if insertadas != 1:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe el documento {firma.documento_id}"
            )
