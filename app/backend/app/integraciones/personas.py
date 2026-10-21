"""Fuente externa de datos de personas por DNI (MVP v2, UAT-010).

Contrato para consultar nombre y apellido a una fuente AUTORIZADA (por
ejemplo, el padron de ARCA por web service, con certificado, o un
proveedor contratado). Hoy no hay ninguna configurada: CUIT Online
protege los nombres de sus resultados (texto codificado dentro de
contenido de pago, con medicion por huella del navegador) y extraerlos
exigiria eludir esa proteccion, asi que no se implementa
(``traceability/IMPLEMENTATION.md``).

Una fuente devuelve solo lo necesario para el formulario: el nombre
completo (``nombre_apellido``), nunca HTML ni la respuesta completa. No se
separa en nombre y apellido: Recepcion lo revisa y lo confirma. Si la
fuente los da por separado, el adaptador los une tal como vienen.
"""

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


class EstadoFuente:
    ENCONTRADO = "ENCONTRADO"
    SIN_RESULTADOS = "SIN_RESULTADOS"
    AMBIGUO = "AMBIGUO"
    # La fuente no respondio, cambio su formato o rechazo la consulta.
    NO_DISPONIBLE = "NO_DISPONIBLE"


@dataclass(frozen=True)
class PersonaExterna:
    """Una persona segun la fuente: solo lo que usa el formulario."""

    nombre_apellido: str


@dataclass(frozen=True)
class ResultadoFuente:
    estado: str
    personas: tuple[PersonaExterna, ...] = field(default_factory=tuple)
    detalle: str | None = None


class FuentePersonas(Protocol):
    """Una fuente autorizada de datos de personas por DNI."""

    nombre: str

    def consultar(self, dni: str) -> ResultadoFuente: ...


class LimitadorConsultas:
    """Frena las consultas externas: un intervalo minimo entre dos y un
    maximo por minuto (para todo el proceso). No hay busquedas masivas:
    cada consulta la pide una persona desde el formulario."""

    def __init__(
        self,
        *,
        intervalo_minimo: float = 2.0,
        maximo_por_minuto: int = 10,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._intervalo = intervalo_minimo
        self._maximo = maximo_por_minuto
        self._reloj = reloj
        self._recientes: deque[float] = deque()
        self._lock = threading.Lock()

    def permitir(self) -> bool:
        """Registra la consulta si esta dentro de los limites."""
        with self._lock:
            ahora = self._reloj()
            while self._recientes and ahora - self._recientes[0] >= 60:
                self._recientes.popleft()
            if self._recientes and (
                ahora - self._recientes[-1] < self._intervalo
            ):
                return False
            if len(self._recientes) >= self._maximo:
                return False
            self._recientes.append(ahora)
            return True
