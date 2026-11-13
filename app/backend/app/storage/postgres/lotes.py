"""Lotes de insumo sobre PostgreSQL (DEC-MI-10): ``rma.lote_insumo``,
inmutable. El saldo lo calcula ``rma.v_saldo_lote`` desde el libro; el
trigger del libro lo valida."""

from datetime import timezone

from app.domain.models.lotes import LoteInsumo
from app.repositories.exceptions import PersistenciaError

from .consultas import ESCRITURA, LECTURA, consulta
from .transaccion import UnidadDeTrabajoPostgres

_LISTAR = consulta(
    "lotes.listar",
    """
    SELECT l.codigo, i.clave AS insumo, l.numero, l.serie, l.origen,
           l.referencia, u.codigo AS usuario, l.registrado_en
      FROM rma.lote_insumo l
      JOIN rma.insumo i ON i.id = l.insumo_id
      JOIN rma.usuario u ON u.id = l.usuario_id
     WHERE i.clave = %(insumo)s
     ORDER BY l.registrado_en, l.codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_INSERTAR = consulta(
    "lotes.insertar",
    """
    INSERT INTO rma.lote_insumo
        (codigo, insumo_id, numero, serie, origen, referencia, usuario_id,
         registrado_en)
    SELECT %(codigo)s, i.id, %(numero)s, %(serie)s, %(origen)s,
           %(referencia)s, u.id, %(fecha)s
      FROM rma.insumo i, rma.usuario u
     WHERE i.clave = %(insumo)s AND u.codigo = %(usuario)s
    """,
    modo=ESCRITURA,
)


class PostgresLotesRepository:
    def __init__(self, unidad: UnidadDeTrabajoPostgres) -> None:
        self._unidad = unidad

    def listar(self, insumo_id: str) -> list[LoteInsumo]:
        with self._unidad.lectura() as lector:
            filas = lector.filas(_LISTAR, {"insumo": insumo_id})
        return [
            LoteInsumo(
                id=f.codigo,
                insumo_id=f.insumo,
                numero=f.numero,
                serie=f.serie,
                origen=f.origen,
                referencia=f.referencia,
                usuario_id=f.usuario,
                fecha=f.registrado_en.astimezone(timezone.utc),
            )
            for f in filas
        ]

    def agregar(self, lote: LoteInsumo) -> None:
        if not self._unidad.en_curso():
            raise PersistenciaError("Registrar un lote exige una transaccion.")
        insertadas = self._unidad.ejecutor().ejecutar(
            _INSERTAR,
            {
                "codigo": lote.id,
                "insumo": lote.insumo_id,
                "numero": lote.numero,
                "serie": lote.serie,
                "origen": lote.origen.value,
                "referencia": lote.referencia,
                "usuario": lote.usuario_id,
                "fecha": lote.fecha,
            },
        )
        if insertadas != 1:
            raise PersistenciaError(
                f"No se pudo registrar el lote {lote.numero} de "
                f"{lote.insumo_id}."
            )
