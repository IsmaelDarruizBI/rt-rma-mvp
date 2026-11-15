# ruff: noqa: E501  (SQL y mensajes largos)
"""Ensayo LOCAL de la limpieza selectiva del E2E y de ``03_verificar.sql``.

Solo contra un PostgreSQL local y descartable (nunca Supabase). Reutiliza la
base y el servidor de ``ensayar_migracion_integral.py``:

1. ``03_verificar.sql`` corre con las 23 migraciones de São Paulo (las tablas
   nuevas salen como «ausente») y con las 35.
2. Una Orden PREVIA con un cliente que no es del E2E y una foto registrada,
   como ``OR-000001`` en el UAT.
3. Los E2E no escriben si las Órdenes existentes no son las declaradas.
4. Para ``probar_macro_v14.py`` y para ``probar_macro_integral.py``, cada uno
   con su línea de base: ``05_linea_base_e2e.sql``, el E2E con
   ``--ordenes-previas``, ``06_limpiar_e2e.sql`` en ensayo (no cambia nada) y
   aplicado. Al final cada tabla de rma es igual a la de antes del E2E (sin
   sellos de tiempo ni versión), las secuencias vuelven a su valor, la Orden
   previa y su foto siguen y la línea de base ya no existe.
5. Guardas de ``06_limpiar_e2e.sql``: una Orden nueva que no es del E2E y una
   fila previa modificada abortan sin borrar nada.

    app/backend/.venv/Scripts/python supabase/scripts/validacion_uat/ensayar_limpieza_e2e.py --informe <archivo.json>

Datos ficticios. No usa credenciales: el servidor local confía en las
conexiones locales.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ensayar_migracion_integral as em  # noqa: E402
from probar_macro_v14 import EQUIPO  # noqa: E402

RAIZ = em.RAIZ
REINICIO = RAIZ / "supabase" / "scripts" / "reinicio_uat"
VALIDACION = RAIZ / "supabase" / "scripts" / "validacion_uat"
PREVIA = "OR-000001"
VOLATILES = ("modificado_en", "actualizado_en", "version")
PROVEEDOR = "Proveedor Ficticio E2E"
anotar = em.anotar


def sql(nombre: str) -> str:
    return (REINICIO / nombre).read_text(encoding="utf-8")


def limpieza(modo: str) -> str:
    texto = sql("06_limpiar_e2e.sql")
    viejo = "v_modo constant text := 'ensayo';"
    assert texto.count(viejo) == 1
    return texto.replace(viejo, f"v_modo constant text := '{modo}';")


def correr_sql(url: str, texto: str) -> tuple[bool, str, object]:
    """Ejecuta un script; devuelve (ok, mensaje de error, resumen si lo hay)."""
    psycopg = em._psycopg()
    with psycopg.connect(url, autocommit=True) as conexion:
        try:
            conexion.execute(texto)
        except psycopg.Error as error:
            return False, str(error).splitlines()[0], None
        resumen = None
        if conexion.execute(
            "select to_regclass('pg_temp.resumen_limpieza_e2e') is not null"
        ).fetchone()[0]:
            resumen = conexion.execute(
                "select resumen from resumen_limpieza_e2e"
            ).fetchone()[0]
        return True, "", resumen


def huella(url: str) -> dict:
    """Contenido de cada tabla de rma sin columnas volátiles, y secuencias."""
    tablas = [
        t
        for (t,) in em.filas(
            url,
            "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'rma' and c.relkind = 'r' order by 1",
        )
    ]
    volatiles = "array[" + ", ".join(f"'{v}'" for v in VOLATILES) + "]"
    resultado = {}
    for t in tablas:
        filtro = f"where x.nombre <> '{PROVEEDOR}'" if t == "proveedor" else ""
        (resultado[t],) = em.filas(
            url,
            f"select count(*) || ':' || coalesce(md5(string_agg((to_jsonb(x) - {volatiles}::text[])::text, E'\\n' order by (to_jsonb(x) - {volatiles}::text[])::text)), '-') from rma.{t} x {filtro}",
        )[0]
    for (s,) in em.filas(
        url, "select sequencename from pg_sequences where schemaname = 'rma'"
    ):
        resultado[f"secuencia {s}"] = em.filas(
            url, f"select last_value, is_called from rma.{s}"
        )[0]
    return resultado


def diferencias(a: dict, b: dict) -> list[str]:
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def verificar(url: str) -> dict:
    """03_verificar.sql, como lo correría la sesión de solo lectura."""
    filas = em.filas(url, sql("03_verificar.sql"))
    return {
        "migraciones": next(f for g, t, f in filas if t == "migraciones"),
        "ausentes": sorted(t for g, t, f in filas if g == "ausente"),
        "ordenes": next(
            (f for g, t, f in filas if g == "operativa" and t == "orden"), None
        ),
        "stock": [t for g, t, f in filas if g == "stock"],
    }


def e2e(paso: str, script: str, api: str, registro: Path, *extra: str) -> bool:
    return em.correr(
        paso,
        f"{script} {' '.join(extra)}",
        [
            sys.executable,
            str(VALIDACION / script),
            "--api",
            api,
            "--sin-autenticacion",
            *extra,
        ],
        registro=registro,
    )


def e2e_rechazado(paso: str, script: str, api: str, registro: Path) -> bool:
    """Sin declarar las Órdenes previas, el E2E tiene que terminar con error."""
    import subprocess

    r = subprocess.run(
        [
            sys.executable,
            str(VALIDACION / script),
            "--api",
            api,
            "--sin-autenticacion",
            "--escribir",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    with registro.open("a", encoding="utf-8") as archivo:
        archivo.write(
            f"\n===== {script} sin --ordenes-previas\n{r.stdout}{r.stderr}"
        )
    return anotar(
        paso,
        f"{script} sin --ordenes-previas termina con error",
        r.returncode == 1 and "no se escribe nada" in r.stdout,
        (r.stdout + r.stderr)[-300:],
    )


def ciclo(
    paso: str, script: str, url: str, api: str, antes: dict, registro: Path
) -> None:
    """Línea de base, E2E, limpieza en ensayo y aplicada, y comparación."""
    ok, error, _ = correr_sql(url, sql("05_linea_base_e2e.sql"))
    anotar(paso, "05_linea_base_e2e.sql crea la línea de base", ok, error)
    (acceso,) = em.filas(
        url,
        "select bool_or(has_schema_privilege(r, 'rma_linea_base_e2e', 'usage')) from unnest(array['anon', 'authenticated', 'service_role', 'rma_backend']) r",
    )[0]
    anotar(paso, "la línea de base no es accesible por la API", not acceso)
    ok, error, _ = correr_sql(url, sql("05_linea_base_e2e.sql"))
    anotar(
        paso,
        "05 no pisa una línea de base existente",
        not ok and "ya existe" in error,
        error,
    )
    e2e(
        paso,
        script,
        api,
        registro,
        "--escribir",
        "--ordenes-previas",
        PREVIA,
    )
    despues_e2e = huella(url)
    anotar(
        paso,
        "el E2E creó datos",
        diferencias(antes, despues_e2e) != [],
        "sin cambios",
    )
    ok, error, _ = correr_sql(url, limpieza("ensayo"))
    anotar(
        paso,
        "06 en ensayo: ENSAYO OK",
        not ok and "ENSAYO OK" in error,
        error,
    )
    anotar(
        paso,
        "06 en ensayo no cambia nada",
        huella(url) == despues_e2e,
        str(diferencias(despues_e2e, huella(url))),
    )
    ok, error, resumen = correr_sql(url, limpieza("aplicar"))
    anotar(paso, "06 aplicado", ok and resumen is not None, error)
    (resumen or {}).pop("filas_borradas", None)
    with registro.open("a", encoding="utf-8") as archivo:
        archivo.write(
            f"\n===== resumen {script}\n{json.dumps(resumen, ensure_ascii=False)}\n"
        )
    despues = huella(url)
    anotar(
        paso,
        "cada tabla y secuencia quedó como antes del E2E",
        despues == antes,
        str(diferencias(antes, despues)),
    )
    anotar(
        paso,
        f"{PREVIA} conservada y la única Orden",
        (resumen or {}).get("ordenes_conservadas") == [PREVIA],
        str(resumen),
    )
    (base,) = em.filas(
        url, "select to_regclass('rma_linea_base_e2e._metadatos') is not null"
    )[0]
    anotar(paso, "la línea de base se eliminó al aplicar", not base)
    anotar(
        paso,
        "verificar_integridad() vacío",
        em.filas(url, "select * from rma.verificar_integridad()") == [],
    )


def guardas(paso: str, url: str, api: str) -> None:
    import httpx

    ok, error, _ = correr_sql(url, sql("05_linea_base_e2e.sql"))
    anotar(paso, "línea de base para las guardas", ok, error)
    r = httpx.post(
        f"{api}/api/orders",
        json={
            "usuario_id": "RECEP-001",
            "cliente": {
                "nombre_apellido": "Otra Persona",
                "telefono": "341-555",
            },
            "equipo": EQUIPO,
        },
        timeout=30,
    )
    anotar(
        paso, "una Orden nueva que no es del E2E", r.status_code < 300, r.text
    )
    ok, error, _ = correr_sql(url, limpieza("ensayo"))
    anotar(
        paso,
        "06 aborta: la Orden nueva no es del E2E",
        not ok and "no son del E2E" in error,
        error,
    )
    em.ejecutar(url, "drop schema rma_linea_base_e2e cascade")

    ok, error, _ = correr_sql(url, sql("05_linea_base_e2e.sql"))
    em.ejecutar(
        url,
        f"update rma.cliente set telefono = telefono || '9' where id = (select cliente_id from rma.orden where codigo = '{PREVIA}')",
    )
    ok, error, _ = correr_sql(url, limpieza("ensayo"))
    anotar(
        paso,
        "06 aborta: cambió una fila previa",
        not ok and "cambiaron o faltan" in error,
        error,
    )
    em.ejecutar(url, "drop schema rma_linea_base_e2e cascade")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--admin-url", default="postgresql://postgres@127.0.0.1:54329/postgres"
    )
    p.add_argument("--puerto", type=int, default=8791)
    p.add_argument("--informe")
    a = p.parse_args()
    carpeta = Path(tempfile.mkdtemp(prefix="rma-limpieza-e2e-"))
    registro = carpeta / "registro.txt"
    try:
        url = em.preparar_base(a.admin_url)
        v = verificar(url)
        anotar(
            "1",
            "03_verificar.sql con 23 migraciones",
            v["migraciones"] == 23 and "lote_insumo" in v["ausentes"],
            str(v),
        )
        for archivo in em.archivos_nuevos():
            em.ejecutar(url, archivo.read_text(encoding="utf-8"))
        versiones = ", ".join(
            f"('{x.name.split('_')[0]}')" for x in em.archivos_nuevos()
        )
        em.ejecutar(
            url,
            f"insert into supabase_migrations.schema_migrations values {versiones}",
        )
        v = verificar(url)
        anotar(
            "1",
            "03_verificar.sql con 35 migraciones",
            v["migraciones"] == 35
            and v["ausentes"] == []
            and v["ordenes"] == 0,
            str(v),
        )
        url_api = em.url_base(a.admin_url, em.BASE, usuario=em.ROL_API)
        with em.servidor(em.BACKEND, url_api, a.puerto, registro) as api:
            import httpx

            r = httpx.post(
                f"{api}/api/orders",
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
            anotar("2", f"Orden previa {PREVIA}", r.status_code < 300, r.text)
            anotar(
                "2",
                "el listado usa el código como id",
                r.json().get("id") == PREVIA,
                r.text,
            )
            em.ejecutar(
                url,
                f"""insert into rma.foto (codigo, orden_id, objeto_clave, tipo_contenido, tamano_bytes, nombre_original, usuario_id, posicion)
                    select 'FOT-PREVIA', o.id, 'ordenes/{PREVIA}/previa.jpg', 'image/jpeg', 1, 'previa.jpg', u.id, 1
                      from rma.orden o, rma.usuario u where o.codigo = '{PREVIA}' and u.codigo = 'RECEP-001'""",
            )
            antes = huella(url)

            e2e_rechazado("3", "probar_macro_v14.py", api, registro)
            anotar(
                "3",
                "sin declarar la Orden previa, el E2E no escribe",
                huella(url) == antes,
                str(diferencias(antes, huella(url))),
            )
            e2e_rechazado("3", "probar_macro_integral.py", api, registro)
            anotar(
                "3",
                "ni el E2E integral",
                huella(url) == antes,
                str(diferencias(antes, huella(url))),
            )

            ciclo("4a", "probar_macro_v14.py", url, api, antes, registro)
            ciclo("4b", "probar_macro_integral.py", url, api, antes, registro)
            v = verificar(url)
            anotar(
                "4",
                "03_verificar.sql después de limpiar: la Orden previa",
                v["ordenes"] == 1 and all("concilia" in s for s in v["stock"]),
                str(v),
            )
            (fotos,) = em.filas(
                url,
                f"select count(*) from rma.foto where objeto_clave = 'ordenes/{PREVIA}/previa.jpg'",
            )[0]
            anotar("4", "la foto previa sigue registrada", fotos == 1)
            guardas("5", url, api)
    except Exception:
        anotar("x", "excepción", False, traceback.format_exc())
    fallas = [x for x in em.resultados if not x["ok"]]
    for x in em.resultados:
        print(
            f"  {'OK   ' if x['ok'] else 'FALLA'} [{x['paso']}] {x['comprobacion']}"
            + (f" — {x['detalle'][:300]}" if not x["ok"] else "")
        )
    print(
        f"\nRESULTADO: {'OK' if not fallas else f'{len(fallas)} FALLAS'} ({len(em.resultados)} comprobaciones). Registro: {registro}"
    )
    if a.informe:
        Path(a.informe).write_text(
            json.dumps(em.resultados, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0 if not fallas else 1


if __name__ == "__main__":
    sys.exit(main())
