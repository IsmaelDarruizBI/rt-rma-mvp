"""Firmas de documentos en un archivo JSON (DEC-MI-06). Solo se agregan;
se escribe de forma atomica dentro del lock de la unidad de trabajo JSON."""

from pathlib import Path

from app.domain.models.firmas import FirmaDocumento

from .base import asegurar_directorio, escribir_json_atomico, leer_json


class JsonFirmasRepository:
    def __init__(self, directorio: Path) -> None:
        self._ruta = asegurar_directorio(directorio) / "firmas.json"

    def _todas(self) -> list[FirmaDocumento]:
        if not self._ruta.exists():
            return []
        return [
            FirmaDocumento.model_validate(r) for r in leer_json(self._ruta)
        ]

    def de_la_orden(self, orden_id: str) -> list[FirmaDocumento]:
        return [f for f in self._todas() if f.orden_id == orden_id]

    def agregar(self, firma: FirmaDocumento) -> None:
        firmas = [*self._todas(), firma]
        escribir_json_atomico(
            self._ruta, [f.model_dump(mode="json") for f in firmas]
        )
