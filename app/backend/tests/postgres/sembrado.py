"""Carga en PostgreSQL los mismos catalogos JSON que usa una prueba (E4).

Las pruebas de la API siembran ``<directorio>/catalogs/*.json``
(``tests/fixtures/api_salidas.sembrar``). Este modulo carga esos mismos
archivos en una base local, asi una Orden armada por la API en JSON
referencia en PostgreSQL los mismos usuarios, tipos, insumos y mesas.
Solo pruebas: escribe con el usuario administrador de la base local.
"""

import json
from pathlib import Path

ROL_DE = {
    "RECEPCION": "RECEPCION",
    "TECNICO": "TECNICO",
    "COORDINADOR_RMA": "COORDINADOR_RMA",
    "ADMINISTRADOR": "ADMINISTRADOR",
}


def _leer(directorio: Path, nombre: str) -> list[dict]:
    ruta = directorio / "catalogs" / nombre
    return (
        json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else []
    )


def sembrar_catalogos(conexion, directorio: Path) -> None:
    """Usuarios (con su rol), tipos de reparacion, insumos y mesas."""
    for orden, usuario in enumerate(_leer(directorio, "usuarios.json"), 1):
        conexion.execute(
            "insert into rma.usuario (codigo, nombre, activo, orden) "
            "values (%s, %s, %s, %s)",
            (
                usuario["id"],
                usuario["nombre"],
                usuario.get("activo", True),
                orden,
            ),
        )
        conexion.execute(
            "insert into rma.usuario_rol (usuario_id, rol_id) "
            "select u.id, r.id from rma.usuario u, rma.rol r "
            "where u.codigo = %s and r.codigo = %s",
            (usuario["id"], ROL_DE[usuario["rol"]]),
        )
    for tipo in _leer(directorio, "tipos_reparacion.json"):
        conexion.execute(
            "insert into rma.tipo_reparacion "
            "(codigo, nombre, precio, puntaje, garantia_dias, activo) "
            "values (%s, %s, %s, %s, %s, %s)",
            (
                tipo["id"],
                tipo["nombre"],
                tipo["precio"],
                tipo["puntaje"],
                tipo["garantia_dias"],
                tipo.get("activo", True),
            ),
        )
    for insumo in _leer(directorio, "insumos.json"):
        conexion.execute(
            "insert into rma.insumo (clave, codigo, nombre, activo) "
            "values (%s, %s, %s, %s)",
            (
                insumo["id"],
                insumo["codigo"],
                insumo["nombre"],
                insumo.get("activo", True),
            ),
        )
    for estacion in _leer(directorio, "estaciones.json"):
        conexion.execute(
            "insert into rma.mesa_trabajo (codigo, nombre, activa) "
            "values (%s, %s, %s)",
            (estacion["id"], estacion["nombre"], estacion.get("activa", True)),
        )
