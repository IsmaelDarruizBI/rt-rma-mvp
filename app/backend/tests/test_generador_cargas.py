"""Generador de las cargas iniciales (QA-E3-5), sin base.

``supabase/scripts/generar_datos_iniciales.cjs`` valida las referencias
antes de generar: una que no se resuelve detiene la generacion con el
detalle, en vez de producir una carga que la descarte en silencio. Corre
con Node; sin ``node`` en el PATH, se saltea.
"""

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]
GENERADOR = RAIZ / "supabase/scripts/generar_datos_iniciales.cjs"
CARGA_DEMO = RAIZ / "supabase/seeds/desarrollo/01_catalogos_demo.sql"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="sin node en el PATH")

# Lee los datos de stdin (o los del repositorio) y escribe la carga.
_GENERAR = """
const g = require(process.argv[1]);
let entrada = "";
process.stdin.on("data", (d) => (entrada += d));
process.stdin.on("end", () => {
  const datos = entrada.trim() ? JSON.parse(entrada) : g.datosDesarrollo();
  process.stdout.write(g.cargaDesarrollo(datos));
});
"""


def _generar(datos=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [NODE, "-e", _GENERAR, str(GENERADOR)],
        input="" if datos is None else json.dumps(datos),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=RAIZ,
        timeout=60,
    )


def _datos():
    salida = subprocess.run(
        [
            NODE,
            "-e",
            "process.stdout.write(JSON.stringify("
            "require(process.argv[1]).datosDesarrollo()))",
            str(GENERADOR),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=RAIZ,
        timeout=60,
        check=True,
    )
    return json.loads(salida.stdout)


def test_la_carga_versionada_es_la_que_genera_el_script():
    salida = _generar()
    assert salida.returncode == 0, salida.stderr
    assert salida.stdout == CARGA_DEMO.read_text(encoding="utf-8")


def _con(cambio):
    datos = copy.deepcopy(_datos())
    cambio(datos)
    return datos


@pytest.mark.parametrize(
    ("cambio", "mensaje"),
    [
        (
            lambda d: d["tipoInsumos"].append(
                {
                    "tipo_reparacion_id": "TR-002",
                    "insumo_id": "INS-404",
                    "cantidad": "1",
                }
            ),
            "insumo previsto 2: no existe el insumo INS-404",
        ),
        (
            lambda d: d["tipoInsumos"].append(
                {
                    "tipo_reparacion_id": "TR-404",
                    "insumo_id": "INS-001",
                    "cantidad": "1",
                }
            ),
            "no existe el tipo de reparación TR-404",
        ),
        (
            lambda d: d["tipoEstaciones"].append(
                {"estacion_id": "EST-404", "tipo_reparacion_id": "TR-001"}
            ),
            "no existe la estación EST-404",
        ),
        (
            lambda d: d["tipoInsumos"].append(dict(d["tipoInsumos"][0])),
            "insumo previsto repetido: TR-001 / INS-001",
        ),
        (
            lambda d: d["insumos"].append(
                {**d["insumos"][0], "codigo": "OTRO-CODIGO"}
            ),
            "insumo repetido: id INS-001",
        ),
        (
            # El id de un insumo es el codigo de otro: chocaria con la clave
            # provisoria de una fila anterior a E3.
            lambda d: d["insumos"].append(
                {**d["insumos"][0], "id": "INS-002", "codigo": "INS-001"}
            ),
            "su id INS-001 es el código de otro insumo",
        ),
        (
            lambda d: d["usuarios"].append(
                {"id": "SIN-ROL", "nombre": "x", "activo": True}
            ),
            "usuario SIN-ROL: falta el rol",
        ),
    ],
    ids=[
        "insumo inexistente",
        "tipo inexistente",
        "estacion inexistente",
        "relacion repetida",
        "id repetido",
        "id igual al codigo de otro",
        "usuario sin rol",
    ],
)
def test_una_referencia_que_no_se_resuelve_detiene_la_generacion(
    cambio, mensaje
):
    salida = _generar(_con(cambio))
    assert salida.returncode != 0
    assert "Datos de desarrollo inconsistentes" in salida.stderr
    assert mensaje in salida.stderr
    assert salida.stdout == ""  # no genera nada


def test_cada_relacion_de_las_fuentes_queda_en_la_carga():
    """Lo que se genera es exactamente lo de las fuentes: cada insumo
    previsto con su clave y su codigo, en el alta y en la verificacion."""
    datos = _datos()
    carga = _generar().stdout
    codigo = {i["id"]: i["codigo"] for i in datos["insumos"]}
    for previsto in datos["tipoInsumos"]:
        tipo, insumo = previsto["tipo_reparacion_id"], previsto["insumo_id"]
        fila = (
            f"('{tipo}', '{insumo}', '{codigo[insumo]}', "
            f"{previsto['cantidad']}::numeric)"
        )
        assert carga.count(fila) == 2  # alta y verificacion
