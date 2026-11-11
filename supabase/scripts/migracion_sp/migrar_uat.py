# ruff: noqa: E501  (SQL y mensajes largos: partirlos no los hace más claros)
"""Migración del UAT de Supabase Oregón a un proyecto nuevo (São Paulo).

Plan y decisiones: docs/MIGRACION_SUPABASE_SAO_PAULO.md. Cada uso contra un
proyecto remoto requiere autorización explícita; sin ``--aplicar`` ningún
subcomando escribe.

Destinos: ``local`` (la base de ``supabase start``), un project ref
(``--remote=<ref>``, sesión de la CLI) o una URL de PostgreSQL (pruebas
locales). Todas las consultas pasan por ``npx supabase db query``: el origen
siempre en solo lectura.

Subcomandos:

  comparar   Esquema, migraciones, permisos y datos de referencia y maestros
             del origen contra el destino. Solo lectura.
  maestros   Copia los datos maestros del UAT, por id o por código, y el
             ingreso de stock inicial. Idempotente: lo que ya está igual no
             se toca; lo que choca aborta sin cambios.
  cuentas    Crea en el Auth del destino las cuentas vinculadas a usuarios de
             RMA, con el mismo id y el mismo hash bcrypt (API de
             administración, ``password_hash``). Los hashes viven solo en
             memoria: nunca se imprimen ni se escriben en disco. Idempotente.
  verificar  Criterios de aceptación del destino (sección 9 del plan).

Credenciales: la clave secreta del Auth del destino se pide sin eco (o se lee
de SUPABASE_SECRET_KEY_DESTINO). No hay credenciales en este archivo.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
CLI = ["supabase@3.1.0"]
BCRYPT = re.compile(r"^\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}$")

# Tablas maestras que se copian con el mismo id, en orden de dependencias.
POR_ID = [
    ("usuario", ["id"]),
    ("empresa", ["id"]),
    ("texto_legal", ["id"]),
    ("motivo_ajuste", ["id"]),
    ("modelo_equipo", ["id"]),
    ("tipo_reparacion", ["id"]),
    ("insumo", ["id"]),
    ("mesa_trabajo", ["id"]),
    ("mesa_tipo_reparacion", ["mesa_trabajo_id", "tipo_reparacion_id"]),
    ("tipo_reparacion_insumo", ["tipo_reparacion_id", "insumo_id"]),
]

OPERATIVAS = [
    "accion_usuario",
    "ajuste_garantia",
    "auditoria_tecnica",
    "checkin",
    "cliente",
    "control_tecnico",
    "decision_cliente",
    "descuento",
    "detalle",
    "detalle_version",
    "devolucion_dinero",
    "documento_cliente",
    "documento_emitido",
    "ejecucion",
    "ejecucion_insumo",
    "equipo",
    "evento_negocio",
    "foto",
    "movimiento_inventario",
    "orden",
    "orden_detalle_origen",
    "override_insumo",
    "override_recursos",
    "pago",
    "recepcion",
    "recepcion_nota",
    "recepcion_version",
    "salida",
    "toma",
]


class Falla(Exception):
    """Error que se informa sin traza (y sin datos sensibles)."""


# --------------------------------------------------------------------------
# Acceso a las bases por la CLI de Supabase
# --------------------------------------------------------------------------


def consultar(destino: str, sql: str, escribir: bool = False) -> list[dict]:
    """Ejecuta ``sql`` con ``supabase db query`` y devuelve las filas.

    El SQL va en un archivo temporal privado que se borra enseguida. Nunca
    contiene hashes ni claves: las cuentas viajan por la API de Auth.
    """
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        raise Falla("No se encontró npx.")
    carpeta = tempfile.mkdtemp(prefix="rma-migracion-")
    archivo = Path(carpeta) / "consulta.sql"
    try:
        archivo.write_text(sql, encoding="utf-8")
        orden = [
            npx,
            "-y",
            *CLI,
            "db",
            "query",
            # Formato fijo: sin --agent, la CLI cambia de formato según quién
            # la ejecute (sobre de agente o lista de filas en una terminal).
            "--agent",
            "no",
            "--output-format",
            "json",
            "-f",
            str(archivo),
        ]
        if destino != "local":
            orden.append(f"--remote={destino}")
        orden.append("--yes" if escribir else "--read-only")
        resultado = subprocess.run(
            orden,
            cwd=RAIZ,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,
        )
    finally:
        archivo.unlink(missing_ok=True)
        os.rmdir(carpeta)
    return interpretar_salida(
        resultado.stdout,
        resultado.returncode,
        _nombre(destino),
        resultado.stderr,
    )


ETIQUETA_COMANDO = re.compile(r"[A-Z]+(?: [A-Z]+)*(?: \d+)*")


def interpretar_salida(
    stdout: str, codigo: int, nombre: str, stderr: str = ""
) -> list[dict]:
    """Filas de ``supabase db query --output-format json``, o ``Falla``.

    Formatos reales de la CLI 3.1.0:
    - en una terminal (``--agent no``): la lista de filas, ``[{...}, ...]``;
    - para un agente: ``{"boundary": ..., "rows": [...], "warning": ...}``;
    - un error: ``{"_tag": "Error", "error": {"message": ...}}`` con código
      de salida distinto de 0;
    - una sentencia sin filas en la base local: solo la etiqueta del comando
      (``DROP DATABASE``).

    Se interpreta la salida entera: un código de salida distinto de 0, un
    sobre de error, texto que sobra después del JSON o una forma desconocida
    son siempre una falla, nunca filas.
    """
    texto = stdout.strip()
    valor = None
    if texto[:1] in ("[", "{"):
        try:
            valor, fin = json.JSONDecoder().raw_decode(texto)
        except ValueError as error:
            raise Falla(
                f"{nombre}: salida de la CLI que no es JSON ({error.msg})."
            ) from None
        if texto[fin:].strip():
            raise Falla(
                f"{nombre}: la salida de la CLI tiene datos después del JSON."
            )
    if codigo != 0 or (
        isinstance(valor, dict) and ("_tag" in valor or "error" in valor)
    ):
        detalle = valor.get("error") if isinstance(valor, dict) else None
        mensaje = detalle.get("message") if isinstance(detalle, dict) else None
        raise Falla(
            f"{nombre}: {(mensaje or stderr.strip() or 'error de la CLI')[-500:]}"
        )
    if valor is None:
        if texto == "" or ETIQUETA_COMANDO.fullmatch(texto):
            return []  # sentencia sin filas
        raise Falla(f"{nombre}: salida inesperada de la CLI.")
    filas = valor.get("rows") if isinstance(valor, dict) else valor
    if not isinstance(filas, list) or not all(
        isinstance(f, dict) for f in filas
    ):
        raise Falla(f"{nombre}: la salida de la CLI no es una lista de filas.")
    return filas


def _nombre(destino: str) -> str:
    """Nombre del destino para los mensajes, sin contraseñas de una URL."""
    if destino.startswith("postgres"):
        partes = urllib.parse.urlsplit(destino)
        return f"{partes.hostname}:{partes.port}{partes.path}"
    return destino


def uno(destino: str, sql: str, escribir: bool = False):
    filas = consultar(destino, sql, escribir)
    valor = next(iter(filas[0].values())) if filas else None
    return (
        json.loads(valor)
        if isinstance(valor, str) and valor[:1] in "[{"
        else valor
    )


# --------------------------------------------------------------------------
# Huellas comparables entre proyectos
# --------------------------------------------------------------------------

HUELLA = r"""
with f as (
  select 'esquema.funciones' k, md5(string_agg(pg_get_functiondef(p.oid), '|' order by p.oid::regprocedure::text)) v
    from pg_proc p where p.pronamespace = 'rma'::regnamespace
  union all select 'esquema.triggers', md5(string_agg(c.relname || pg_get_triggerdef(t.oid), '|' order by c.relname, t.tgname))
    from pg_trigger t join pg_class c on c.oid = t.tgrelid where c.relnamespace = 'rma'::regnamespace and not t.tgisinternal
  union all select 'esquema.restricciones', md5(string_agg(c.relname || k.conname || pg_get_constraintdef(k.oid), '|' order by c.relname, k.conname))
    from pg_constraint k join pg_class c on c.oid = k.conrelid where c.relnamespace = 'rma'::regnamespace
  union all select 'esquema.indices', md5(string_agg(indexdef, '|' order by indexname)) from pg_indexes where schemaname = 'rma'
  union all select 'esquema.vistas', md5(string_agg(viewname || definition, '|' order by viewname)) from pg_views where schemaname = 'rma'
  union all select 'esquema.columnas', md5(string_agg(table_name || column_name || data_type || is_nullable || coalesce(column_default, ''), '|' order by table_name, ordinal_position))
    from information_schema.columns where table_schema = 'rma'
  union all select 'esquema.secuencias', string_agg(sequencename, ',' order by sequencename) from pg_sequences where schemaname = 'rma'
  union all select 'permisos.tablas', md5(string_agg(x.grantee::regrole::text || c.relname || x.privilege_type, '|' order by x.grantee::regrole::text || c.relname || x.privilege_type))
    from pg_class c cross join lateral aclexplode(c.relacl) x
   where c.relnamespace = 'rma'::regnamespace and x.grantee <> 0 and x.grantee::regrole::text in ('rma_backend', 'anon', 'authenticated', 'service_role')
  union all select 'permisos.columnas', md5(string_agg(x.grantee::regrole::text || c.relname || a.attname || x.privilege_type, '|' order by x.grantee::regrole::text || c.relname || a.attname || x.privilege_type))
    from pg_attribute a join pg_class c on c.oid = a.attrelid cross join lateral aclexplode(a.attacl) x
   where c.relnamespace = 'rma'::regnamespace and a.attacl is not null and x.grantee <> 0 and x.grantee::regrole::text = 'rma_backend'
  union all select 'permisos.funciones_publicas', md5(string_agg(p.oid::regprocedure::text || coalesce(p.proacl::text, 'default'), '|' order by p.oid::regprocedure::text || coalesce(p.proacl::text, 'default')))
    from pg_proc p where p.pronamespace = 'rma'::regnamespace
  union all select 'permisos.api_sin_acceso_a_rma', string_agg(r || '=' || has_schema_privilege(r, 'rma', 'usage'), ',' order by r)
    from unnest(array['anon', 'authenticated', 'service_role']) r
  union all select 'migraciones', string_agg(version, ',' order by version) from supabase_migrations.schema_migrations
  union all select 'referencia.rol', md5(string_agg((to_jsonb(t) - 'id')::text, '|' order by t.codigo)) from rma.rol t
  union all select 'referencia.tipo_documento', md5(string_agg((to_jsonb(t) - 'id' - 'creado_en' - 'modificado_en')::text, '|' order by t.codigo)) from rma.tipo_documento t
  union all select 'referencia.tipo_evento', md5(string_agg((to_jsonb(t) - 'id')::text, '|' order by t.codigo)) from rma.tipo_evento t
  union all select 'referencia.equivalencia_historial', md5(string_agg(e.tipo_referencia || coalesce(e.referencia_id, '') || coalesce(e.accion, '') || te.codigo, '|' order by e.tipo_referencia || coalesce(e.referencia_id, '') || coalesce(e.accion, '') || te.codigo))
    from rma.equivalencia_historial e join rma.tipo_evento te on te.id = e.tipo_evento_id
  union all select 'maestra.medio_pago', md5(string_agg((to_jsonb(t) - 'id' - 'creado_en' - 'modificado_en')::text, '|' order by t.codigo)) from rma.medio_pago t
  union all select 'maestra.usuario_rol', md5(string_agg(ur.usuario_id || r.codigo || coalesce(ur.otorgado_por::text, ''), '|' order by ur.usuario_id || r.codigo || coalesce(ur.otorgado_por::text, '')))
    from rma.usuario_rol ur join rma.rol r on r.id = ur.rol_id
  {por_id}
  union all select 'stock', string_agg(i.codigo || '=' || i.stock_fisico || '/' || i.stock_reservado, ',' order by i.codigo) from rma.insumo i
  union all select 'stock.ingresos_iniciales', string_agg(m.codigo || ':' || i.codigo || ':' || m.cantidad, ',' order by m.codigo)
    from rma.movimiento_inventario m join rma.insumo i on i.id = m.insumo_id where m.orden_id is null and m.tipo = 'INGRESO'
  union all select 'datos.ordenes', count(*)::text from rma.orden
  union all select 'datos.proxima_orden', (case when is_called then last_value + 1 else last_value end)::text from rma.orden_numero_seq
)
select coalesce(jsonb_object_agg(k, coalesce(v, '-')), '{}') as huella from f
"""


def _huella_por_id() -> str:
    partes = []
    for tabla, clave in POR_ID:
        orden = ", ".join(f"t.{c}::text" for c in clave)
        quitar = " - 'modificado_en'" + (
            " - 'stock_fisico' - 'stock_reservado'"
            if tabla == "insumo"
            else ""
        )
        partes.append(
            f"union all select 'maestra.{tabla}', md5(string_agg((to_jsonb(t){quitar})::text, '|' order by {orden})) from rma.{tabla} t"
        )
    return "\n  ".join(partes)


def huella(destino: str) -> dict:
    return uno(destino, HUELLA.replace("{por_id}", _huella_por_id()))


def comparar(origen: str, destino: str, solo: tuple[str, ...] = ()) -> bool:
    a, b = huella(origen), huella(destino)
    todo_igual = True
    for clave in sorted(a.keys() | b.keys()):
        if solo and not clave.startswith(solo):
            continue
        igual = a.get(clave) == b.get(clave)
        todo_igual &= igual
        detalle = (
            ""
            if igual
            or clave.startswith(
                (
                    "esquema.funciones",
                    "esquema.triggers",
                    "esquema.restricciones",
                    "esquema.indices",
                    "esquema.vistas",
                    "esquema.columnas",
                    "permisos.tablas",
                    "permisos.columnas",
                    "referencia.",
                    "maestra.",
                )
            )
            else f"  origen={a.get(clave)} destino={b.get(clave)}"
        )
        print(f"  {'OK   ' if igual else 'DIFIERE'} {clave}{detalle}")
    return todo_igual


# --------------------------------------------------------------------------
# Datos maestros
# --------------------------------------------------------------------------

EXPORTAR_MAESTROS = """
select jsonb_build_object(
  {por_id},
  'medio_pago', (select coalesce(jsonb_agg(to_jsonb(t) - 'id' order by t.codigo), '[]') from rma.medio_pago t),
  'usuario_rol', (select coalesce(jsonb_agg(jsonb_build_object('usuario_id', ur.usuario_id, 'rol_codigo', r.codigo,
                    'otorgado_en', ur.otorgado_en, 'otorgado_por', ur.otorgado_por) order by ur.usuario_id, r.codigo), '[]')
                  from rma.usuario_rol ur join rma.rol r on r.id = ur.rol_id),
  'ingresos_iniciales', (select coalesce(jsonb_agg(jsonb_build_object('codigo', m.codigo, 'insumo_id', m.insumo_id,
                    'cantidad', m.cantidad, 'motivo_texto', m.motivo_texto) order by m.codigo), '[]')
                  from rma.movimiento_inventario m where m.orden_id is null and m.tipo = 'INGRESO'),
  'movimientos', (select count(*) from rma.movimiento_inventario),
  'ordenes', (select count(*) from rma.orden)
) as datos
"""


def exportar_maestros(origen: str) -> dict:
    por_id = ",\n  ".join(
        f"'{t}', (select coalesce(jsonb_agg(to_jsonb(x) order by {', '.join('x.' + c + '::text' for c in clave)}), '[]') from rma.{t} x)"
        for t, clave in POR_ID
    )
    datos = uno(origen, EXPORTAR_MAESTROS.replace("{por_id}", por_id))
    if datos["ordenes"] != 0:
        raise Falla(
            f"El origen tiene {datos['ordenes']} Órdenes: se esperaba el UAT reiniciado."
        )
    if datos["movimientos"] != len(datos["ingresos_iniciales"]):
        raise Falla(
            "El origen tiene movimientos de inventario además de los ingresos iniciales."
        )
    return datos


def sql_maestros(datos: dict) -> str:
    """Un único bloque DO, idempotente, para el destino."""
    carga = json.dumps(datos, ensure_ascii=False, sort_keys=True)
    if "$carga$" in carga:
        raise Falla("Los datos contienen el delimitador reservado.")
    sentencias = []
    for tabla, clave in POR_ID:
        sentencias.append(
            f"insert into rma.{tabla} select * from jsonb_populate_recordset(null::rma.{tabla}, d->'{tabla}')"
            f" on conflict ({', '.join(clave)}) do nothing;"
        )
    return f"""
do $migracion$
declare
  d constant jsonb := $carga${carga}$carga$::jsonb;
  v_accion uuid;
  r jsonb;
begin
  if exists (select 1 from rma.orden) then
    raise exception 'El destino tiene Órdenes: no se cargan datos maestros.';
  end if;
  if exists (select 1 from rma.movimiento_inventario m
              where not (d->'ingresos_iniciales') @> jsonb_build_array(jsonb_build_object('codigo', m.codigo))) then
    raise exception 'El destino tiene movimientos de inventario que no son los ingresos iniciales del origen.';
  end if;

  {chr(10).join("  " + s for s in sentencias).strip()}

  -- Medios de pago: por código (la migración E4 crea los predeterminados con otro id).
  insert into rma.medio_pago (codigo, nombre, activo, admite_devolucion, creado_en, modificado_en, orden)
  select codigo, nombre, activo, admite_devolucion, creado_en, modificado_en, orden
    from jsonb_populate_recordset(null::rma.medio_pago, d->'medio_pago')
  on conflict (codigo) do update
     set nombre = excluded.nombre, activo = excluded.activo,
         admite_devolucion = excluded.admite_devolucion, orden = excluded.orden
   where (rma.medio_pago.nombre, rma.medio_pago.activo, rma.medio_pago.admite_devolucion, rma.medio_pago.orden)
         is distinct from (excluded.nombre, excluded.activo, excluded.admite_devolucion, excluded.orden);

  -- Roles de usuario: por el código del rol (sus UUID cambian entre proyectos).
  insert into rma.usuario_rol (usuario_id, rol_id, otorgado_en, otorgado_por)
  select (x->>'usuario_id')::uuid, ro.id, (x->>'otorgado_en')::timestamptz, (x->>'otorgado_por')::uuid
    from jsonb_array_elements(d->'usuario_rol') x
    join rma.rol ro on ro.codigo = x->>'rol_codigo'
  on conflict (usuario_id, rol_id) do nothing;
  if (select count(*) from jsonb_array_elements(d->'usuario_rol') x
       where not exists (select 1 from rma.rol ro where ro.codigo = x->>'rol_codigo')) > 0 then
    raise exception 'Hay roles del origen que no existen en el destino.';
  end if;

  -- Stock inicial: el trigger del libro recalcula los saldos (el insumo nace en cero).
  for r in select * from jsonb_array_elements(d->'ingresos_iniciales') loop
    if not exists (select 1 from rma.movimiento_inventario where codigo = r->>'codigo') then
      if v_accion is null then
        insert into rma.accion_usuario (proceso, operacion, resultado)
        values ('CARGA_INICIAL_UAT', 'INGRESO_STOCK_INICIAL', 'CONFIRMADA')
        returning id into v_accion;
      end if;
      insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, motivo_texto, accion_id)
      values (r->>'codigo', 'INGRESO', (r->>'insumo_id')::uuid, (r->>'cantidad')::numeric, r->>'motivo_texto', v_accion);
    end if;
  end loop;

  if exists (select 1 from rma.verificar_integridad()) then
    raise exception 'verificar_integridad() informa problemas después de la carga.';
  end if;
end $migracion$
"""


def cargar_maestros(origen: str, destino: str, aplicar: bool) -> bool:
    datos = exportar_maestros(origen)
    print("Origen (filas a asegurar en el destino):")
    for tabla, _ in POR_ID:
        print(f"  {tabla}: {len(datos[tabla])}")
    print(
        f"  medio_pago: {len(datos['medio_pago'])}  usuario_rol: {len(datos['usuario_rol'])}"
        f"  ingresos iniciales: {len(datos['ingresos_iniciales'])}"
    )
    if not aplicar:
        print("Sin --aplicar: no se escribe nada. Diferencias actuales:")
        return comparar(origen, destino, ("maestra.", "stock", "referencia."))
    consultar(destino, sql_maestros(datos), escribir=True)
    print("Carga aplicada. Comparación:")
    return comparar(origen, destino, ("maestra.", "stock", "referencia."))


# --------------------------------------------------------------------------
# Cuentas de Supabase Auth
# --------------------------------------------------------------------------

CUENTAS_SQL = """
select coalesce(jsonb_agg(jsonb_build_object(
         'codigo', u.codigo, 'id', a.id, 'email', a.email, 'hash', a.encrypted_password,
         'confirmada', a.email_confirmed_at is not null,
         'bloqueada', a.banned_until is not null and a.banned_until > now(),
         'identidad_email', exists (select 1 from auth.identities i where i.user_id = a.id
                                     and i.provider = 'email' and i.provider_id = a.id::text))
       order by u.codigo), '[]') as cuentas
  from rma.usuario u join auth.users a on a.id = u.auth_user_id
 where u.activo
"""


def leer_cuentas(destino: str) -> dict[str, dict]:
    """Cuentas vinculadas, con su hash en memoria. Nunca se imprimen."""
    return {c["id"]: c for c in uno(destino, CUENTAS_SQL)}


class AdminAuth:
    def __init__(self, url: str, clave: str):
        if not (
            url.startswith("https://") or url.startswith("http://127.0.0.1")
        ):
            raise Falla(
                "La URL de Auth del destino debe ser https (o la local 127.0.0.1)."
            )
        self.base = url.rstrip("/") + "/auth/v1"
        self.clave = clave

    def pedir(self, metodo: str, ruta: str, cuerpo: dict | None = None):
        pedido = urllib.request.Request(
            self.base + ruta,
            data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
            method=metodo,
            headers={
                "apikey": self.clave,
                "Content-Type": "application/json",
                # La clave publicable no es un JWT: va solo en apikey.
                **(
                    {}
                    if self.clave.startswith("sb_publishable_")
                    else {"Authorization": f"Bearer {self.clave}"}
                ),
            },
        )
        try:
            with urllib.request.urlopen(pedido, timeout=30) as respuesta:
                return respuesta.status, json.loads(
                    respuesta.read().decode() or "{}"
                )
        except urllib.error.HTTPError as error:
            try:
                detalle = json.loads(error.read().decode() or "{}")
            except ValueError:
                detalle = {}
            # Solo el código y el mensaje de Auth: nunca el cuerpo enviado.
            return error.code, {
                "error": detalle.get("error_code") or detalle.get("code"),
                "mensaje": str(
                    detalle.get("msg") or detalle.get("message") or ""
                )[:200],
            }


def migrar_cuentas(
    origen: str, destino: str, auth_url: str, aplicar: bool
) -> bool:
    cuentas = leer_cuentas(origen)
    if not cuentas:
        raise Falla(
            "El origen no tiene cuentas vinculadas a usuarios activos."
        )
    for c in cuentas.values():
        if not BCRYPT.match(c["hash"] or ""):
            raise Falla(
                f"La cuenta de {c['codigo']} no tiene un hash bcrypt: usar la alternativa de contraseñas nuevas."
            )
        if not c["confirmada"] or c["bloqueada"] or not c["identidad_email"]:
            raise Falla(
                f"La cuenta de {c['codigo']} no está confirmada, está bloqueada o no tiene identidad email."
            )

    existentes = uno(
        destino,
        "select coalesce(jsonb_agg(jsonb_build_object('id', id, 'email', email, 'hash', encrypted_password)), '[]') from auth.users",
    )
    por_id = {e["id"]: e for e in existentes}
    por_email = {e["email"]: e for e in existentes}

    clave = os.environ.get("SUPABASE_SECRET_KEY_DESTINO") or (
        getpass.getpass("Clave secreta del Auth del destino (no se muestra): ")
        if aplicar
        else ""
    )
    admin = AdminAuth(auth_url, clave) if aplicar else None
    bien = True
    for c in sorted(cuentas.values(), key=lambda x: x["codigo"]):
        actual = por_id.get(c["id"])
        if actual:
            iguales = (
                actual["email"] == c["email"] and actual["hash"] == c["hash"]
            )
            print(
                f"  {c['codigo']}: ya existe; email y contraseña {'iguales' if iguales else 'DISTINTOS'}"
            )
            bien &= iguales
            continue
        if c["email"] in por_email:
            print(
                f"  {c['codigo']}: CONFLICTO, el email ya existe en el destino con otro id"
            )
            bien = False
            continue
        if not aplicar:
            print(
                f"  {c['codigo']}: se crearía con el mismo id y la misma contraseña"
            )
            continue
        estado, respuesta = admin.pedir(
            "POST",
            "/admin/users",
            {
                "id": c["id"],
                "email": c["email"],
                "password_hash": c["hash"],
                "email_confirm": True,
            },
        )
        creada = estado in (200, 201) and respuesta.get("id") == c["id"]
        print(
            f"  {c['codigo']}: {'creada' if creada else f'ERROR HTTP {estado} {respuesta}'}"
        )
        bien &= creada

    if aplicar:
        # Relectura del destino: mismo id, email, hash e identidad email.
        destino_cuentas = {
            e["id"]: e
            for e in uno(
                destino,
                """
          select coalesce(jsonb_agg(jsonb_build_object('id', a.id, 'email', a.email, 'hash', a.encrypted_password,
                   'identidad', exists (select 1 from auth.identities i where i.user_id = a.id and i.provider = 'email'))), '[]')
            from auth.users a""",
            )
        }
        for c in cuentas.values():
            d = destino_cuentas.get(c["id"])
            ok = (
                bool(d)
                and d["email"] == c["email"]
                and d["hash"] == c["hash"]
                and d["identidad"]
            )
            print(f"  verificación {c['codigo']}: {'OK' if ok else 'FALLA'}")
            bien &= ok
    cuentas.clear()
    return bien


# --------------------------------------------------------------------------
# Verificación del destino
# --------------------------------------------------------------------------

VERIFICAR_SQL = """
select jsonb_build_object(
  'migraciones', (select string_agg(version, ',' order by version) from supabase_migrations.schema_migrations),
  'operativas', (select jsonb_object_agg(t, (xpath('/row/n/text()', query_to_xml(format('select count(*) as n from rma.%I', t), false, true, '')))[1]::text::int)
                   from unnest(array[{operativas}]) t),
  'integridad', (select count(*) from rma.verificar_integridad()),
  'stock', (select jsonb_object_agg(codigo, jsonb_build_array(stock_fisico, stock_reservado, concilia)) from rma.v_conciliacion_inventario),
  'proxima_orden', (select case when is_called then last_value + 1 else last_value end from rma.orden_numero_seq),
  'usuarios', (select jsonb_agg(jsonb_build_object('codigo', u.codigo, 'activo', u.activo,
                 'roles', (select string_agg(r.codigo, ',') from rma.usuario_rol ur join rma.rol r on r.id = ur.rol_id where ur.usuario_id = u.id),
                 'cuenta', a.id is not null, 'email_igual', a.email = u.email) order by u.codigo)
               from rma.usuario u left join auth.users a on a.id = u.auth_user_id),
  'api_usa_rma', (select bool_or(has_schema_privilege(r, 'rma', 'usage')) from unnest(array['anon', 'authenticated', 'service_role']) r),
  'rma_api', (select jsonb_build_object('existe', true, 'miembro', pg_has_role(r.oid, 'rma_backend', 'member'),
                 'superusuario', r.rolsuper, 'bypassrls', r.rolbypassrls) from pg_roles r where r.rolname = 'rma_api'),
  'respaldo_presente', exists (select 1 from pg_namespace where nspname = 'rma_respaldo_reinicio')
) as v
"""


def verificar(
    destino: str,
    usuarios_esperados: dict[str, str],
    stock: dict[str, float],
    exigir_rma_api: bool,
) -> bool:
    repo = sorted(
        p.name.split("_", 1)[0]
        for p in (RAIZ / "supabase" / "migrations").glob("*.sql")
    )
    v = uno(
        destino,
        VERIFICAR_SQL.replace(
            "{operativas}", ", ".join(f"'{t}'" for t in OPERATIVAS)
        ),
        escribir=destino != "local",
    )
    esperado_op = {t: 0 for t in OPERATIVAS} | {
        "accion_usuario": 1 if stock else 0,
        "movimiento_inventario": len(stock),
    }
    usuarios = {u["codigo"]: u for u in v["usuarios"] or []}
    chequeos = [
        (
            "20 migraciones, iguales al repositorio",
            (v["migraciones"] or "").split(",") == repo,
        ),
        (
            "cero datos operativos (salvo el stock inicial)",
            v["operativas"] == esperado_op,
        ),
        ("verificar_integridad() vacío", v["integridad"] == 0),
        (
            "stock inicial conciliado",
            all(
                (v["stock"] or {}).get(k) == [float(q), 0.0, True]
                or (v["stock"] or {}).get(k) == [q, 0, True]
                for k, q in stock.items()
            ),
        ),
        ("próxima Orden OR-000001", v["proxima_orden"] == 1),
        (
            "usuarios activos, con su rol, vinculados",
            set(usuarios) == set(usuarios_esperados)
            and all(
                u["activo"]
                and u["roles"] == usuarios_esperados[c]
                and u["cuenta"]
                and u["email_igual"]
                for c, u in usuarios.items()
            ),
        ),
        (
            "anon/authenticated/service_role sin acceso a rma",
            v["api_usa_rma"] is False,
        ),
        ("sin esquema rma_respaldo_reinicio", v["respaldo_presente"] is False),
    ]
    if exigir_rma_api:
        r = v["rma_api"] or {}
        chequeos.append(
            (
                "rma_api miembro de rma_backend, sin superusuario ni BYPASSRLS",
                r.get("miembro") is True
                and not r.get("superusuario")
                and not r.get("bypassrls"),
            )
        )
    for nombre, ok in chequeos:
        print(f"  {'OK   ' if ok else 'FALLA'} {nombre}")
    return all(ok for _, ok in chequeos)


USUARIOS_UAT = {
    "ADMIN-001": "ADMINISTRADOR",
    "COORD-001": "COORDINADOR_RMA",
    "RECEP-001": "RECEPCION",
    "TECH-001": "TECNICO",
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="comando", required=True)
    for nombre in ("comparar", "maestros", "cuentas"):
        s = sub.add_parser(nombre)
        s.add_argument("--origen", required=True)
        s.add_argument("--destino", required=True)
        if nombre != "comparar":
            s.add_argument("--aplicar", action="store_true")
        if nombre == "cuentas":
            s.add_argument(
                "--auth-url",
                required=True,
                help="https://<ref>.supabase.co del destino",
            )
    s = sub.add_parser("verificar")
    s.add_argument("--destino", required=True)
    s.add_argument(
        "--stock",
        default="BAT-IP14=10",
        help="código=cantidad, separados por coma",
    )
    s.add_argument(
        "--usuarios",
        default=",".join(f"{k}={v}" for k, v in USUARIOS_UAT.items()),
    )
    s.add_argument(
        "--sin-rma-api",
        action="store_true",
        help="no exige el rol rma_api (base local)",
    )
    a = p.parse_args(argv)
    try:
        if a.comando == "comparar":
            ok = comparar(a.origen, a.destino)
        elif a.comando == "maestros":
            ok = cargar_maestros(a.origen, a.destino, a.aplicar)
        elif a.comando == "cuentas":
            ok = migrar_cuentas(a.origen, a.destino, a.auth_url, a.aplicar)
        else:
            stock = {
                k: float(q)
                for k, q in (x.split("=") for x in a.stock.split(",") if x)
            }
            usuarios = dict(x.split("=") for x in a.usuarios.split(",") if x)
            ok = verificar(a.destino, usuarios, stock, not a.sin_rma_api)
    except Falla as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print("RESULTADO:", "OK" if ok else "CON DIFERENCIAS O FALLAS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
