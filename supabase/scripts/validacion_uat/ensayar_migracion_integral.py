# ruff: noqa: E501  (SQL y mensajes largos)
"""Ensayo LOCAL del despliegue de la macroiteración integral.

Solo contra un PostgreSQL local y descartable (nunca Supabase): reproduce lo
que pasará en São Paulo y lo que pasaría al volver atrás.

1. Base «anterior»: las 23 migraciones que tiene São Paulo, las cargas de
   referencia y de desarrollo, ``supabase_migrations.schema_migrations`` y un
   esquema ``auth`` mínimo con las cuatro cuentas (como el UAT). La API
   conecta con un rol de login miembro de ``rma_backend`` (como ``rma_api``).
2. Datos con el código PUBLICADO (``--codigo-anterior``: una exportación de
   ``ce37c78``, cuya app es idéntica a ``5c6137e``, la revisión del UAT, y
   que trae el E2E V1.4 con el que se validó): el E2E de la macroiteración V1.4 y además una reserva
   abierta, un consumo, una cancelación y una Orden entregada.
3. Las 12 migraciones nuevas, en orden. Conciliación: stock físico y
   reservado, cada movimiento del libro y los conteos idénticos; todo
   SIN_LOTE, ningún lote, integridad vacía.
4. Código NUEVO (este repositorio, DC12 sin configurar): las Órdenes
   anteriores se leen igual; E2E de la macroiteración integral; la reserva
   abierta antes de migrar se consume; lotes, series, compra con series,
   recepciones concurrentes e idempotencia.
5. Vuelta atrás: el código publicado sobre la base migrada y con los datos
   del código nuevo (lectura de todo y un recorrido que escribe).
6. Regreso al código nuevo.
7. Respaldo y restauración con ``ensayar_restauracion.sh`` (el mismo script
   del Job) en ``postgres:17-alpine``, leyendo con un rol como
   ``rma_respaldo``.
8. Reinicio del UAT (``reinicio_uat/01_reiniciar.sql``) en modo ensayo sobre
   la base resultante.

    app/backend/.venv/Scripts/python supabase/scripts/validacion_uat/ensayar_migracion_integral.py \\
      --codigo-anterior <exportación de 5c6137e> --informe <archivo.json>

Datos ficticios. No usa credenciales: el servidor local confía en las
conexiones locales.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

RAIZ = Path(__file__).resolve().parents[3]
BACKEND = RAIZ / "app" / "backend"
MIGRACIONES = RAIZ / "supabase" / "migrations"
PRIMERA_NUEVA = "20261113000100"
BASE = "rma_ensayo_integral"
ROL_API = "rma_api_ensayo"
ROL_RESPALDO = "rma_respaldo_ensayo"
CUENTAS = {
    "RECEP-001": "00000000-0000-4000-8000-000000000001",
    "TECH-001": "00000000-0000-4000-8000-000000000002",
    "COORD-001": "00000000-0000-4000-8000-000000000003",
    "ADMIN-001": "00000000-0000-4000-8000-000000000004",
}

resultados: list[dict] = []
# Tablas anteriores a las que las migraciones nuevas agregan filas de
# referencia (equivalencias de eventos y tipos de evento nuevos).
CATALOGOS_SEMBRADOS = {"equivalencia_historial", "tipo_evento"}


def anotar(paso: str, nombre: str, ok: bool, detalle: str = "") -> bool:
    resultados.append(
        {
            "paso": paso,
            "comprobacion": nombre,
            "ok": bool(ok),
            "detalle": "" if ok else str(detalle)[:400],
        }
    )
    print(
        f"  {'OK   ' if ok else 'FALLA'} {nombre}{(' - ' + str(detalle)[:400]) if detalle and not ok else ''}",
        flush=True,
    )
    return bool(ok)


# --- Base de datos ---------------------------------------------------------------


def _psycopg():
    import psycopg

    return psycopg


def url_base(url_admin: str, nombre: str, usuario: str | None = None) -> str:
    partes = urlsplit(url_admin)
    netloc = partes.netloc
    if usuario:
        netloc = f"{usuario}@{partes.hostname}:{partes.port or 5432}"
    return partes._replace(netloc=netloc, path=f"/{nombre}").geturl()


def ejecutar(url: str, texto: str) -> None:
    with _psycopg().connect(url, autocommit=True) as conexion:
        conexion.execute(texto)


def filas(url: str, texto: str) -> list[tuple]:
    with _psycopg().connect(url, autocommit=True) as conexion:
        return conexion.execute(texto).fetchall()


def archivos_anteriores() -> list[Path]:
    return [
        a for a in sorted(MIGRACIONES.glob("*.sql")) if a.name < PRIMERA_NUEVA
    ]


def archivos_nuevos() -> list[Path]:
    return [
        a for a in sorted(MIGRACIONES.glob("*.sql")) if a.name >= PRIMERA_NUEVA
    ]


def preparar_base(url_admin: str) -> str:
    sys.path.insert(0, str(BACKEND))
    from tests.postgres.base_local import ROLES_SUPABASE, url_admin_local

    url_admin_local(url_admin)
    with _psycopg().connect(url_admin, autocommit=True) as admin:
        admin.execute(f"drop database if exists {BASE} with (force)")
        for rol in ROLES_SUPABASE:
            if not admin.execute(
                "select 1 from pg_roles where rolname = %s", (rol,)
            ).fetchone():
                admin.execute(f"create role {rol} nologin")
        admin.execute(f"create database {BASE}")
    url = url_base(url_admin, BASE)
    for archivo in archivos_anteriores():
        ejecutar(url, archivo.read_text(encoding="utf-8"))
    for carpeta in ("referencia_operativa", "desarrollo"):
        for archivo in sorted(
            (RAIZ / "supabase" / "seeds" / carpeta).glob("*.sql")
        ):
            ejecutar(url, archivo.read_text(encoding="utf-8"))
    versiones = ", ".join(
        f"('{a.name.split('_')[0]}')" for a in archivos_anteriores()
    )
    cuentas = ", ".join(
        f"('{u}', '{c.lower()}@usuarios.rma.invalid')"
        for c, u in CUENTAS.items()
    )
    ejecutar(
        url,
        f"""
        create schema if not exists supabase_migrations;
        create table supabase_migrations.schema_migrations (version text primary key);
        insert into supabase_migrations.schema_migrations values {versiones};
        create schema if not exists auth;
        create table auth.users (id uuid primary key, email text, encrypted_password text);
        create table auth.identities (id uuid primary key default gen_random_uuid(), user_id uuid references auth.users (id));
        insert into auth.users (id, email) values {cuentas};
        insert into auth.identities (user_id) select id from auth.users;
        """,
    )
    for codigo, uid in CUENTAS.items():
        ejecutar(
            url,
            f"update rma.usuario set auth_user_id = '{uid}' where codigo = '{codigo}'",
        )
    with _psycopg().connect(url_admin, autocommit=True) as admin:
        if not admin.execute(
            "select 1 from pg_roles where rolname = %s", (ROL_API,)
        ).fetchone():
            admin.execute(f"create role {ROL_API} login")
        admin.execute(f"grant rma_backend to {ROL_API}")
        if not admin.execute(
            "select 1 from pg_roles where rolname = %s", (ROL_RESPALDO,)
        ).fetchone():
            admin.execute(f"create role {ROL_RESPALDO} login bypassrls")
        admin.execute(
            f"grant pg_read_all_data to {ROL_RESPALDO} with inherit true, set false"
        )
        admin.execute(
            f"alter role {ROL_RESPALDO} set default_transaction_read_only = on"
        )
    return url


SQL_LIBRO = "select codigo, tipo, cantidad::text, stock_fisico_resultante::text, stock_reservado_resultante::text from rma.movimiento_inventario order by codigo"
SQL_STOCK = "select clave, stock_fisico::text, stock_reservado::text from rma.insumo order by clave"
SQL_CONTEOS = """
select c.relname, (xpath('/row/n/text()', query_to_xml(format('select count(*) as n from rma.%I', c.relname), false, true, '')))[1]::text
  from pg_class c join pg_namespace s on s.oid = c.relnamespace
 where s.nspname = 'rma' and c.relkind = 'r' order by c.relname
"""


def instantanea(url: str) -> dict:
    return {
        "libro": filas(url, SQL_LIBRO),
        "stock": filas(url, SQL_STOCK),
        "conteos": dict(filas(url, SQL_CONTEOS)),
        "integridad": filas(url, "select * from rma.verificar_integridad()"),
    }


# --- Servidores ------------------------------------------------------------------


@contextlib.contextmanager
def servidor(raiz_backend: Path, url_db: str, puerto: int, registro: Path):
    entorno = {
        **os.environ,
        "RMA_PERSISTENCIA": "postgres",
        "RMA_DATABASE_URL": url_db,
        "RMA_DATA_DIR": str(
            registro.parent / f"datos_{raiz_backend.parent.parent.name}"
        ),
        "RMA_CATALOGO_ORIGEN": "ninguno",
        "PYTHONPATH": str(raiz_backend),
    }
    entorno.pop("RMA_TIPO_EQUIPO_CAMPO", None)
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
            cwd=raiz_backend,
            env=entorno,
            stdout=salida,
            stderr=subprocess.STDOUT,
        )
        try:
            import httpx

            for _ in range(60):
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
                        f"El servidor de {raiz_backend} terminó al arrancar (ver {registro})."
                    )
                time.sleep(1)
            else:
                raise RuntimeError("El servidor no respondió /health.")
            yield f"http://127.0.0.1:{puerto}"
        finally:
            proceso.terminate()
            try:
                proceso.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proceso.kill()


def correr(
    paso: str,
    nombre: str,
    argumentos: list[str],
    cwd: Path | None = None,
    registro: Path | None = None,
) -> bool:
    r = subprocess.run(
        argumentos,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    salida = (r.stdout or "") + (r.stderr or "")
    if registro:
        with registro.open("a", encoding="utf-8") as archivo:
            archivo.write(f"\n===== {nombre}\n{salida}")
    resumen = [
        linea
        for linea in salida.splitlines()
        if "RESULTADO" in linea or "FALLA" in linea or "Error" in linea
    ][:8]
    return anotar(
        paso, nombre, r.returncode == 0, " | ".join(resumen) or salida[-400:]
    )


# --- Fases que corren con los fixtures de cada versión (subproceso) ------------------


def fase_datos_anteriores(api: str) -> int:
    """Con el código y los fixtures PUBLICADOS: reserva abierta, consumo,
    cancelación y entrega."""
    import httpx

    from tests.fixtures import api_salidas as f

    c = httpx.Client(base_url=api, timeout=60)
    f.ok(
        c.post(
            "/api/inventory/INS-001/receipts",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "cantidad": "10",
                "motivo": "Ensayo: stock anterior",
            },
        )
    )
    consumida = f.definida(c, f.BATERIA)
    f.encolar(c, consumida)
    f.tomar(c, consumida)
    f.ejecutar(c, consumida)
    cancelada = f.definida(c, f.BATERIA)
    f.ok(f.cancelar_detalle(c, cancelada, "DET-001"))
    entregada = f.definida(c, f.BATERIA)
    f.encolar(c, entregada)
    f.tomar(c, entregada, tecnico=f.TECNICO)
    f.ejecutar(c, entregada)
    f.ok(f.aprobar(c, entregada, "DET-001"))
    f.notificar_pagar_entregar(c, entregada)
    # Al final, con la Ejecución iniciada y sin cerrar: la reserva real se
    # hace al iniciar (BR-REP-006) y queda abierta al migrar.
    abierta = f.definida(c, f.BATERIA)
    f.encolar(c, abierta)
    f.tomar(c, abierta)
    f.iniciar(c, abierta)
    print(
        json.dumps(
            {
                "abierta": abierta,
                "consumida": consumida,
                "cancelada": cancelada,
                "entregada": entregada,
            }
        )
    )
    return 0


def proyeccion(o: dict) -> dict:
    detalles = o.get("reparaciones_detail") or o.get("detalles") or []
    return {
        "estado": o.get("estado_workflow"),
        "detalles": sorted((d.get("id"), d.get("estado")) for d in detalles),
        "historial": len(o.get("historial") or []),
    }


def fase_leer_ordenes(api: str) -> int:
    """Cada Orden por su detalle y el listado; imprime las proyecciones."""
    import httpx

    c = httpx.Client(base_url=api, timeout=60)
    salida: dict = {"errores": {}}
    listado = c.get("/api/orders")
    salida["listado"] = listado.status_code
    proyecciones = {}
    for o in listado.json() if listado.status_code == 200 else []:
        r = c.get(f"/api/orders/{o['id']}")
        if r.status_code == 200:
            proyecciones[o["id"]] = proyeccion(r.json())
        else:
            salida["errores"][o["id"]] = (
                f"HTTP {r.status_code}: {r.text[:200]}"
            )
    salida["ordenes"] = proyecciones
    inventario = c.get("/api/inventory")
    salida["inventario"] = inventario.status_code
    for i in inventario.json() if inventario.status_code == 200 else []:
        r = c.get(f"/api/inventory/{i['id']}")
        if r.status_code != 200:
            salida["errores"][i["id"]] = (
                f"HTTP {r.status_code}: {r.text[:200]}"
            )
    for ruta in (
        "/api/reports/operational",
        "/api/catalogs/repair-types",
        "/api/me",
    ):
        r = c.get(ruta)
        salida[ruta] = r.status_code
    print(json.dumps(salida, default=str))
    return 0


def fase_nuevo(api: str, abierta: str) -> int:
    """Con el código y los fixtures NUEVOS, sobre los datos migrados."""
    import httpx

    from tests.fixtures import api_salidas as f

    c = httpx.Client(base_url=api, timeout=60)
    informe: dict = {}

    # La reserva abierta ANTES de migrar se consume con el código nuevo.
    def reservado() -> str:
        return next(
            str(i["reservado"])
            for i in f.ok(c.get("/api/inventory"))
            if i["id"] == "INS-001"
        )

    antes = reservado()
    orden = f.ok(c.get(f"/api/orders/{abierta}"))
    (activa,) = [
        e["id"] for e in orden["ejecuciones"] if e["estado"] == "EN_PROGRESO"
    ]
    f.ok(f.cerrar_ejecucion(c, abierta, activa))
    informe["reserva_anterior_consumida"] = [antes, reservado()]
    # Datos que solo existen con el código nuevo y que la versión anterior
    # va a leer en la vuelta atrás: un usuario con dos roles (el que encola
    # en los recorridos) y un descuento por Detalle (DEC-MI-03).
    roles = c.put(
        f"/api/admin/users/{f.COORDINADOR}/roles",
        json={
            "usuario_id": f.ADMINISTRADOR,
            "roles": ["COORDINADOR_RMA", "RECEPCION"],
        },
    )
    informe["dos_roles"] = roles.status_code
    con_descuento = f.definida(c, f.BATERIA)
    descuento = c.post(
        f"/api/orders/{con_descuento}/discount",
        json={
            "usuario_id": f.RECEPCION,
            "tipo": "PORCENTAJE",
            "valor": "10",
            "motivo": "Ensayo",
            "detalle_id": "DET-001",
        },
    )
    informe["descuento_por_detalle"] = descuento.status_code
    admin = {"usuario_id": f.ADMINISTRADOR}
    # Insumos de ensayo con control por lote y por serie.
    for clave, codigo, control in (
        ("INS-ENS-L", "ENS-LOTE", "LOTE"),
        ("INS-ENS-S", "ENS-SERIE", "SERIE"),
    ):
        f.ok(
            c.post(
                "/api/admin/supplies",
                json={
                    **admin,
                    "clave": clave,
                    "codigo": codigo,
                    "nombre": f"Ensayo {control}",
                    "activo": True,
                    "control": control,
                },
            )
        )
    r = c.post(
        "/api/inventory/INS-ENS-L/receipts",
        json={**admin, "cantidad": "3", "motivo": "Ensayo"},
    )
    informe["ingreso_sin_lote_rechazado"] = r.status_code
    f.ok(
        c.post(
            "/api/inventory/INS-ENS-L/receipts",
            json={
                **admin,
                "cantidad": "3",
                "motivo": "Ensayo",
                "lote": "L-ENS-1",
            },
        )
    )
    proveedor = f.ok(
        c.post(
            "/api/admin/suppliers",
            json={**admin, "nombre": "Proveedor de ensayo"},
        )
    )["id"]
    oc = f.ok(
        c.post(
            "/api/purchases/orders",
            json={
                "usuario_id": f.RECEPCION,
                "proveedor_id": proveedor,
                "items": [
                    {
                        "insumo_id": "INS-ENS-L",
                        "cantidad": "4",
                        "costo_unitario": "100",
                    },
                    {
                        "insumo_id": "INS-ENS-S",
                        "cantidad": "2",
                        "costo_unitario": "500",
                    },
                ],
            },
        )
    )["id"]
    f.ok(
        c.post(
            f"/api/purchases/orders/{oc}/confirm",
            json={"usuario_id": f.COORDINADOR},
        )
    )
    serie_mal = c.post(
        f"/api/purchases/orders/{oc}/receipts",
        json={
            "usuario_id": f.RECEPCION,
            "lineas": [
                {
                    "insumo_id": "INS-ENS-S",
                    "cantidad": "2",
                    "costo_unitario": "500",
                    "series": ["S-1"],
                }
            ],
        },
    )
    informe["series_incompletas_rechazadas"] = serie_mal.status_code
    f.ok(
        c.post(
            f"/api/purchases/orders/{oc}/receipts",
            json={
                "usuario_id": f.RECEPCION,
                "lineas": [
                    {
                        "insumo_id": "INS-ENS-S",
                        "cantidad": "2",
                        "costo_unitario": "500",
                        "series": ["S-ENS-1", "S-ENS-2"],
                    }
                ],
            },
        )
    )
    f.ok(
        c.post(
            f"/api/purchases/orders/{oc}/receipts",
            json={
                "usuario_id": f.RECEPCION,
                "lineas": [
                    {
                        "insumo_id": "INS-ENS-L",
                        "cantidad": "2",
                        "costo_unitario": "100",
                        "lote": "L-ENS-2",
                    }
                ],
            },
        )
    )

    # Dos recepciones a la vez por lo que queda (2): cada una pide 2.
    def recibir(numero: int):
        cliente = httpx.Client(base_url=api, timeout=60)
        return cliente.post(
            f"/api/purchases/orders/{oc}/receipts",
            json={
                "usuario_id": f.RECEPCION,
                "lineas": [
                    {
                        "insumo_id": "INS-ENS-L",
                        "cantidad": "2",
                        "costo_unitario": "100",
                        "lote": f"L-ENS-C{numero}",
                    }
                ],
            },
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as hilos:
        informe["concurrentes"] = sorted(hilos.map(recibir, (1, 2)))
    estado = f.ok(c.get(f"/api/purchases/orders/{oc}"))
    informe["oc_estado"] = estado["estado"]
    informe["oc_renglones"] = estado["renglones"]
    # Idempotencia de un ingreso: misma clave, una sola vez.
    clave = "ensayo-ingreso-idempotente"
    cuerpo = {
        **admin,
        "cantidad": "1",
        "motivo": "Ensayo idempotente",
        "lote": "L-ENS-1",
    }
    respuestas = [
        c.post(
            "/api/inventory/INS-ENS-L/receipts",
            json=cuerpo,
            headers={"Idempotency-Key": clave},
        ).status_code
        for _ in range(2)
    ]
    informe["ingreso_idempotente"] = respuestas
    informe["saldos_lote"] = f.ok(c.get("/api/inventory/INS-ENS-L/lots"))
    informe["saldos_serie"] = f.ok(c.get("/api/inventory/INS-ENS-S/lots"))
    informe["saldos_bat"] = f.ok(c.get("/api/inventory/INS-001/lots"))
    print(json.dumps(informe, default=str))
    return 0


def fase_escribir_anterior(api: str) -> int:
    """Con el código PUBLICADO sobre la base migrada: un recorrido que
    escribe (alta, reserva, consumo) y un ingreso a un insumo por lote."""
    import httpx

    from tests.fixtures import api_salidas as f

    c = httpx.Client(base_url=api, timeout=60)
    informe: dict = {}
    orden_id = f.definida(c, f.BATERIA)
    f.encolar(c, orden_id)
    f.tomar(c, orden_id)
    f.ejecutar(c, orden_id)
    informe["recorrido"] = orden_id
    r = c.post(
        "/api/inventory/INS-ENS-L/receipts",
        json={
            "usuario_id": f.ADMINISTRADOR,
            "cantidad": "1",
            "motivo": "Ensayo: version anterior",
        },
    )
    informe["ingreso_lote_con_version_anterior"] = (
        f"HTTP {r.status_code}: {r.text[:200]}"
    )
    print(json.dumps(informe, default=str))
    return 0


def subfase(raiz_backend: Path, fase: str, *args: str, registro: Path) -> dict:
    r = subprocess.run(
        [
            sys.executable,
            __file__,
            "--fase",
            fase,
            "--raiz-backend",
            str(raiz_backend),
            *args,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONPATH": str(raiz_backend)},
    )
    with registro.open("a", encoding="utf-8") as archivo:
        archivo.write(
            f"\n===== fase {fase} ({raiz_backend})\n{r.stdout}\n{r.stderr}"
        )
    if r.returncode != 0:
        raise RuntimeError(f"fase {fase}: {(r.stderr or r.stdout)[-600:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


# --- Respaldo y reinicio -------------------------------------------------------------


def ruta_docker(ruta: Path) -> str:
    return str(ruta).replace("\\", "/")


def ensayar_respaldo(contenedor_pg: str, registro: Path) -> None:
    with tempfile.TemporaryDirectory() as temporal:
        herramientas = Path(temporal) / "herramientas"
        (herramientas / "migraciones").mkdir(parents=True)
        for nombre in (
            "respaldar.sh",
            "restaurar.sh",
            "ensayar_restauracion.sh",
        ):
            contenido = (
                (RAIZ / "supabase" / "scripts" / "respaldo" / nombre)
                .read_bytes()
                .replace(b"\r\n", b"\n")
            )
            (herramientas / nombre).write_bytes(contenido)
        for archivo in sorted(MIGRACIONES.glob("*.sql")):
            shutil.copy(archivo, herramientas / "migraciones" / archivo.name)
        anotar(
            "7",
            "herramientas con las 35 migraciones",
            len(list((herramientas / "migraciones").glob("*.sql"))) == 35,
        )
        correr(
            "7",
            "ensayar_restauracion.sh (respaldo con rol de solo lectura, restauración en ensayo y aplicar, secuencias, Auth)",
            [
                "docker",
                "run",
                "--rm",
                "--network",
                f"container:{contenedor_pg}",
                "-v",
                f"{ruta_docker(herramientas)}:/herramientas",
                "-e",
                f"RMA_RESPALDO_DB_URL=postgresql://{ROL_RESPALDO}@127.0.0.1:5432/{BASE}",
                "postgres:17-alpine",
                "sh",
                "/herramientas/ensayar_restauracion.sh",
            ],
            registro=registro,
        )
        salida = registro.read_text(encoding="utf-8")
        anotar(
            "7",
            "ENSAYO_RESTAURACION_OK en la salida",
            "ENSAYO_RESTAURACION_OK" in salida,
        )


def clonar(url_admin: str, nombre: str) -> str:
    """Copia de la base del ensayo (sin conexiones abiertas a ella)."""
    with _psycopg().connect(url_admin, autocommit=True) as admin:
        admin.execute(f"drop database if exists {nombre} with (force)")
        admin.execute(f"create database {nombre} template {BASE}")
    return url_base(url_admin, nombre)


def texto_reinicio(url: str, modo: str) -> str:
    """01_reiniciar.sql con las Órdenes que tiene la base y el modo."""
    texto = (
        RAIZ / "supabase" / "scripts" / "reinicio_uat" / "01_reiniciar.sql"
    ).read_text(encoding="utf-8")
    ordenes = [
        fila[0]
        for fila in filas(url, "select codigo from rma.orden order by codigo")
    ]
    inicio = texto.index("v_ordenes constant text[] := array[")
    fin = texto.index("];", inicio) + 2
    texto = (
        texto[:inicio]
        + "v_ordenes constant text[] := array["
        + ", ".join(f"'{o}'" for o in ordenes)
        + "]::text[];"
        + texto[fin:]
    )
    return texto.replace(
        "v_modo constant text := 'ensayo';",
        f"v_modo constant text := '{modo}';",
    )


def reiniciar(url: str, modo: str) -> str:
    """Corre el reinicio; devuelve los avisos o el error (el ensayo termina
    con un error a propósito)."""
    avisos: list[str] = []
    with _psycopg().connect(url, autocommit=True) as conexion:
        conexion.add_notice_handler(lambda d: avisos.append(d.message_primary))
        try:
            conexion.execute(texto_reinicio(url, modo))
        except Exception as error:  # noqa: BLE001
            return str(error)
    return " ".join(avisos)


def ensayar_reinicio(url_admin: str, registro: Path) -> None:
    url = url_base(url_admin, BASE)
    texto = (
        RAIZ / "supabase" / "scripts" / "reinicio_uat" / "01_reiniciar.sql"
    ).read_text(encoding="utf-8")
    ordenes = [
        fila[0]
        for fila in filas(url, "select codigo from rma.orden order by codigo")
    ]
    inicio = texto.index("v_ordenes constant text[] := array[")
    fin = texto.index("];", inicio) + 2
    texto = (
        texto[:inicio]
        + "v_ordenes constant text[] := array["
        + ", ".join(f"'{o}'" for o in ordenes)
        + "];"
        + texto[fin:]
    )
    try:
        ejecutar(url, texto)
        anotar(
            "8",
            "01_reiniciar.sql en ensayo",
            False,
            "terminó sin el error de ensayo",
        )
    except Exception as error:  # noqa: BLE001 - el ensayo termina con un error a propósito
        mensaje = str(error)
        with registro.open("a", encoding="utf-8") as archivo:
            archivo.write(f"\n===== reinicio (ensayo)\n{mensaje}\n")
        anotar(
            "8",
            "01_reiniciar.sql en ensayo: ENSAYO OK (todas las tablas clasificadas, integridad sin problemas)",
            "ENSAYO OK" in mensaje,
            mensaje,
        )


# --- Orquestación ----------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--url-admin", default="postgresql://postgres@127.0.0.1:55432/postgres"
    )
    p.add_argument(
        "--contenedor-pg",
        default="rma-it1-pg",
        help="contenedor Docker del PostgreSQL local",
    )
    p.add_argument(
        "--codigo-anterior",
        help="exportación del commit publicado (git archive 5c6137e)",
    )
    p.add_argument("--puerto", type=int, default=8100)
    p.add_argument("--informe", required=False)
    p.add_argument("--fase", help=argparse.SUPPRESS)
    p.add_argument("--raiz-backend", help=argparse.SUPPRESS)
    p.add_argument("--api", help=argparse.SUPPRESS)
    p.add_argument("--orden", help=argparse.SUPPRESS)
    a = p.parse_args()

    if a.fase:
        sys.path.insert(0, a.raiz_backend)
        return {
            "datos": lambda: fase_datos_anteriores(a.api),
            "leer": lambda: fase_leer_ordenes(a.api),
            "nuevo": lambda: fase_nuevo(a.api, a.orden),
            "escribir-anterior": lambda: fase_escribir_anterior(a.api),
        }[a.fase]()

    anterior = Path(a.codigo_anterior).resolve() / "app" / "backend"
    if not (anterior / "app" / "main.py").exists():
        print(
            "--codigo-anterior tiene que ser una exportación del commit publicado."
        )
        return 2
    trabajo = Path(tempfile.mkdtemp(prefix="ensayo_mi_"))
    registro = trabajo / "registro.log"
    print(f"Registro: {registro}")
    url_api = url_base(a.url_admin, BASE, ROL_API)
    url = None
    try:
        print("\n1. Base anterior (23 migraciones)")
        url = preparar_base(a.url_admin)
        anotar(
            "1",
            "23 migraciones y cargas aplicadas",
            filas(
                url,
                "select count(*) from supabase_migrations.schema_migrations",
            )
            == [(23,)],
        )
        anotar(
            "1",
            "47 tablas en rma",
            filas(
                url, "select count(*) from pg_tables where schemaname = 'rma'"
            )
            == [(47,)],
        )

        print("\n2. Datos con el código publicado")
        with servidor(
            anterior, url_api, a.puerto, trabajo / "anterior.log"
        ) as api:
            correr(
                "2",
                "E2E de la macroiteración V1.4 con el código publicado",
                [
                    sys.executable,
                    str(
                        anterior.parent.parent
                        / "supabase"
                        / "scripts"
                        / "validacion_uat"
                        / "probar_macro_v14.py"
                    ),
                    "--api",
                    api,
                    "--sin-autenticacion",
                    "--escribir",
                ],
                registro=registro,
            )
            datos = subfase(anterior, "datos", "--api", api, registro=registro)
            anotar(
                "2", "reserva abierta, consumo, cancelación y entrega", True
            )
            lectura_antes = subfase(
                anterior, "leer", "--api", api, registro=registro
            )
        antes = instantanea(url)
        anotar(
            "2",
            "stock con una reserva abierta",
            any(r[2] != "0.000" for r in antes["stock"]),
            str(antes["stock"]),
        )
        anotar(
            "2",
            "integridad sin problemas antes de migrar",
            antes["integridad"] == [],
            str(antes["integridad"]),
        )

        print("\n3. Las 12 migraciones nuevas")
        for archivo in archivos_nuevos():
            ejecutar(url, archivo.read_text(encoding="utf-8"))
            ejecutar(
                url,
                f"insert into supabase_migrations.schema_migrations values ('{archivo.name.split('_')[0]}')",
            )
        despues = instantanea(url)
        anotar(
            "3",
            "35 migraciones; 69 tablas",
            (
                filas(
                    url,
                    "select count(*) from supabase_migrations.schema_migrations",
                ),
                filas(
                    url,
                    "select count(*) from pg_tables where schemaname = 'rma'",
                ),
            )
            == ([(35,)], [(69,)]),
        )
        anotar(
            "3",
            "libro de inventario idéntico (nada duplicado ni perdido)",
            despues["libro"] == antes["libro"],
            f"{len(antes['libro'])} -> {len(despues['libro'])}",
        )
        anotar(
            "3",
            "stock físico y reservado idénticos",
            despues["stock"] == antes["stock"],
            f"{antes['stock']} -> {despues['stock']}",
        )
        cambiadas = {
            t: (n, despues["conteos"].get(t))
            for t, n in antes["conteos"].items()
            if despues["conteos"].get(t) != n
        }
        anotar(
            "3",
            "de las 47 tablas anteriores solo cambian los catálogos que siembran las migraciones",
            set(cambiadas) <= CATALOGOS_SEMBRADOS,
            json.dumps(cambiadas),
        )
        resultados.append(
            {
                "paso": "3",
                "comprobacion": "tablas anteriores con filas nuevas por las migraciones (informativo)",
                "ok": True,
                "detalle": json.dumps(cambiadas),
            }
        )
        anotar(
            "3",
            "todos los insumos SIN_LOTE, ningún lote",
            filas(
                url,
                "select count(*) filter (where control <> 'SIN_LOTE'), (select count(*) from rma.lote_insumo) from rma.insumo",
            )
            == [(0, 0)],
        )
        anotar(
            "3",
            "sin Tipos de Equipo",
            filas(url, "select count(*) from rma.tipo_equipo") == [(0,)],
        )
        anotar(
            "3",
            "integridad sin problemas después de migrar",
            despues["integridad"] == [],
            str(despues["integridad"]),
        )
        filas_tablas = filas(
            url,
            "select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'rma' and c.relkind = 'r' and has_table_privilege('rma_backend', c.oid, 'SELECT')",
        )
        anotar(
            "3",
            "rma_backend lee las 69 tablas",
            filas_tablas == [(69,)],
            str(filas_tablas),
        )

        print("\n4. Código nuevo (DC12 sin configurar)")
        with servidor(
            BACKEND, url_api, a.puerto, trabajo / "nuevo.log"
        ) as api:
            lectura_nueva = subfase(
                BACKEND, "leer", "--api", api, registro=registro
            )
            anotar(
                "4",
                "todas las Órdenes anteriores se leen",
                not lectura_nueva["errores"],
                str(lectura_nueva["errores"]),
            )
            iguales = {
                k: v
                for k, v in lectura_antes["ordenes"].items()
                if lectura_nueva["ordenes"].get(k) != v
            }
            anotar(
                "4",
                "estado, Detalles e historial de las Órdenes anteriores iguales",
                not iguales,
                json.dumps(iguales)[:400],
            )
            nuevo = subfase(
                BACKEND,
                "nuevo",
                "--api",
                api,
                "--orden",
                datos["abierta"],
                registro=registro,
            )
            correr(
                "4",
                "E2E de la macroiteración integral (código nuevo, base migrada)",
                [
                    sys.executable,
                    str(
                        RAIZ
                        / "supabase"
                        / "scripts"
                        / "validacion_uat"
                        / "probar_macro_integral.py"
                    ),
                    "--api",
                    api,
                    "--sin-autenticacion",
                    "--escribir",
                    "--permitir-ordenes",
                ],
                registro=registro,
            )
        anotar(
            "4",
            "la reserva abierta antes de migrar se consumió",
            [float(x) for x in nuevo["reserva_anterior_consumida"]]
            == [1.0, 0.0],
        )
        anotar(
            "4",
            "un usuario con dos roles (Coordinación y Recepción)",
            nuevo["dos_roles"] == 200,
            str(nuevo["dos_roles"]),
        )
        anotar(
            "4",
            "descuento por Detalle",
            nuevo["descuento_por_detalle"] == 200,
            str(nuevo["descuento_por_detalle"]),
        )
        anotar(
            "4",
            "ingreso sin lote a un insumo por lote rechazado",
            nuevo["ingreso_sin_lote_rechazado"] == 409,
            str(nuevo["ingreso_sin_lote_rechazado"]),
        )
        anotar(
            "4",
            "series incompletas rechazadas",
            nuevo["series_incompletas_rechazadas"] == 409,
            str(nuevo["series_incompletas_rechazadas"]),
        )
        anotar(
            "4",
            "recepciones concurrentes: una entra y la otra se rechaza",
            nuevo["concurrentes"] == [200, 409],
            str(nuevo["concurrentes"]),
        )
        anotar(
            "4",
            "la OC queda RECIBIDA",
            nuevo["oc_estado"] == "RECIBIDA",
            nuevo["oc_estado"],
        )
        anotar(
            "4",
            "ingreso idempotente: misma respuesta, una sola vez",
            nuevo["ingreso_idempotente"] == [200, 200],
            str(nuevo["ingreso_idempotente"]),
        )
        lotes = {
            s["lote"]["numero"]: s["saldo"]
            for s in nuevo["saldos_lote"]["lotes"]
        }
        anotar(
            "4",
            "saldos por lote (L-ENS-1 4 con el idempotente, L-ENS-2 2, uno de los concurrentes 2)",
            lotes.get("L-ENS-1") in ("4", "4.000")
            and lotes.get("L-ENS-2") in ("2", "2.000")
            and len(lotes) == 3,
            str(lotes),
        )
        anotar(
            "4",
            "series de a una unidad",
            sorted(s["lote"]["numero"] for s in nuevo["saldos_serie"]["lotes"])
            == ["S-ENS-1", "S-ENS-2"],
            str(nuevo["saldos_serie"]["lotes"])[:200],
        )
        anotar(
            "4",
            "BAT-IP14 sigue todo sin lote identificado",
            nuevo["saldos_bat"]["sin_lote_identificado"]
            == nuevo["saldos_bat"]["stock_fisico"],
            str(nuevo["saldos_bat"]),
        )
        con_nuevos = instantanea(url)
        anotar(
            "4",
            "integridad sin problemas con los datos del código nuevo",
            con_nuevos["integridad"] == [],
            str(con_nuevos["integridad"]),
        )
        anotar(
            "4",
            "DC12: ningún Tipo de Equipo creado",
            filas(url, "select count(*) from rma.tipo_equipo") == [(0,)],
        )
        tipos = filas(
            url,
            "select tipo, count(*) from rma.movimiento_inventario group by tipo order by tipo",
        )
        anotar(
            "4",
            "el libro tiene DESPERDICIO y DEVOLUCION del código nuevo",
            {"DESPERDICIO", "DEVOLUCION"} <= {t for t, _ in tipos},
            str(tipos),
        )

        print("\n5a. Vuelta atrás con todos los datos del código nuevo")
        desperdicios = filas(
            url,
            "select count(*) from rma.movimiento_inventario where tipo = 'DESPERDICIO'",
        )[0][0]
        anotar(
            "5a",
            f"control previo a la vuelta atrás: {desperdicios} movimientos DESPERDICIO",
            desperdicios > 0,
        )
        log_atras = trabajo / "vuelta_atras.log"
        with servidor(anterior, url_api, a.puerto, log_atras) as api:
            lectura_atras = subfase(
                anterior, "leer", "--api", api, registro=registro
            )
        causa = "input_value='DESPERDICIO'" in log_atras.read_text(
            encoding="utf-8", errors="replace"
        )
        anotar(
            "5a",
            "incompatibilidad conocida: con DESPERDICIO en el libro la versión anterior no lista Órdenes ni inventario (500)",
            lectura_atras["listado"] == 500 and causa,
            f"listado {lectura_atras['listado']}, causa DESPERDICIO: {causa}",
        )

        print(
            "\n5b. Vuelta atrás sobre una copia sin DESPERDICIO (otras incompatibilidades)"
        )
        copia = clonar(a.url_admin, f"{BASE}_sin_desperdicio")
        ejecutar(
            copia,
            "set session_replication_role = replica; "
            "update rma.movimiento_inventario set tipo = 'CONSUMO' where tipo = 'DESPERDICIO'; "
            "update rma.ejecucion_insumo set desperdicio = 0 where desperdicio > 0; "
            "set session_replication_role = origin;",
        )
        url_copia = url_base(a.url_admin, f"{BASE}_sin_desperdicio", ROL_API)
        with servidor(
            anterior, url_copia, a.puerto, trabajo / "vuelta_atras_copia.log"
        ) as api:
            lectura_copia = subfase(
                anterior, "leer", "--api", api, registro=registro
            )
            total = filas(copia, "select count(*) from rma.orden")[0][0]
            anotar(
                "5b",
                "listado e inventario responden",
                (lectura_copia["listado"], lectura_copia["inventario"])
                == (200, 200),
                str((lectura_copia["listado"], lectura_copia["inventario"])),
            )
            anotar(
                "5b",
                f"las {total} Órdenes se leen con la versión anterior",
                not lectura_copia["errores"]
                and len(lectura_copia["ordenes"]) == total,
                json.dumps(lectura_copia["errores"])[:400],
            )
            cambiadas = {
                k: v
                for k, v in lectura_antes["ordenes"].items()
                if lectura_copia["ordenes"].get(k, {}).get("estado")
                != v["estado"]
                and k != datos["abierta"]
            }
            anotar(
                "5b",
                "las Órdenes anteriores conservan su estado",
                not cambiadas,
                json.dumps(cambiadas)[:300],
            )
            log_copia = trabajo / "vuelta_atras_copia.log"
            try:
                subfase(
                    anterior,
                    "escribir-anterior",
                    "--api",
                    api,
                    registro=registro,
                )
                varios_roles = False
            except RuntimeError:
                varios_roles = "tiene 2 roles" in log_copia.read_text(
                    encoding="utf-8", errors="replace"
                )
            anotar(
                "5b",
                "incompatibilidad conocida: un usuario con varios roles impide escribir a la versión anterior, y es la causa",
                varios_roles,
            )
            # Lo que haría Administración antes de volver: un rol por usuario.
            ejecutar(
                copia,
                "delete from rma.usuario_rol ur using rma.usuario u, rma.rol r "
                "where u.id = ur.usuario_id and r.id = ur.rol_id "
                "and u.codigo = 'COORD-001' and r.codigo = 'RECEPCION'",
            )
            escrito = subfase(
                anterior, "escribir-anterior", "--api", api, registro=registro
            )
            anotar(
                "5b",
                "la versión anterior escribe (alta, reserva y consumo)",
                bool(escrito.get("recorrido")),
            )
            resultados.append(
                {
                    "paso": "5b",
                    "comprobacion": "ingreso a un insumo por lote con la versión anterior (informativo)",
                    "ok": True,
                    "detalle": escrito["ingreso_lote_con_version_anterior"],
                }
            )
            print(
                f"  INFO  ingreso a un insumo por lote con la versión anterior: {escrito['ingreso_lote_con_version_anterior']}"
            )
        anotar(
            "5b",
            "integridad sin problemas después de escribir con la versión anterior",
            filas(copia, "select * from rma.verificar_integridad()") == [],
            str(filas(copia, "select * from rma.verificar_integridad()")),
        )

        print(
            "\n5c. Vuelta atrás del UAT: reinicio de los datos ficticios y versión anterior"
        )
        reiniciada = clonar(a.url_admin, f"{BASE}_reiniciada")
        mensaje = reiniciar(reiniciada, "aplicar")
        anotar(
            "5c",
            "01_reiniciar.sql aplicado sobre los datos de las dos versiones",
            "REINICIO APLICADO" in mensaje,
            mensaje,
        )
        anotar(
            "5c",
            "sin Órdenes, compras, lotes ni DESPERDICIO",
            filas(
                reiniciada,
                "select (select count(*) from rma.orden), (select count(*) from rma.orden_compra), "
                "(select count(*) from rma.lote_insumo), "
                "(select count(*) from rma.movimiento_inventario where tipo = 'DESPERDICIO')",
            )
            == [(0, 0, 0, 0)],
        )
        ejecutar(
            reiniciada,
            (
                RAIZ
                / "supabase"
                / "scripts"
                / "reinicio_uat"
                / "03_verificar.sql"
            ).read_text(encoding="utf-8"),
        )
        anotar("5c", "03_verificar.sql corre sobre el esquema nuevo", True)
        # Paso del procedimiento de vuelta atrás: un rol por usuario.
        varios = filas(
            reiniciada,
            "select count(*) from (select usuario_id from rma.usuario_rol group by usuario_id having count(*) > 1) x",
        )[0][0]
        anotar(
            "5c",
            f"control previo: {varios} usuario(s) con varios roles",
            varios == 1,
        )
        ejecutar(
            reiniciada,
            "delete from rma.usuario_rol ur using rma.usuario u, rma.rol r "
            "where u.id = ur.usuario_id and r.id = ur.rol_id "
            "and u.codigo = 'COORD-001' and r.codigo = 'RECEPCION'",
        )
        url_reiniciada = url_base(a.url_admin, f"{BASE}_reiniciada", ROL_API)
        with servidor(
            anterior,
            url_reiniciada,
            a.puerto,
            trabajo / "vuelta_atras_reinicio.log",
        ) as api:
            lectura_reinicio = subfase(
                anterior, "leer", "--api", api, registro=registro
            )
            anotar(
                "5c",
                "la versión anterior lista Órdenes e inventario",
                (lectura_reinicio["listado"], lectura_reinicio["inventario"])
                == (200, 200),
                str(
                    (
                        lectura_reinicio["listado"],
                        lectura_reinicio["inventario"],
                    )
                ),
            )
            escrito = subfase(
                anterior, "escribir-anterior", "--api", api, registro=registro
            )
            anotar(
                "5c",
                "la versión anterior escribe (alta, reserva y consumo)",
                bool(escrito.get("recorrido")),
            )
        anotar(
            "5c",
            "integridad sin problemas",
            filas(reiniciada, "select * from rma.verificar_integridad()")
            == [],
        )

        print("\n5d. Reinicio aplicado y su vuelta atrás (02_restaurar.sql)")
        restaurada = clonar(a.url_admin, f"{BASE}_restaurada")
        conteos = dict(filas(restaurada, SQL_CONTEOS))
        mensaje = reiniciar(restaurada, "aplicar")
        anotar(
            "5d", "reinicio aplicado", "REINICIO APLICADO" in mensaje, mensaje
        )
        ejecutar(
            restaurada,
            (
                RAIZ
                / "supabase"
                / "scripts"
                / "reinicio_uat"
                / "02_restaurar.sql"
            ).read_text(encoding="utf-8"),
        )
        restaurados = dict(filas(restaurada, SQL_CONTEOS))
        distintas = {
            t: (n, restaurados.get(t))
            for t, n in conteos.items()
            if restaurados.get(t) != n
            and t not in ("accion_usuario", "movimiento_inventario")
        }
        anotar(
            "5d",
            "02_restaurar.sql devuelve todas las tablas operativas, también las nuevas",
            not distintas,
            json.dumps(distintas),
        )
        anotar(
            "5d",
            "stock e integridad iguales a antes del reinicio",
            filas(restaurada, SQL_STOCK) == filas(url, SQL_STOCK)
            and filas(restaurada, "select * from rma.verificar_integridad()")
            == [],
            str(filas(restaurada, SQL_STOCK)),
        )

        print("\n6. Regreso al código nuevo")
        with servidor(
            BACKEND, url_api, a.puerto, trabajo / "regreso.log"
        ) as api:
            lectura_regreso = subfase(
                BACKEND, "leer", "--api", api, registro=registro
            )
            total = filas(url, "select count(*) from rma.orden")[0][0]
            anotar(
                "6",
                f"las {total} Órdenes se leen con el código nuevo",
                not lectura_regreso["errores"]
                and len(lectura_regreso["ordenes"]) == total,
                json.dumps(lectura_regreso["errores"])[:300],
            )

        print("\n7. Respaldo y restauración (ensayar_restauracion.sh)")
        ensayar_respaldo(a.contenedor_pg, registro)

        print("\n8. Reinicio del UAT en ensayo")
        ensayar_reinicio(a.url_admin, registro)
    except Exception as error:  # noqa: BLE001
        anotar(
            "x",
            "el ensayo terminó sin errores",
            False,
            f"{type(error).__name__}: {error}",
        )
        traceback.print_exc(limit=3)
    finally:
        fallas = [x for x in resultados if not x["ok"]]
        print(
            f"\nRESULTADO: {'OK' if not fallas else f'{len(fallas)} FALLAS'} ({len(resultados)} comprobaciones). Registro: {registro}"
        )
        if a.informe:
            Path(a.informe).write_text(
                json.dumps(
                    {"comprobaciones": resultados, "registro": str(registro)},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
    return 0 if not [x for x in resultados if not x["ok"]] else 1


if __name__ == "__main__":
    sys.exit(main())
