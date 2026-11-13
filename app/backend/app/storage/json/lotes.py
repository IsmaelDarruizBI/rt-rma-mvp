"""Lotes de insumo en un archivo JSON (DEC-MI-10). En la demo JSON los
insumos no se configuran por lote (DC23), asi que queda vacio; existe para
que el codigo sea el mismo en los dos modos."""

from pathlib import Path

from app.domain.models.lotes import LoteInsumo

from .base import asegurar_directorio, escribir_json_atomico, leer_json


class JsonLotesRepository:
    def __init__(self, directorio: Path) -> None:
        self._ruta = asegurar_directorio(directorio) / "lotes.json"

    def _todos(self) -> list[LoteInsumo]:
        if not self._ruta.exists():
            return []
        return [LoteInsumo.model_validate(r) for r in leer_json(self._ruta)]

    def listar(self, insumo_id: str) -> list[LoteInsumo]:
        return [lote for lote in self._todos() if lote.insumo_id == insumo_id]

    def agregar(self, lote: LoteInsumo) -> None:
        lotes = [*self._todos(), lote]
        escribir_json_atomico(
            self._ruta, [lote.model_dump(mode="json") for lote in lotes]
        )
