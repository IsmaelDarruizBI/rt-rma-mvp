"""Genera los CSV ficticios de Reparacion RT (etapa 1, tarea 1.8).

Escribe en ``--destino``:

- ``producto.csv``: la tabla Producto con sus 31 columnas reales, en su
  orden, y los casos de la seccion 8 del diseño
  (docs/reparacion-rt-discovery.md): las 5 sedes y una no confirmada,
  otros estados y variantes de «Reparacion», sin IMEI, IMEI invalido, en
  notacion cientifica y repetido, ``producto_id`` vacio y repetido,
  TipoProducto inexistente y eliminado, eliminado en Gestion RT y una fecha
  de alta que no se puede interpretar.
- ``tipo_producto.csv``: la tabla TipoProducto ficticia.

Ningun dato real: IMEI con prefijo de prueba y digito verificador valido;
``producto_passcode``, documento, precios y datos de personas con el valor
fijo ``NO-LEER-FICTICIO`` (sirve para comprobar que nunca se leen). Los
mismos datos que usan las pruebas (``tests/fixtures/productos_rt.py``).

Sirven para el adaptador ``archivo`` (``RMA_PRODUCTOS_RT_ORIGEN=archivo``)
y para cargar la PLANILLA DE PRUEBA del UAT (importar ``producto.csv`` en
una hoja nueva). Nunca la planilla real de Gestion RT.

    app/backend/.venv/Scripts/python supabase/scripts/validacion_uat/generar_productos_rt_ficticios.py --destino <carpeta>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
BACKEND = RAIZ / "app" / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--destino", type=Path, required=True)
    argumentos = parser.parse_args()

    from tests.fixtures import productos_rt as ficticios

    destino: Path = argumentos.destino
    destino.mkdir(parents=True, exist_ok=True)
    productos = ficticios.escribir_csv(destino / "producto.csv")
    tipos = ficticios.escribir_tipos(destino / "tipo_producto.csv")
    print(f"Producto: {productos} ({ficticios.LEIDOS} filas con datos)")
    print(f"TipoProducto: {tipos}")
    print(
        f"Esperado en la primera sincronizacion: {ficticios.EN_REPARACION} "
        f"en reparacion, por sede {ficticios.EN_REPARACION_POR_SEDE}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
