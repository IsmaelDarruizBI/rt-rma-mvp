"""Buscar los datos de un cliente por DNI (MVP v2, UAT-010).

    buscar_cliente_por_dni   1. nuestras Ordenes (cliente ya conocido)
                             2. si no esta y hay una fuente externa
                                autorizada configurada: esa fuente, con
                                limite de consultas
                             3. si no: se carga a mano

Solo lee: no guarda nada. Recepcion revisa y corrige el resultado antes de
crear la Orden, y la carga manual siempre sigue disponible.
"""

from dataclasses import dataclass, field

from app.domain.models import RolUsuario
from app.integraciones import EstadoFuente, PersonaExterna
from app.services import (
    ClienteConocido,
    clientes_con_dni,
    normalizar_dni,
    validar_alguno_de,
)

from .contexto import ApplicationContext

ROLES_BUSQUEDA_CLIENTE = (RolUsuario.RECEPCION, RolUsuario.ADMINISTRADOR)


class EstadoBusqueda:
    ENCONTRADO = "ENCONTRADO"
    AMBIGUO = "AMBIGUO"
    SIN_RESULTADOS = "SIN_RESULTADOS"
    NO_DISPONIBLE = "NO_DISPONIBLE"
    LIMITE = "LIMITE"
    # Ninguna fuente externa autorizada configurada.
    NO_HABILITADA = "NO_HABILITADA"


ORIGEN_BASE = "BASE"
ORIGEN_EXTERNO = "EXTERNO"


@dataclass(frozen=True)
class BusquedaCliente:
    dni: str
    estado: str
    mensaje: str
    origen: str | None = None
    conocidos: tuple[ClienteConocido, ...] = field(default_factory=tuple)
    externos: tuple[PersonaExterna, ...] = field(default_factory=tuple)
    fuente: str | None = None


def buscar_cliente_por_dni(
    contexto: ApplicationContext,
    *,
    dni: str,
    usuario_id: str,
    incluir_externa: bool = True,
) -> BusquedaCliente:
    """Primero nuestra base; despues, solo si hay, una fuente autorizada.

    ``incluir_externa=False``: solo nuestra base (la comprobacion previa al
    crear una Orden no consulta afuera).
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    validar_alguno_de(usuario, ROLES_BUSQUEDA_CLIENTE)
    dni = normalizar_dni(dni)

    conocidos = tuple(clientes_con_dni(contexto.ordenes.listar(), dni))
    if len(conocidos) == 1:
        return BusquedaCliente(
            dni=dni,
            estado=EstadoBusqueda.ENCONTRADO,
            origen=ORIGEN_BASE,
            conocidos=conocidos,
            mensaje="Ya es cliente: revisá sus datos antes de usarlos.",
        )
    if conocidos:
        return BusquedaCliente(
            dni=dni,
            estado=EstadoBusqueda.AMBIGUO,
            origen=ORIGEN_BASE,
            conocidos=conocidos,
            mensaje="Hay más de un cliente con ese DNI: elegí el correcto.",
        )

    if not incluir_externa:
        return BusquedaCliente(
            dni=dni,
            estado=EstadoBusqueda.SIN_RESULTADOS,
            mensaje="No está en nuestra base.",
        )
    fuente = contexto.fuente_personas
    if fuente is None:
        return BusquedaCliente(
            dni=dni,
            estado=EstadoBusqueda.NO_HABILITADA,
            mensaje=(
                "No está en nuestra base y no hay una fuente externa "
                "habilitada: cargá el nombre y apellido a mano."
            ),
        )
    if not contexto.limitador_personas.permitir():
        return BusquedaCliente(
            dni=dni,
            estado=EstadoBusqueda.LIMITE,
            fuente=fuente.nombre,
            mensaje="Demasiadas búsquedas seguidas: esperá unos segundos.",
        )
    try:
        resultado = fuente.consultar(dni)
    except Exception:  # una fuente caida no rompe el alta
        resultado = None
    if resultado is None or resultado.estado == EstadoFuente.NO_DISPONIBLE:
        return BusquedaCliente(
            dni=dni,
            estado=EstadoBusqueda.NO_DISPONIBLE,
            fuente=fuente.nombre,
            mensaje=(
                "La fuente externa no respondió: cargá el nombre y apellido "
                "a mano."
            ),
        )
    if not resultado.personas:
        return BusquedaCliente(
            dni=dni,
            estado=EstadoBusqueda.SIN_RESULTADOS,
            fuente=fuente.nombre,
            mensaje=(
                "La fuente externa no tiene datos para ese DNI: cargá el "
                "nombre y apellido a mano."
            ),
        )
    unica = len(resultado.personas) == 1
    return BusquedaCliente(
        dni=dni,
        estado=EstadoBusqueda.ENCONTRADO if unica else EstadoBusqueda.AMBIGUO,
        origen=ORIGEN_EXTERNO,
        externos=resultado.personas,
        fuente=fuente.nombre,
        mensaje=(
            "Revisá y corregí el nombre y apellido antes de usarlo."
            if unica
            else "Más de un resultado: elegí el correcto y revisalo."
        ),
    )
