"""Busqueda de clientes por DNI (MVP v2, UAT-010).

El MVP no tiene padron de clientes: los clientes viven dentro de sus
Ordenes. Buscar por DNI primero mira esas Ordenes (``clientes_con_dni``);
solo si no aparece, la capa de aplicacion puede consultar una fuente
externa autorizada. Nada se guarda en la busqueda: Recepcion revisa el
resultado, lo corrige si hace falta y recien entonces crea la Orden.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from app.domain.models import Cliente, OrdenReparacion

from .exceptions import PrecondicionInvalidaError


class ClienteExistenteError(PrecondicionInvalidaError):
    """Ya hay otro cliente con ese DNI: se reutiliza, no se duplica."""

    codigo = "CLIENTE_EXISTENTE"


# DNI argentino: 7 u 8 digitos (sin puntos). Se aceptan puntos, espacios o
# guiones al escribirlo.
_SEPARADORES = re.compile(r"[\s.\-]")
_DNI = re.compile(r"\d{7,8}")


def normalizar_dni(texto: str | None) -> str:
    """El DNI solo con digitos, o un error si no es un DNI valido.

    Sin ceros a la izquierda de mas: "07.123.456" y "7123456" son el mismo
    documento.
    """
    limpio = _SEPARADORES.sub("", texto or "")
    if not _DNI.fullmatch(limpio):
        raise PrecondicionInvalidaError(
            "El DNI debe tener 7 u 8 digitos (sin letras)."
        )
    sin_ceros = limpio.lstrip("0")
    if len(sin_ceros) < 7:
        raise PrecondicionInvalidaError(
            "El DNI debe tener 7 u 8 digitos (sin letras)."
        )
    return sin_ceros


def dni_opcional(texto: str | None) -> str | None:
    """Para el alta: sin DNI es valido (carga manual); con DNI, se valida."""
    if texto is None or not texto.strip():
        return None
    return normalizar_dni(texto)


@dataclass(frozen=True)
class ClienteConocido:
    """Un cliente que ya tiene Ordenes con ese DNI (el dato mas reciente)."""

    cliente_id: str
    nombre_apellido: str
    telefono: str
    email: str | None
    ultima_orden_id: str
    ultima_fecha: datetime
    ordenes: int


def clientes_con_dni(
    ordenes: Iterable[OrdenReparacion], dni: str
) -> list[ClienteConocido]:
    """Clientes de nuestras Ordenes con ese DNI, el mas reciente primero.

    Agrupa por ID de cliente y toma los datos de su Orden mas reciente.
    Mas de uno (por ejemplo, un DNI cargado con otro cliente) es ambiguo:
    Recepcion elige.
    """
    por_cliente: dict[str, list[OrdenReparacion]] = {}
    for orden in ordenes:
        cliente = orden.cliente
        if cliente is not None and cliente.dni == dni:
            por_cliente.setdefault(cliente.id, []).append(orden)
    conocidos = []
    for cliente_id, del_cliente in por_cliente.items():
        # Desempata por numero de Orden (correlativo): dos altas en el mismo
        # instante igual tienen un orden.
        ultima = max(
            del_cliente, key=lambda orden: (orden.created_at, orden.id)
        )
        conocidos.append(
            ClienteConocido(
                cliente_id=cliente_id,
                nombre_apellido=ultima.cliente.nombre_apellido,
                telefono=ultima.cliente.telefono,
                email=ultima.cliente.email,
                ultima_orden_id=ultima.id,
                ultima_fecha=ultima.created_at,
                ordenes=len(del_cliente),
            )
        )
    return sorted(
        conocidos,
        key=lambda conocido: (conocido.ultima_fecha, conocido.ultima_orden_id),
        reverse=True,
    )


def cliente_para_orden(
    ordenes: Iterable[OrdenReparacion],
    *,
    cliente: Cliente,
    reutilizado: bool,
) -> Cliente:
    """El cliente de una Orden nueva, sin duplicar uno que ya existe.

    ``reutilizado``: Recepcion eligio un cliente conocido (viene su ID) y
    sus datos pueden traer correcciones. Sin DNI no hay como reconocerlo.
    Con DNI:

    - nuevo (sin ID) y ese DNI ya es de un cliente: se rechaza para que se
      reutilice ese cliente (o se corrija el DNI), nunca se duplica;
    - reutilizado con un DNI que es de OTRO cliente: tambien se rechaza.
      Si el DNI cambio y nadie mas lo tiene, es una correccion.
    """
    if cliente.dni is None:
        return cliente
    con_ese_dni = clientes_con_dni(ordenes, cliente.dni)
    ids = {conocido.cliente_id for conocido in con_ese_dni}
    if not ids or (reutilizado and cliente.id in ids):
        return cliente
    otro = con_ese_dni[0]
    raise ClienteExistenteError(
        f"Ya existe un cliente con el DNI {cliente.dni} "
        f"({otro.nombre_apellido}): usá sus datos con «Buscar datos» o "
        "corregí el DNI."
    )
