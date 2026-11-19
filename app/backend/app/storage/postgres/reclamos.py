"""Reclamos de garantia rechazados sobre PostgreSQL (DEC-MI-02).

``rma.reclamo_garantia``: el reclamo es inmutable salvo su continuacion
como reparacion paga, que se completa una sola vez (un trigger lo exige y
la Orden de continuacion es unica).
"""

import json
from datetime import timezone

from app.domain.models.reclamos import ReclamoGarantia
from app.repositories.exceptions import (
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
)

from .codigos import reservar_codigo
from .consultas import ESCRITURA, LECTURA, consulta
from .transaccion import UnidadDeTrabajoPostgres

_COLUMNAS = """
    SELECT r.codigo, o.codigo AS orden_origen, r.detalles, r.equipo,
           u.codigo AS usuario, r.registrado_en, r.vigencias,
           r.excepciones, r.resultado, r.motivo,
           oc.codigo AS orden_continuacion, uc.codigo AS continuado_por,
           r.continuado_en
      FROM rma.reclamo_garantia r
      JOIN rma.orden o ON o.id = r.orden_origen_id
      JOIN rma.usuario u ON u.id = r.usuario_id
      LEFT JOIN rma.orden oc ON oc.id = r.orden_continuacion_id
      LEFT JOIN rma.usuario uc ON uc.id = r.continuado_por
"""
_RECLAMOS = consulta(
    "reclamos.listar",
    _COLUMNAS + " ORDER BY r.codigo DESC",
    modo=LECTURA,
)
_RECLAMO = consulta(
    "reclamos.obtener",
    _COLUMNAS + " WHERE r.codigo = %(codigo)s",
    modo=LECTURA,
)
_INSERTAR = consulta(
    "reclamos.insertar",
    """
    INSERT INTO rma.reclamo_garantia
        (codigo, orden_origen_id, detalles, equipo, usuario_id,
         registrado_en, vigencias, excepciones, resultado, motivo)
    SELECT %(codigo)s, o.id, %(detalles)s::jsonb, %(equipo)s::jsonb, u.id,
           %(fecha)s, %(vigencias)s::jsonb, %(excepciones)s::jsonb,
           %(resultado)s, %(motivo)s
      FROM rma.orden o, rma.usuario u
     WHERE o.codigo = %(orden)s AND u.codigo = %(usuario)s
    ON CONFLICT (codigo) DO NOTHING
    """,
    modo=ESCRITURA,
)
_CONTINUAR = consulta(
    "reclamos.continuar",
    """
    UPDATE rma.reclamo_garantia r
       SET orden_continuacion_id = o.id, continuado_por = u.id,
           continuado_en = %(fecha)s
      FROM rma.orden o, rma.usuario u
     WHERE r.codigo = %(codigo)s AND r.orden_continuacion_id IS NULL
       AND o.codigo = %(orden)s AND u.codigo = %(usuario)s
    """,
    modo=ESCRITURA,
)


def _reclamo(f) -> ReclamoGarantia:
    return ReclamoGarantia(
        id=f.codigo,
        orden_origen_id=f.orden_origen,
        detalles_reclamados=list(f.detalles),
        equipo=f.equipo,
        usuario_id=f.usuario,
        fecha=f.registrado_en.astimezone(timezone.utc),
        vigencias=f.vigencias,
        excepciones_pedidas=f.excepciones,
        resultado=f.resultado,
        motivo=f.motivo,
        orden_continuacion_id=f.orden_continuacion,
        continuado_por=f.continuado_por,
        continuado_en=(
            f.continuado_en.astimezone(timezone.utc)
            if f.continuado_en
            else None
        ),
    )


class PostgresReclamosRepository:
    def __init__(self, unidad: UnidadDeTrabajoPostgres) -> None:
        self._unidad = unidad

    def siguiente_id(self) -> str:
        """CFG-01: ``RGA-NNNNNN`` generado por la base dentro de la
        transaccion del alta (antes max+1, no seguro ante concurrencia)."""
        if not self._unidad.en_curso():
            raise PersistenciaError(
                "Numerar un reclamo exige una transaccion."
            )
        return reservar_codigo(self._unidad, "RGA")

    def guardar(self, reclamo: ReclamoGarantia) -> None:
        if not self._unidad.en_curso():
            raise PersistenciaError(
                "Guardar un reclamo exige una transaccion."
            )
        ejecutor = self._unidad.ejecutor()
        if reclamo.orden_continuacion_id is None:
            insertadas = ejecutor.ejecutar(
                _INSERTAR,
                {
                    "codigo": reclamo.id,
                    "orden": reclamo.orden_origen_id,
                    "detalles": json.dumps(reclamo.detalles_reclamados),
                    "equipo": reclamo.equipo.model_dump_json(),
                    "usuario": reclamo.usuario_id,
                    "fecha": reclamo.fecha,
                    "vigencias": json.dumps(
                        [v.model_dump(mode="json") for v in reclamo.vigencias]
                    ),
                    "excepciones": json.dumps(reclamo.excepciones_pedidas),
                    "resultado": reclamo.resultado.value,
                    "motivo": reclamo.motivo,
                },
            )
            if insertadas != 1:
                raise PersistenciaError(f"Ya existe el reclamo {reclamo.id}.")
            return
        actualizadas = ejecutor.ejecutar(
            _CONTINUAR,
            {
                "codigo": reclamo.id,
                "orden": reclamo.orden_continuacion_id,
                "usuario": reclamo.continuado_por,
                "fecha": reclamo.continuado_en,
            },
        )
        if actualizadas != 1:
            raise PersistenciaError(
                f"El reclamo {reclamo.id} ya se continuo o no existe."
            )

    def obtener(self, reclamo_id: str) -> ReclamoGarantia:
        with self._unidad.lectura() as lector:
            fila = lector.fila(_RECLAMO, {"codigo": reclamo_id})
        if fila is None:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe el reclamo {reclamo_id}"
            )
        return _reclamo(fila)

    def listar(self) -> list[ReclamoGarantia]:
        with self._unidad.lectura() as lector:
            return [_reclamo(f) for f in lector.filas(_RECLAMOS)]
