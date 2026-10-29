"""Genera el catalogo tecnico de modelos de equipo desde una exportacion
de Ventas (``raw_TipoProducto`` como CSV). Herramienta de UNA vez: la
aplicacion nunca lee Ventas para este catalogo.

    python -m scripts.generar_modelos_equipo RUTA_CSV [--salida ARCHIVO]

Desde ``app/backend``. Por defecto escribe ``app/datos/modelos_equipo.json``
e imprime que incluyo y que descarto. El CSV tiene precios y emails: no
se versiona ni se copia, solo se lee.

Que genera: un modelo por marca, modelo y variante de los iPhone (sin
capacidad ni color, que no identifican el tipo de equipo). Las demas
categorias de Ventas no tienen el modelo estructurado y quedan para la
carga manual.

IDs estables: un modelo que ya esta en el archivo de salida conserva su
ID (y sus ``numeros_modelo`` y ``activo``, que se cargan a mano); los
nuevos toman el siguiente numero. Un modelo que ya no aparece en Ventas
se conserva tal cual: el catalogo nunca borra. Regenerar con los mismos
datos deja el archivo identico.
"""

import argparse
import json
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import MODELOS_EQUIPO_POR_DEFECTO
from app.domain.models import ModeloEquipo, ProductoInformado
from app.integraciones.catalogo import FiltroCatalogo
from app.integraciones.catalogo.archivo import ProveedorCatalogoArchivo

MARCA = "Apple"
CATEGORIA = "IPHONE"
FILTRO = FiltroCatalogo(("IPHONE NUEVOS", "IPHONE USADOS"))

# Lineas que no se incorporan todavia (no se borran del origen).
MODELOS_EXCLUIDOS = {
    "iPhone 18": "pendiente de verificar sus denominaciones y variantes",
}

# La variante «E» de Ventas es parte del nombre comercial: «iPhone 16e».
VARIANTES_EN_EL_NOMBRE = {"e": "e"}

# Orden de las variantes dentro de un modelo (las demas, al final).
ORDEN_VARIANTES = ("", "mini", "e", "plus", "air", "max", "pro", "pro max")


@dataclass(frozen=True)
class Descartado:
    tipo_producto_id: str
    descripcion: str
    motivo: str


@dataclass
class Informe:
    incluidos: list[ModeloEquipo] = field(default_factory=list)
    nuevos: list[str] = field(default_factory=list)
    conservados_sin_origen: list[str] = field(default_factory=list)
    # Modelo excluido -> motivo y cuantas filas tenia.
    excluidos: dict[str, tuple[str, int]] = field(default_factory=dict)
    descartados: list[Descartado] = field(default_factory=list)


def _clave(marca: str, modelo: str, variante: str | None) -> tuple:
    return (marca.casefold(), modelo.casefold(), (variante or "").casefold())


def _natural(texto: str) -> tuple:
    return tuple(
        (0, int(parte), "") if parte.isdigit() else (1, 0, parte.casefold())
        for parte in re.findall(r"\d+|\D+", texto)
    )


def _orden(modelo: ModeloEquipo) -> tuple:
    variante = (modelo.variante or "").casefold()
    rango = (
        ORDEN_VARIANTES.index(variante)
        if variante in ORDEN_VARIANTES
        else len(ORDEN_VARIANTES)
    )
    # «iPhone 16e» va con el 16, despues del estandar.
    base = re.sub(r"(\d)e$", r"\1", modelo.modelo)
    sufijo = modelo.modelo[len(base) :]
    return (
        modelo.marca.casefold(),
        _natural(base),
        rango,
        sufijo,
        variante,
    )


def modelo_de_producto(
    producto: ProductoInformado,
) -> tuple[str, str, str | None] | None:
    """Linea, modelo y variante de un iPhone de Ventas («iPhone 16»,
    «iPhone 16e», ``None``), o ``None`` si le falta el modelo
    (``tp_number``)."""
    numero = producto.valores_origen.get("tp_number", "").strip()
    if not numero:
        return None
    linea = f"iPhone {numero}"
    variante = producto.variante
    sufijo = VARIANTES_EN_EL_NOMBRE.get((variante or "").casefold())
    if sufijo is not None:
        return linea, f"{linea}{sufijo}", None
    return linea, linea, variante


def generar(
    productos: Iterable[ProductoInformado],
    existentes: Sequence[ModeloEquipo] = (),
) -> Informe:
    """El catalogo a partir de los productos de Ventas y del anterior."""
    informe = Informe()
    encontrados: dict[tuple, tuple[str, str | None]] = {}
    incompletos: list[ProductoInformado] = []
    for producto in productos:
        if producto.generador or producto.categoria != CATEGORIA:
            continue
        resultado = modelo_de_producto(producto)
        if resultado is None:
            incompletos.append(producto)
            continue
        linea, modelo, variante = resultado
        if linea in MODELOS_EXCLUIDOS:
            motivo, filas = informe.excluidos.get(
                linea, (MODELOS_EXCLUIDOS[linea], 0)
            )
            informe.excluidos[linea] = (motivo, filas + 1)
            continue
        encontrados.setdefault(
            _clave(MARCA, modelo, variante), (modelo, variante)
        )

    nombres = sorted(
        {f"{MARCA} {modelo}".casefold() for modelo, _ in encontrados.values()},
        key=len,
        reverse=True,
    )
    for producto in incompletos:
        texto = f"{MARCA} {producto.descripcion}".casefold()
        representado = next(
            (
                nombre
                for nombre in nombres
                if texto == nombre or texto.startswith(nombre + " ")
            ),
            None,
        )
        excluida = next(
            (
                linea
                for linea in MODELOS_EXCLUIDOS
                if producto.descripcion.casefold().startswith(
                    linea.casefold() + " "
                )
            ),
            None,
        )
        if representado:
            motivo = f"ya representado por «{representado}»"
        elif excluida:
            motivo = f"de la linea excluida {excluida}"
        else:
            motivo = "NO representado: revisar"
        informe.descartados.append(
            Descartado(
                producto.tipo_producto_id,
                producto.descripcion,
                f"sin modelo (tp_number); {motivo}",
            )
        )

    previos = {_clave(m.marca, m.modelo, m.variante): m for m in existentes}
    siguiente = 1 + max(
        (int(m.id.removeprefix("MOD-")) for m in existentes), default=0
    )
    modelos: list[ModeloEquipo] = []
    candidatos = sorted(
        (
            ModeloEquipo(
                id="MOD-0000", marca=MARCA, modelo=modelo, variante=variante
            )
            for modelo, variante in encontrados.values()
        ),
        key=_orden,
    )
    for candidato in candidatos:
        clave = _clave(candidato.marca, candidato.modelo, candidato.variante)
        previo = previos.pop(clave, None)
        if previo is not None:
            modelos.append(previo)
            continue
        nuevo = candidato.model_copy(update={"id": f"MOD-{siguiente:04d}"})
        siguiente += 1
        modelos.append(nuevo)
        informe.nuevos.append(nuevo.id)
    # Lo que ya no informa Ventas se conserva tal cual: nunca se borra.
    for previo in previos.values():
        modelos.append(previo)
        informe.conservados_sin_origen.append(previo.id)
    informe.incluidos = sorted(modelos, key=_orden)
    return informe


def a_json(modelos: Sequence[ModeloEquipo]) -> str:
    """Todos los campos, siempre en el mismo orden (el de ``ModeloEquipo``):
    regenerar con los mismos datos da el mismo archivo."""
    registros = [modelo.model_dump(mode="json") for modelo in modelos]
    return json.dumps(registros, ensure_ascii=False, indent=2) + "\n"


def leer_existentes(ruta: Path) -> list[ModeloEquipo]:
    if not ruta.is_file():
        return []
    return [
        ModeloEquipo.model_validate(registro)
        for registro in json.loads(ruta.read_text(encoding="utf-8"))
    ]


def main(argumentos: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv", type=Path)
    parser.add_argument(
        "--salida", type=Path, default=MODELOS_EQUIPO_POR_DEFECTO
    )
    opciones = parser.parse_args(argumentos)

    lectura = ProveedorCatalogoArchivo(
        opciones.csv, marcas={CATEGORIA: MARCA}
    ).leer(FILTRO)
    informe = generar(lectura.productos, leer_existentes(opciones.salida))
    opciones.salida.parent.mkdir(parents=True, exist_ok=True)
    opciones.salida.write_bytes(a_json(informe.incluidos).encode("utf-8"))

    print(f"Filas leidas: {lectura.leidos}; iPhone: {lectura.filtrados}")
    print(f"Modelos en el catalogo: {len(informe.incluidos)}")
    for modelo in informe.incluidos:
        print(f"  {modelo.id}  {modelo.nombre}")
    print(f"Nuevos: {len(informe.nuevos)}")
    if informe.conservados_sin_origen:
        print(
            "Conservados aunque Ventas ya no los informa: "
            + ", ".join(informe.conservados_sin_origen)
        )
    for modelo, (motivo, filas) in informe.excluidos.items():
        print(f"Excluido: {modelo} ({filas} filas): {motivo}")
    for descartado in informe.descartados:
        print(
            f"Descartada: {descartado.tipo_producto_id} "
            f"«{descartado.descripcion}»: {descartado.motivo}"
        )
    print(f"Escrito: {opciones.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
