# ruff: noqa: E501  (SQL y mensajes largos)
"""Ensayo LOCAL del bloque C: la copia del catalogo de Ventas en PostgreSQL.

Solo contra un PostgreSQL local y descartable (nunca Supabase), con datos
ficticios (el CSV de las pruebas). Procesos reales de uvicorn, que se matan:

1. Una instancia sincroniza; se la mata y se borra su carpeta de datos; otra
   instancia, con una carpeta vacia, ve la misma copia (reinicio y escalado
   a cero: nada depende del disco ni de la memoria).
2. Datos no confiables (CSV sin columnas): RECHAZADA, la copia intacta.
3. Origen inaccesible (el CSV no existe): FALLIDA, la copia intacta.
4. Un proceso muere A MITAD de una sincronizacion (origen lento, ``kill``):
   la copia intacta, la reserva bloquea hasta vencer y la siguiente la marca
   INTERRUMPIDA y sincroniza.
5. Vuelta atras: el backend publicado (``--anterior``, exportado con
   ``git archive``) arranca sobre la base con las migraciones nuevas, lista
   y crea Ordenes; la version nueva lee lo que creo.

    app/backend/.venv/Scripts/python supabase/scripts/validacion_uat/ensayar_persistencia_catalogo.py --admin-url postgresql://postgres@127.0.0.1:55432/postgres --anterior 677dbb1

Sin credenciales: el servidor local confia en las conexiones locales.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

RAIZ = Path(__file__).resolve().parents[3]
BACKEND = RAIZ / "app" / "backend"
SUPABASE = RAIZ / "supabase"
CARPETAS_SQL = ("migrations", "seeds/referencia_operativa", "seeds/desarrollo")
BASE = "rma_ensayo_persistencia"
ROL_API = "rma_api_ensayo"
ADMIN = "ADMIN-001"
RECEPCION = "RECEP-001"
RESERVA_S = 10

sys.path.insert(0, str(BACKEND))

resultados: list[dict] = []


def anotar(paso: str, nombre: str, ok: bool, detalle: str = "") -> bool:
    resultados.append(
        {
            "paso": paso,
            "comprobacion": nombre,
            "ok": bool(ok),
            "detalle": detalle,
        }
    )
    print(
        f"  {'OK   ' if ok else 'FALLA'} [{paso}] {nombre}"
        + ("" if ok else f" — {detalle[:300]}"),
        flush=True,
    )
    return bool(ok)


def _psycopg():
    import psycopg

    return psycopg


def url_base(url_admin: str, nombre: str, usuario: str | None = None) -> str:
    partes = urlsplit(url_admin)
    netloc = (
        partes.netloc
        if usuario is None
        else f"{usuario}@{partes.hostname}:{partes.port}"
    )
    return urlunsplit(partes._replace(path=f"/{nombre}", netloc=netloc))


def filas(url: str, texto: str, parametros=()) -> list[tuple]:
    with _psycopg().connect(url) as conexion:
        return conexion.execute(texto, parametros).fetchall()


def preparar_base(url_admin: str) -> str:
    """Base nueva con todas las migraciones y las cargas de desarrollo."""
    psycopg = _psycopg()
    host = urlsplit(url_admin).hostname
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("Solo un PostgreSQL local.")
    with psycopg.connect(url_admin, autocommit=True) as admin:
        admin.execute(f"drop database if exists {BASE} with (force)")
        for rol in ("anon", "authenticated", "service_role"):
            if not admin.execute(
                "select 1 from pg_roles where rolname = %s", (rol,)
            ).fetchone():
                admin.execute(f"create role {rol} nologin")
        admin.execute(f"create database {BASE}")
    url = url_base(url_admin, BASE)
    with psycopg.connect(url, autocommit=True) as conexion:
        for carpeta in CARPETAS_SQL:
            for archivo in sorted((SUPABASE / carpeta).glob("*.sql")):
                conexion.execute(archivo.read_text(encoding="utf-8"))
        if not conexion.execute(
            "select 1 from pg_roles where rolname = %s", (ROL_API,)
        ).fetchone():
            conexion.execute(
                f"create role {ROL_API} login inherit in role rma_backend"
            )
    return url


def exportar(commit: str, destino: Path) -> Path:
    datos = subprocess.run(
        ["git", "archive", commit, "app/backend"],
        cwd=RAIZ,
        capture_output=True,
        check=True,
    ).stdout
    with tarfile.open(fileobj=BytesIO(datos)) as tar:
        tar.extractall(destino, filter="data")
    return destino / "app" / "backend"


def entorno(url_api: str, datos: Path, csv: Path) -> dict:
    valores = {k: v for k, v in os.environ.items() if not k.startswith("RMA_")}
    return valores | {
        "RMA_PERSISTENCIA": "postgres",
        "RMA_DATABASE_URL": url_api,
        "RMA_DATA_DIR": str(datos),
        "RMA_CATALOGO_ORIGEN": "archivo",
        "RMA_CATALOGO_ARCHIVO": str(csv),
        "RMA_SINCRONIZACION_RESERVA_S": str(RESERVA_S),
    }


@contextmanager
def servidor(
    raiz_backend: Path, variables: dict, puerto: int, registro: Path, cwd: Path
):
    import httpx

    with registro.open("ab") as salida:
        proceso = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--port",
                str(puerto),
                "--host",
                "127.0.0.1",
            ],
            cwd=cwd,
            env=variables | {"PYTHONPATH": str(raiz_backend)},
            stdout=salida,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(120):
                try:
                    if (
                        httpx.get(
                            f"http://127.0.0.1:{puerto}/health", timeout=2
                        ).status_code
                        == 200
                    ):
                        break
                except httpx.HTTPError:
                    pass
                if proceso.poll() is not None:
                    raise RuntimeError(
                        f"El servidor terminó al arrancar (ver {registro})."
                    )
                time.sleep(0.5)
            else:
                raise RuntimeError(
                    f"El servidor no respondió (ver {registro})."
                )
            yield f"http://127.0.0.1:{puerto}", proceso
        finally:
            if proceso.poll() is None:
                proceso.kill()  # sin apagado ordenado: como una instancia que se corta
                proceso.wait(15)


def huella(url: str) -> tuple:
    return filas(
        url,
        "select count(*), md5(coalesce(string_agg(t::text, '|' order by t.tipo_producto_id), ''))"
        " from rma.catalogo_producto t",
    )[0]


def intentos(url: str) -> list[tuple]:
    return filas(
        url,
        "select id, resultado from rma.sincronizacion_origen order by iniciada_en, id",
    )


SINCRONIZAR_LENTO = """
import sys, time
from app.core.config import get_settings
from app.application.contexto import construir_contexto
from app.application import sincronizar_catalogo_equipos
from dataclasses import replace
contexto = construir_contexto(get_settings())
real = contexto.proveedor_catalogo
class Lento:
    descripcion = real.descripcion
    def leer(self, filtro):
        print("LEYENDO", flush=True)
        time.sleep(120)
        return real.leer(filtro)
contexto = replace(contexto, proveedor_catalogo=Lento())
sincronizar_catalogo_equipos(contexto, usuario_id="ADMIN-001")
"""


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--admin-url", default="postgresql://postgres@127.0.0.1:55432/postgres"
    )
    p.add_argument(
        "--anterior", required=True, help="commit del backend publicado"
    )
    p.add_argument("--puerto", type=int, default=8891)
    p.add_argument("--informe")
    a = p.parse_args()

    import httpx

    from tests.fixtures.catalogo_ventas import (
        ID_12_NEGRO,
        escribir_csv,
        filas_base,
    )

    carpeta = Path(tempfile.mkdtemp(prefix="rma-ensayo-persistencia-"))
    registro = carpeta / "registro.txt"
    csv = carpeta / "tipo_producto.csv"
    escribir_csv(csv)
    sin_env = carpeta / "cwd"  # cwd sin .env
    sin_env.mkdir()

    def sincronizar(api: str):
        return httpx.post(
            f"{api}/api/catalogs/equipment/sync",
            params={"usuario_id": ADMIN},
            timeout=60,
        )

    def estado(api: str) -> dict:
        r = httpx.get(f"{api}/api/catalogs/equipment", timeout=60)
        r.raise_for_status()
        return r.json()["estado"]

    try:
        url = preparar_base(a.admin_url)
        url_api = url_base(a.admin_url, BASE, usuario=ROL_API)
        tablas = filas(
            url,
            "select count(*) from information_schema.tables where table_schema = 'rma' and table_type = 'BASE TABLE'",
        )[0][0]
        anotar(
            "0",
            "base con todas las migraciones (71 tablas) y la copia vacía",
            tablas == 71 and huella(url)[0] == 0,
            f"{tablas} tablas",
        )

        # 1. Reinicio y escalado a cero.
        datos_a = carpeta / "datos-a"
        with servidor(
            BACKEND,
            entorno(url_api, datos_a, csv),
            a.puerto,
            registro,
            sin_env,
        ) as (api, _):
            r = sincronizar(api)
            exitosa = r.json() if r.status_code == 200 else {}
            anotar(
                "1",
                "la instancia A sincroniza: EXITOSA, 12 vigentes",
                r.status_code == 200 and exitosa.get("vigentes") == 12,
                r.text[:300],
            )
        shutil.rmtree(datos_a, ignore_errors=True)
        anotar(
            "1", "A muerta (kill) y su carpeta borrada", not datos_a.exists()
        )
        copia = huella(url)
        datos_b = carpeta / "datos-b"
        with servidor(
            BACKEND,
            entorno(url_api, datos_b, csv),
            a.puerto + 1,
            registro,
            sin_env,
        ) as (api, _):
            e = estado(api)
            anotar(
                "1",
                "la instancia B (carpeta vacía) ve la misma copia y la misma última exitosa",
                e["ultima_exitosa"]
                and e["ultima_exitosa"]["id"] == exitosa.get("id")
                and e["vigentes"] == 12,
                str(e)[:300],
            )
            anotar(
                "1",
                "B no escribe la copia en disco",
                not (
                    datos_b / "catalogo_equipos" / "catalogo_equipos.json"
                ).exists(),
            )

            # 2. Datos no confiables.
            csv.write_text("tp_id,tp_modelo\nx,y\n", encoding="utf-8")
            r = sincronizar(api)
            anotar(
                "2",
                "CSV sin columnas: 409 CATALOGO_ORIGEN_INVALIDO",
                r.status_code == 409
                and r.json()["error"]["codigo"] == "CATALOGO_ORIGEN_INVALIDO",
                r.text[:300],
            )
            anotar("2", "la copia no cambió", huella(url) == copia)
            anotar(
                "2", "intento RECHAZADA", intentos(url)[-1][1] == "RECHAZADA"
            )

            # 3. Origen inaccesible.
            csv.unlink()
            r = sincronizar(api)
            anotar(
                "3",
                "CSV inexistente: 503 y se conserva el catálogo anterior",
                r.status_code == 503
                and "Se conserva el catálogo anterior"
                in r.json()["error"]["mensaje"],
                r.text[:300],
            )
            anotar("3", "la copia no cambió", huella(url) == copia)
            anotar("3", "intento FALLIDA", intentos(url)[-1][1] == "FALLIDA")
            e = estado(api)
            anotar(
                "3",
                "el estado muestra la última exitosa de antes",
                e["ultima_exitosa"]["id"] == exitosa.get("id")
                and e["ultima"]["resultado"] == "FALLIDA",
            )

            # 4. Un proceso muere a mitad de una sincronizacion.
            escribir_csv(
                csv, [f for f in filas_base() if ID_12_NEGRO not in f]
            )
            variables = entorno(url_api, carpeta / "datos-lento", csv) | {
                "PYTHONPATH": str(BACKEND)
            }
            with (carpeta / "lento.txt").open("wb") as salida:
                lento = subprocess.Popen(
                    [sys.executable, "-c", SINCRONIZAR_LENTO],
                    cwd=sin_env,
                    env=variables,
                    stdout=salida,
                    stderr=subprocess.STDOUT,
                )
            en_curso = []
            for _ in range(120):
                en_curso = filas(
                    url,
                    "select id from rma.sincronizacion_origen where resultado = 'EN_CURSO'",
                )
                if en_curso:
                    break
                time.sleep(0.25)
            anotar(
                "4",
                "el proceso lento reservó (EN_CURSO)",
                len(en_curso) == 1,
                (carpeta / "lento.txt").read_text(errors="replace")[-500:],
            )
            lento.kill()
            lento.wait(15)
            anotar(
                "4",
                "proceso muerto a mitad (kill)",
                lento.returncode is not None,
            )
            anotar("4", "la copia no cambió", huella(url) == copia)
            r = sincronizar(api)
            anotar(
                "4",
                "mientras la reserva vale: 409 SINCRONIZACION_EN_CURSO",
                r.status_code == 409
                and r.json()["error"]["codigo"] == "SINCRONIZACION_EN_CURSO",
                r.text[:300],
            )
            time.sleep(RESERVA_S + 1)
            r = sincronizar(api)
            anotar(
                "4",
                "vencida la reserva, la siguiente sincroniza (1 baja)",
                r.status_code == 200 and r.json().get("dados_de_baja") == 1,
                r.text[:300],
            )
            resultado_caido = (
                dict(intentos(url)).get(en_curso[0][0]) if en_curso else None
            )
            anotar(
                "4",
                "el intento del proceso muerto quedó INTERRUMPIDA",
                resultado_caido == "INTERRUMPIDA",
                str(resultado_caido),
            )
            anotar(
                "4",
                "ningún secreto guardado",
                filas(
                    url,
                    "select count(*) from rma.sincronizacion_origen where propietario is not null",
                )[0][0]
                == 0
                and filas(
                    url,
                    "select count(*) from rma.catalogo_producto where propietario is not null",
                )[0][0]
                == 0,
            )

        # 5. Vuelta atras al backend publicado sobre la base nueva.
        anterior = exportar(a.anterior, carpeta / "anterior")
        with servidor(
            anterior,
            entorno(url_api, carpeta / "datos-anterior", csv),
            a.puerto + 2,
            registro,
            sin_env,
        ) as (api, _):
            r = httpx.get(f"{api}/api/orders", timeout=60)
            anotar(
                "5",
                f"el backend anterior ({a.anterior}) lista Órdenes sobre la base nueva",
                r.status_code == 200,
                r.text[:300],
            )
            r = httpx.post(
                f"{api}/api/orders",
                json={
                    "usuario_id": RECEPCION,
                    "cliente": {
                        "nombre_apellido": "Persona Ficticia",
                        "telefono": "341-0000000",
                    },
                    "equipo": {
                        "marca": "Apple",
                        "modelo": "iPhone 12",
                        "falla_reportada": "No enciende.",
                    },
                },
                timeout=60,
            )
            orden = r.json().get("id") if r.status_code < 300 else None
            anotar(
                "5",
                "el backend anterior crea una Orden",
                orden is not None,
                r.text[:300],
            )
            r = httpx.get(f"{api}/api/catalogs/equipment", timeout=60)
            anotar(
                "5",
                "el backend anterior responde su catálogo (su copia JSON, vacía)",
                r.status_code == 200,
                r.text[:200],
            )
        anotar(
            "5",
            "la copia de la base no cambió con el backend anterior",
            huella(url)[0] == 12,
        )
        with servidor(
            BACKEND,
            entorno(url_api, carpeta / "datos-c", csv),
            a.puerto + 3,
            registro,
            sin_env,
        ) as (api, _):
            r = (
                httpx.get(f"{api}/api/orders/{orden}", timeout=60)
                if orden
                else None
            )
            anotar(
                "5",
                "la versión nueva lee la Orden creada por la anterior",
                r is not None and r.status_code == 200,
                r.text[:200] if r is not None else "sin orden",
            )
            anotar(
                "5",
                "y conserva la copia (12 productos, 11 vigentes tras la baja)",
                huella(url)[0] == 12 and estado(api)["vigentes"] == 11,
            )
        anotar(
            "6",
            "verificar_integridad() vacío",
            filas(url, "select count(*) from rma.verificar_integridad()")[0][0]
            == 0,
        )
    except Exception:
        anotar("x", "excepción", False, traceback.format_exc())

    fallas = [x for x in resultados if not x["ok"]]
    print(
        f"\nRESULTADO: {'OK' if not fallas else f'{len(fallas)} FALLAS'} ({len(resultados)} comprobaciones). Registros: {carpeta}"
    )
    if a.informe:
        Path(a.informe).write_text(
            json.dumps(resultados, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0 if not fallas else 1


if __name__ == "__main__":
    sys.exit(main())
