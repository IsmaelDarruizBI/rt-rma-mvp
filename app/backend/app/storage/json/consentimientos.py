"""Historial de consentimiento de comunicacion en un archivo JSON
(DEC-MI-08). Solo se agregan registros; se escribe de forma atomica dentro
del lock de la unidad de trabajo JSON."""

from pathlib import Path

from app.domain.models.comunicaciones import ConsentimientoComunicacion

from .base import asegurar_directorio, escribir_json_atomico, leer_json


class JsonConsentimientosRepository:
    def __init__(self, directorio: Path) -> None:
        self._ruta = asegurar_directorio(directorio) / "consentimientos.json"

    def _todos(self) -> list[ConsentimientoComunicacion]:
        if not self._ruta.exists():
            return []
        return [
            ConsentimientoComunicacion.model_validate(r)
            for r in leer_json(self._ruta)
        ]

    def listar(self, cliente_id: str) -> list[ConsentimientoComunicacion]:
        return [r for r in self._todos() if r.cliente_id == cliente_id]

    def agregar(self, registro: ConsentimientoComunicacion) -> None:
        registros = [*self._todos(), registro]
        escribir_json_atomico(
            self._ruta, [r.model_dump(mode="json") for r in registros]
        )
