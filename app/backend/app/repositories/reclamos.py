"""Contrato de los reclamos de garantia rechazados (DEC-MI-02)."""

from typing import Protocol

from app.domain.models.reclamos import ReclamoGarantia


class ReclamosRepository(Protocol):
    def siguiente_id(self) -> str:
        """``RGA-000001``, ``RGA-000002``... dentro de la transaccion."""
        ...

    def guardar(self, reclamo: ReclamoGarantia) -> None:
        """Alta del reclamo, o su continuacion (lo unico que cambia)."""
        ...

    def obtener(self, reclamo_id: str) -> ReclamoGarantia: ...

    def listar(self) -> list[ReclamoGarantia]:
        """Del mas reciente al mas antiguo."""
        ...
