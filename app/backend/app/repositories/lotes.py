"""Contrato de los lotes de insumo (DEC-MI-10). Solo crecen: un lote no se
modifica ni se borra; su saldo sale del libro de inventario."""

from typing import Protocol

from app.domain.models.lotes import LoteInsumo


class LotesRepository(Protocol):
    def listar(self, insumo_id: str) -> list[LoteInsumo]: ...

    def agregar(self, lote: LoteInsumo) -> None: ...
