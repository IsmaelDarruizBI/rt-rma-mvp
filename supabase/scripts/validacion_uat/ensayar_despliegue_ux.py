# ruff: noqa: E501  (SQL y mensajes largos)
"""Ensayo LOCAL del despliegue de la iteración de UX de Recepción.

Solo contra un PostgreSQL local y descartable (nunca Supabase):

1. Base «anterior»: las 35 migraciones de São Paulo, las cargas y una Orden
   PREVIA con su foto, como ``OR-000001``.
2. Backend anterior (el código de ``00031-ror``, exportado del commit
   indicado) sobre esa base; se aplican las DOS migraciones nuevas y sigue
   funcionando: ``probar_macro_v14.py`` con su limpieza selectiva.
3. Backend nuevo (el árbol actual): ``probar_ux_recepcion.py``,
   ``probar_macro_v14.py`` y ``probar_macro_integral.py``, cada uno con su
   línea de base, limpieza en ensayo y aplicada, y comparación.
4. Vuelta atrás: con los datos que crea la versión nueva (recargos,
   devoluciones con recargo, texto único), el backend anterior lista y lee
   esas Órdenes.

    app/backend/.venv/Scripts/python supabase/scripts/validacion_uat/ensayar_despliegue_ux.py --admin-url postgresql://postgres@127.0.0.1:55432/postgres --anterior 9176921

Datos ficticios. Sin credenciales: el servidor local confía en las
conexiones locales.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tarfile
import tempfile
import traceback
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ensayar_limpieza_e2e as el  # noqa: E402
import ensayar_migracion_integral as em  # noqa: E402
from probar_macro_v14 import EQUIPO  # noqa: E402

em.PRIMERA_NUEVA = "20261116000100"
anotar = em.anotar
PREVIA = el.PREVIA


def exportar(commit: str, destino: Path) -> Path:
    """``git archive`` de app/backend del commit, sin tocar el árbol."""
    datos = subprocess.run(
        ["git", "archive", commit, "app/backend"],
        cwd=em.RAIZ,
        capture_output=True,
        check=True,
    ).stdout
    with tarfile.open(fileobj=BytesIO(datos)) as tar:
        tar.extractall(destino, filter="data")
    return destino / "app" / "backend"


def ciclo(paso, script, url, api, antes, registro, durante=None) -> None:
    """Línea de base, E2E, (verificación intermedia), limpieza en ensayo y
    aplicada, y comparación con la línea de base."""
    ok, error, _ = el.correr_sql(url, el.sql("05_linea_base_e2e.sql"))
    anotar(paso, "05_linea_base_e2e.sql crea la línea de base", ok, error)
    # Cada E2E con su propio archivo: el registro lo comparten los servidores.
    salida = registro.with_name(f"{paso}-{script}.txt")
    el.e2e(
        paso, script, api, salida, "--escribir", "--ordenes-previas", PREVIA
    )
    despues_e2e = el.huella(url)
    anotar(
        paso,
        "el E2E creó datos",
        el.diferencias(antes, despues_e2e) != [],
        "sin cambios",
    )
    if durante:
        durante()
    ok, error, _ = el.correr_sql(url, el.limpieza("ensayo"))
    anotar(
        paso, "06 en ensayo: ENSAYO OK", not ok and "ENSAYO OK" in error, error
    )
    anotar(paso, "06 en ensayo no cambia nada", el.huella(url) == despues_e2e)
    ok, error, resumen = el.correr_sql(url, el.limpieza("aplicar"))
    anotar(paso, "06 aplicado", ok and resumen is not None, error)
    despues = el.huella(url)
    anotar(
        paso,
        "cada tabla y secuencia quedó como antes del E2E",
        despues == antes,
        str(el.diferencias(antes, despues))[:600],
    )
    anotar(
        paso,
        f"{PREVIA} conservada y la única Orden",
        (resumen or {}).get("ordenes_conservadas") == [PREVIA],
        str(resumen)[:300],
    )
    anotar(
        paso,
        "verificar_integridad() vacío",
        em.filas(url, "select * from rma.verificar_integridad()") == [],
    )


def main() -> int:
    # La consola de Windows (cp1252) no imprime todo: no cortar por eso.
    sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--admin-url", default="postgresql://postgres@127.0.0.1:55432/postgres"
    )
    p.add_argument(
        "--anterior",
        required=True,
        help="commit del backend publicado (00031-ror)",
    )
    p.add_argument("--puerto", type=int, default=8791)
    p.add_argument("--informe")
    a = p.parse_args()
    carpeta = Path(tempfile.mkdtemp(prefix="rma-ensayo-ux-"))
    registro = carpeta / "registro.txt"
    try:
        anterior = exportar(a.anterior, carpeta / "anterior")
        url = em.preparar_base(a.admin_url)
        v = el.verificar(url)
        anotar(
            "1",
            "base anterior con 35 migraciones",
            v["migraciones"] == 35 and v["ordenes"] == 0,
            str(v),
        )
        anotar(
            "1",
            "las dos migraciones nuevas son las únicas pendientes",
            [x.name for x in em.archivos_nuevos()]
            == [
                "20261116000100_recargos_medio_pago.sql",
                "20261116000200_recargo_detalles_devoluciones.sql",
            ],
            str([x.name for x in em.archivos_nuevos()]),
        )
        url_api = em.url_base(a.admin_url, em.BASE, usuario=em.ROL_API)

        import httpx

        with em.servidor(
            anterior, url_api, a.puerto + 1, registro
        ) as api_anterior:
            r = httpx.post(
                f"{api_anterior}/api/orders",
                json={
                    "usuario_id": "RECEP-001",
                    "cliente": {
                        "nombre_apellido": "Persona Previa",
                        "telefono": "341-0000000",
                    },
                    "equipo": EQUIPO,
                },
                timeout=30,
            )
            anotar(
                "1",
                f"Orden previa {PREVIA} con el backend anterior",
                r.status_code < 300 and r.json().get("id") == PREVIA,
                r.text[:200],
            )
            em.ejecutar(
                url,
                f"""insert into rma.foto (codigo, orden_id, objeto_clave, tipo_contenido, tamano_bytes, nombre_original, usuario_id, posicion)
                    select 'FOT-PREVIA', o.id, 'ordenes/{PREVIA}/previa.jpg', 'image/jpeg', 1, 'previa.jpg', u.id, 1
                      from rma.orden o, rma.usuario u where o.codigo = '{PREVIA}' and u.codigo = 'RECEP-001'""",
            )
            huella_previa = em.filas(
                url,
                f"select to_jsonb(o) - 'modificado_en' - 'version' from rma.orden o where codigo = '{PREVIA}'",
            )

            # 2. Las migraciones nuevas, con el backend anterior en marcha.
            for archivo in em.archivos_nuevos():
                em.ejecutar(url, archivo.read_text(encoding="utf-8"))
            versiones = ", ".join(
                f"('{x.name.split('_')[0]}')" for x in em.archivos_nuevos()
            )
            em.ejecutar(
                url,
                f"insert into supabase_migrations.schema_migrations values {versiones}",
            )
            v = el.verificar(url)
            anotar(
                "2",
                "37 migraciones, la Orden previa intacta",
                v["migraciones"] == 37 and v["ordenes"] == 1,
                str(v),
            )
            anotar(
                "2",
                "Transferencia con 2 %",
                em.filas(
                    url,
                    "select recargo_porcentaje::text from rma.medio_pago where codigo = 'TRANSFERENCIA'",
                )
                == [("2.00",)],
            )
            anotar(
                "2",
                "la Orden previa no cambió",
                em.filas(
                    url,
                    f"select to_jsonb(o) - 'modificado_en' - 'version' from rma.orden o where codigo = '{PREVIA}'",
                )
                == huella_previa,
            )
            anotar(
                "2",
                "verificar_integridad() vacío",
                em.filas(url, "select * from rma.verificar_integridad()")
                == [],
            )
            antes = el.huella(url)
            ciclo(
                "2", "probar_macro_v14.py", url, api_anterior, antes, registro
            )

        # 3. Backend nuevo.
        with em.servidor(em.BACKEND, url_api, a.puerto, registro) as api:
            antes = el.huella(url)

            def vuelta_atras() -> None:
                """4. El backend anterior lee lo que creó la versión nueva."""
                with em.servidor(
                    anterior, url_api, a.puerto + 2, registro
                ) as viejo:
                    listado = httpx.get(f"{viejo}/api/orders", timeout=60)
                    anotar(
                        "4",
                        "el backend anterior lista las Órdenes con recargos",
                        listado.status_code == 200,
                        f"HTTP {listado.status_code}",
                    )
                    codigos = (
                        [o["id"] for o in listado.json()]
                        if listado.status_code == 200
                        else []
                    )
                    errores = [
                        c
                        for c in codigos
                        if httpx.get(
                            f"{viejo}/api/orders/{c}", timeout=60
                        ).status_code
                        != 200
                    ]
                    anotar(
                        "4",
                        f"y lee cada una ({len(codigos)})",
                        codigos != [] and errores == [],
                        str(errores),
                    )
                    finanzas = [
                        c
                        for c in codigos
                        if httpx.get(
                            f"{viejo}/api/orders/{c}/finances", timeout=60
                        ).status_code
                        != 200
                    ]
                    anotar(
                        "4", "y sus finanzas", finanzas == [], str(finanzas)
                    )

            ciclo(
                "3a",
                "probar_ux_recepcion.py",
                url,
                api,
                antes,
                registro,
                durante=vuelta_atras,
            )
            ciclo("3b", "probar_macro_v14.py", url, api, antes, registro)
            ciclo("3c", "probar_macro_integral.py", url, api, antes, registro)
            v = el.verificar(url)
            anotar(
                "3",
                "al final: la Orden previa y el stock conciliado",
                v["ordenes"] == 1 and all("concilia" in s for s in v["stock"]),
                str(v),
            )
            anotar(
                "3",
                "Transferencia sigue en 2 %",
                em.filas(
                    url,
                    "select recargo_porcentaje::text from rma.medio_pago where codigo = 'TRANSFERENCIA'",
                )
                == [("2.00",)],
            )
    except Exception:
        anotar("x", "excepción", False, traceback.format_exc())
    fallas = [x for x in em.resultados if not x["ok"]]
    for x in em.resultados:
        print(
            f"  {'OK   ' if x['ok'] else 'FALLA'} [{x['paso']}] {x['comprobacion']}"
            + (f" — {x['detalle'][:300]}" if not x["ok"] else "")
        )
    print(
        f"\nRESULTADO: {'OK' if not fallas else f'{len(fallas)} FALLAS'} ({len(em.resultados)} comprobaciones). Registros: {carpeta}"
    )
    if a.informe:
        Path(a.informe).write_text(
            json.dumps(em.resultados, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0 if not fallas else 1


if __name__ == "__main__":
    sys.exit(main())
