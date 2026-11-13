"""Reclamos de garantia rechazados en un archivo JSON (DEC-MI-02).

Un solo archivo con la lista, escrito de forma atomica dentro del lock de
proceso de la unidad de trabajo JSON (como las Ordenes).
"""

from pathlib import Path

from app.domain.models.reclamos import ReclamoGarantia
from app.repositories.exceptions import EntidadPersistidaNoEncontradaError

from .base import asegurar_directorio, escribir_json_atomico, leer_json


class JsonReclamosRepository:
    def __init__(self, directorio: Path) -> None:
        self._ruta = asegurar_directorio(directorio) / "reclamos.json"

    def _todos(self) -> list[ReclamoGarantia]:
        if not self._ruta.exists():
            return []
        return [
            ReclamoGarantia.model_validate(r) for r in leer_json(self._ruta)
        ]

    def siguiente_id(self) -> str:
        numeros = [int(r.id.split("-")[1]) for r in self._todos()]
        return f"RGA-{max(numeros, default=0) + 1:06d}"

    def guardar(self, reclamo: ReclamoGarantia) -> None:
        reclamos = [r for r in self._todos() if r.id != reclamo.id]
        reclamos.append(reclamo)
        reclamos.sort(key=lambda r: r.id)
        escribir_json_atomico(
            self._ruta, [r.model_dump(mode="json") for r in reclamos]
        )

    def obtener(self, reclamo_id: str) -> ReclamoGarantia:
        for reclamo in self._todos():
            if reclamo.id == reclamo_id:
                return reclamo
        raise EntidadPersistidaNoEncontradaError(
            f"No existe el reclamo {reclamo_id}"
        )

    def listar(self) -> list[ReclamoGarantia]:
        return sorted(self._todos(), key=lambda r: r.id, reverse=True)
