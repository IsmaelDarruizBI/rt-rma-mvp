"""Catalogos y actores minimos para ejecutar HP-REP-001 en memoria.

Datos ficticios de prueba. Los catalogos se pasan a los services como
parametros: todavia no hay repositories que los resuelvan.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.domain.models import (
    Cliente,
    Equipo,
    EstacionTrabajo,
    Insumo,
    RolUsuario,
    TipoReparacion,
    TipoReparacionEstacion,
    TipoReparacionInsumos,
    Usuario,
)

INICIO = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)


def t(minutos: int) -> datetime:
    """Momento relativo al inicio del escenario, para legibilidad."""
    return INICIO + timedelta(minutes=minutos)


# --- Catalogos ----------------------------------------------------------

TIPO_BATERIA = TipoReparacion(
    id="TREP-001",
    nombre="Cambio de bateria iPhone 14",
    precio=Decimal("80000"),
    puntaje=10,
    garantia_dias=90,
)

INSUMO_BATERIA = Insumo(
    id="INS-001",
    codigo="BAT-IP14",
    nombre="Bateria iPhone 14",
    stock_fisico=Decimal("2"),
)

INSUMOS = [INSUMO_BATERIA]

INSUMOS_PREVISTOS = [
    TipoReparacionInsumos(
        tipo_reparacion_id="TREP-001",
        insumo_id="INS-001",
        cantidad=Decimal("1"),
    )
]

ESTACION = EstacionTrabajo(id="EST-001", nombre="Estacion 1")

ESTACION_OTRA = EstacionTrabajo(id="EST-002", nombre="Estacion 2")

ESTACIONES = [ESTACION, ESTACION_OTRA]

# EST-002 existe y esta operativa, pero no esta habilitada para TREP-001.
COMPATIBILIDADES = [
    TipoReparacionEstacion(
        tipo_reparacion_id="TREP-001",
        estacion_id="EST-001",
    )
]


# --- Actores ------------------------------------------------------------

RECEPCION = Usuario(
    id="RECEP-001",
    nombre="Recepcion Uno",
    rol=RolUsuario.RECEPCION,
)

COORDINADOR = Usuario(
    id="COORD-001",
    nombre="Coordinador Uno",
    rol=RolUsuario.COORDINADOR_RMA,
)

TECNICO = Usuario(id="TECH-001", nombre="Tecnico Uno", rol=RolUsuario.TECNICO)

TECNICO_DOS = Usuario(
    id="TECH-002",
    nombre="Tecnico Dos",
    rol=RolUsuario.TECNICO,
)

ADMINISTRADOR = Usuario(
    id="ADMIN-001",
    nombre="Admin Uno",
    rol=RolUsuario.ADMINISTRADOR,
)


# --- Cliente y equipo ---------------------------------------------------

CLIENTE = Cliente(
    id="CLI-001",
    nombre_apellido="Cliente de Prueba",
    telefono="341-0000000",
    email="cliente.prueba@example.com",
)

EQUIPO = Equipo(
    id="EQP-001",
    marca="Apple",
    modelo="iPhone 14",
    falla_reportada="La bateria se descarga en pocas horas.",
    numero_serie="SN-PRUEBA-0001",
)
