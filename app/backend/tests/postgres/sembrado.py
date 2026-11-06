"""Carga en PostgreSQL los mismos catalogos JSON que usa una prueba (E4).

Las pruebas de la API siembran ``<directorio>/catalogs/*.json``
(``tests/fixtures/api_salidas.sembrar``). Este modulo carga esos mismos
archivos en una base local, asi una Orden armada por la API en JSON
referencia en PostgreSQL los mismos usuarios, tipos, insumos y mesas.
Solo pruebas: escribe con el usuario administrador de la base local.
"""

import json
from decimal import Decimal
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
    # A6: lo que la reserva necesita leer de PostgreSQL.
    for relacion in _leer(directorio, "tipo_reparacion_insumos.json"):
        conexion.execute(
            "insert into rma.tipo_reparacion_insumo "
            "(tipo_reparacion_id, insumo_id, cantidad) "
            "select t.id, i.id, %s from rma.tipo_reparacion t, rma.insumo i "
            "where t.codigo = %s and i.clave = %s",
            (
                relacion["cantidad"],
                relacion["tipo_reparacion_id"],
                relacion["insumo_id"],
            ),
        )
    for relacion in _leer(directorio, "tipo_reparacion_estaciones.json"):
        conexion.execute(
            "insert into rma.mesa_tipo_reparacion "
            "(mesa_trabajo_id, tipo_reparacion_id) "
            "select m.id, t.id from rma.mesa_trabajo m, rma.tipo_reparacion t "
            "where m.codigo = %s and t.codigo = %s",
            (relacion["estacion_id"], relacion["tipo_reparacion_id"]),
        )
    # Un insumo nace sin stock: el del catalogo entra como INGRESO del libro.
    # Si los flujos ya lo movieron, el que tenia antes (corpus_ordenes).
    inicial = directorio / "insumos_iniciales.json"
    insumos = (
        json.loads(inicial.read_text(encoding="utf-8"))
        if inicial.exists()
        else _leer(directorio, "insumos.json")
    )
    for insumo in insumos:
        ingresar_stock(conexion, insumo["id"], insumo["stock_fisico"])


def ingresar_stock(conexion, clave: str, cantidad) -> None:
    """Un INGRESO de ``cantidad`` en el libro, con su accion del sistema."""
    if not Decimal(str(cantidad)) > 0:
        return
    accion = conexion.execute(
        "insert into rma.accion_usuario (proceso, operacion, resultado) "
        "values ('SISTEMA', 'STOCK_INICIAL_PRUEBA', 'CONFIRMADA') "
        "returning id"
    ).fetchone()[0]
    conexion.execute(
        "insert into rma.movimiento_inventario "
        "(codigo, tipo, insumo_id, cantidad, motivo_texto, accion_id) "
        "select 'ING-' || gen_random_uuid(), 'INGRESO', i.id, %s, "
        "'Stock inicial de prueba', %s from rma.insumo i where i.clave = %s",
        (cantidad, accion, clave),
    )


def fijar_stock(conexion, clave: str, cantidad) -> None:
    """Lleva el stock fisico a ``cantidad`` con un INGRESO o un
    AJUSTE_NEGATIVO del libro (con un motivo que aplique)."""
    actual = conexion.execute(
        "select stock_fisico from rma.insumo where clave = %s", (clave,)
    ).fetchone()[0]
    diferencia = Decimal(str(cantidad)) - actual
    if diferencia > 0:
        ingresar_stock(conexion, clave, diferencia)
    elif diferencia < 0:
        accion = conexion.execute(
            "insert into rma.accion_usuario (proceso, operacion, resultado) "
            "values ('SISTEMA', 'AJUSTE_PRUEBA', 'CONFIRMADA') returning id"
        ).fetchone()[0]
        conexion.execute(
            "insert into rma.movimiento_inventario "
            "(codigo, tipo, insumo_id, cantidad, motivo_ajuste_id, "
            " motivo_texto, usuario_id, accion_id) "
            "select 'AJ-' || gen_random_uuid(), 'AJUSTE_NEGATIVO', i.id, %s, "
            "(select id from rma.motivo_ajuste "
            " where aplica_a in ('NEGATIVO', 'AMBOS') "
            " order by codigo limit 1), "
            "'Ajuste de prueba', (select id from rma.usuario order by codigo "
            "limit 1), %s from rma.insumo i where i.clave = %s",
            (-diferencia, accion, clave),
        )
