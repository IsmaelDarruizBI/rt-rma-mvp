#!/bin/sh
# Restauración de un respaldo de respaldar.sh. Mismo contenedor
# (postgres:17-alpine) o cualquier equipo con psql, pg_restore y age.
#
# Variables:
#   RMA_RESTAURAR_DB_URL     base destino. Para la parte rma: con las
#                            migraciones del repositorio ya aplicadas, las
#                            mismas que lista el manifiesto. Nunca se imprime.
#   RMA_RESPALDO_DIR         carpeta del respaldo (rma.dump.age, auth.dump.age,
#                            manifiesto.json, SHA256SUMS).
#   RMA_RESPALDO_IDENTIDAD   archivo con la clave PRIVADA de age.
#   RMA_RESTAURAR_PARTE      rma (por defecto) o auth.
#   RMA_RESTAURAR_MODO       ensayo (por defecto) o aplicar.
#
# Parte rma: en UNA transacción, con session_replication_role = replica
# (los triggers de inmutabilidad, de saldos y de secuencia de eventos no se
# disparan: las filas vuelven tal cual), vacía las tablas de rma, carga los
# datos y las secuencias, y verifica conteos contra el manifiesto y
# verificar_integridad(). En modo ensayo termina con un error que revierte
# todo. Reemplaza TODO el contenido de rma del destino.
#
# Parte auth: carga auth.users y auth.identities en una base de TRABAJO (sin
# esquema auth propio de Supabase). Nunca sobre un proyecto: las cuentas de
# un proyecto se recrean desde esa base con
#   migrar_uat.py cuentas --origen <url de la base de trabajo> --destino <ref> --aplicar
# (mismo id y mismo hash, por la API de administración).

set -eu
umask 077

: "${RMA_RESTAURAR_DB_URL:?Falta RMA_RESTAURAR_DB_URL}"
: "${RMA_RESPALDO_DIR:?Falta RMA_RESPALDO_DIR}"
: "${RMA_RESPALDO_IDENTIDAD:?Falta RMA_RESPALDO_IDENTIDAD (clave privada de age)}"
PARTE="${RMA_RESTAURAR_PARTE:-rma}"
MODO="${RMA_RESTAURAR_MODO:-ensayo}"
case "$PARTE" in rma|auth) ;; *) echo "RMA_RESTAURAR_PARTE: rma o auth." >&2; exit 2 ;; esac
case "$MODO" in ensayo|aplicar) ;; *) echo "RMA_RESTAURAR_MODO: ensayo o aplicar." >&2; exit 2 ;; esac

if ! command -v age >/dev/null 2>&1; then
  apk add --no-cache age >/dev/null
fi

(cd "$RMA_RESPALDO_DIR" && sha256sum -c -s SHA256SUMS) || { echo "SHA256SUMS no coincide: respaldo alterado o incompleto." >&2; exit 1; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM
URL="$RMA_RESTAURAR_DB_URL"
MANIFIESTO=$(cat "$RMA_RESPALDO_DIR/manifiesto.json")
age -d -i "$RMA_RESPALDO_IDENTIDAD" -o "$TMP/$PARTE.dump" "$RMA_RESPALDO_DIR/$PARTE.dump.age"

if [ "$PARTE" = "auth" ]; then
  if [ "$(psql "$URL" -X -A -t -c "select to_regclass('auth.users') is not null")" = "t" ]; then
    echo "El destino ya tiene auth.users: la parte auth solo se carga en una base de trabajo." >&2
    exit 1
  fi
  if [ "$MODO" = "ensayo" ]; then
    pg_restore --list "$TMP/auth.dump" | grep -cE "TABLE DATA auth (users|identities)" | sed 's/^/ENSAYO OK: tablas de datos en el respaldo: /'
    exit 0
  fi
  psql "$URL" -X -q -v ON_ERROR_STOP=1 -c "create schema if not exists auth"
  pg_restore --no-owner --no-privileges --exit-on-error --single-transaction -d "$URL" "$TMP/auth.dump"
  psql "$URL" -X -q -A -t -v ON_ERROR_STOP=1 -v manifiesto="$MANIFIESTO" <<'SQL'
select case when count(*) = ((:'manifiesto')::json -> 'respaldo' ->> 'cuentas_auth')::int
            then 'RESTAURACION_OK auth: ' || count(*) || ' cuentas'
            else 'RESTAURACION_INCOMPLETA auth: ' || count(*) || ' cuentas' end
  from auth.users;
SQL
  exit 0
fi

pg_restore --data-only --no-owner --file="$TMP/rma.sql" "$TMP/rma.dump"

cat > "$TMP/antes.sql" <<'SQL'
select set_config('rma.manifiesto', :'manifiesto', false), set_config('rma.modo', :'modo', false);
do $$
declare
  v_destino json;
  v_respaldo json := (current_setting('rma.manifiesto')::json -> 'respaldo' -> 'migraciones');
begin
  select json_agg(version order by version) into v_destino from supabase_migrations.schema_migrations;
  if v_destino::text is distinct from v_respaldo::text then
    raise exception 'Las migraciones del destino no son las del respaldo.';
  end if;
end $$;
set session_replication_role = replica;
do $$
begin
  execute (select 'truncate table ' || string_agg(format('rma.%I', c.relname), ', ')
             from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'rma' and c.relkind = 'r');
end $$;
SQL

cat > "$TMP/despues.sql" <<'SQL'
set session_replication_role = origin;
do $$
declare
  v_tablas json := current_setting('rma.manifiesto')::json -> 'respaldo' -> 'tablas';
  v_tabla text;
  v_esperado bigint;
  v_n bigint;
  v_problemas bigint;
begin
  for v_tabla, v_esperado in select key, value::text::bigint from json_each(v_tablas) loop
    execute format('select count(*) from rma.%I', v_tabla) into v_n;
    if v_n <> v_esperado then
      raise exception 'La tabla % quedó con % filas; el respaldo tiene %.', v_tabla, v_n, v_esperado;
    end if;
  end loop;
  select count(*) into v_problemas from rma.verificar_integridad();
  if v_problemas <> 0 then
    raise exception 'verificar_integridad() informa % problemas.', v_problemas;
  end if;
  if current_setting('rma.modo') = 'ensayo' then
    raise exception 'ENSAYO OK: % tablas con los conteos del respaldo e integridad sin problemas (se revierte todo).',
      (select count(*) from json_object_keys(v_tablas));
  end if;
end $$;
select 'RESTAURACION_OK rma';
SQL

set +e
psql "$URL" -X -q -A -t -v ON_ERROR_STOP=1 --single-transaction \
  -v manifiesto="$MANIFIESTO" -v modo="$MODO" \
  -f "$TMP/antes.sql" -f "$TMP/rma.sql" -f "$TMP/despues.sql" >"$TMP/salida.log" 2>&1
CODIGO=$?
set -e
sed -E 's#postgres(ql)?://[^ ]+#<oculto>#g' "$TMP/salida.log" | grep -E "ENSAYO OK|RESTAURACION|ERROR" | head -5
# En ensayo el error final es el rollback buscado; cualquier otro error es una falla.
if [ "$MODO" = "ensayo" ] && grep -q "ENSAYO OK" "$TMP/salida.log"; then
  exit 0
fi
exit "$CODIGO"
