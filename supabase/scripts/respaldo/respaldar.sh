#!/bin/sh
# Respaldo lógico y cifrado de la base del UAT (Supabase PostgreSQL).
#
# Pensado para correr en un contenedor postgres:17-alpine (Cloud Run Job o
# Docker local). Produce, en $RMA_RESPALDO_DESTINO/<etiqueta>/<marca UTC>/:
#
#   rma.dump.age     datos del esquema rma (sin esquema: el esquema sale de
#                    las migraciones del repositorio), con los valores de las
#                    secuencias. Formato custom de pg_dump, cifrado con age.
#   auth.dump.age    auth.users y auth.identities (esquema y datos): contiene
#                    los hashes de las contraseñas, siempre cifrado.
#   manifiesto.json  versiones, migraciones aplicadas y conteos por tabla.
#                    Sin datos de negocio ni personales.
#   SHA256SUMS       sumas de los tres archivos.
#
# Variables (sin valores por defecto para lo sensible):
#   RMA_RESPALDO_DB_URL         cadena de conexión con permiso de lectura
#                               sobre rma, auth.users y auth.identities (rol
#                               rma_respaldo o administrador). Nunca se imprime.
#   RMA_RESPALDO_DESTINATARIO   clave PÚBLICA de age (age1...). La privada
#                               queda fuera de la nube, con quien restaura.
#   RMA_RESPALDO_DESTINO        carpeta de salida (en Cloud Run, el bucket
#                               montado como volumen).
#   RMA_RESPALDO_ETIQUETA       opcional; por defecto "uat".
#
# Nada sin cifrar llega al destino: los volcados se escriben en un temporal
# local con umask 077 y se borran al terminar, falle o no.

set -eu
umask 077

: "${RMA_RESPALDO_DB_URL:?Falta RMA_RESPALDO_DB_URL}"
: "${RMA_RESPALDO_DESTINATARIO:?Falta RMA_RESPALDO_DESTINATARIO (clave pública de age)}"
: "${RMA_RESPALDO_DESTINO:?Falta RMA_RESPALDO_DESTINO}"
ETIQUETA="${RMA_RESPALDO_ETIQUETA:-uat}"

case "$RMA_RESPALDO_DESTINATARIO" in
  age1*) ;;
  *) echo "RMA_RESPALDO_DESTINATARIO no es una clave pública de age." >&2; exit 2 ;;
esac

if ! command -v age >/dev/null 2>&1; then
  apk add --no-cache age >/dev/null
fi

MARCA=$(date -u +%Y%m%dT%H%M%SZ)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM
URL="$RMA_RESPALDO_DB_URL"

# Los errores de pg_dump y psql no incluyen la contraseña; igual se filtra
# cualquier cadena de conexión antes de mostrarlos.
fallar() {
  echo "RESPALDO_FALLIDO: $1" >&2
  sed -E 's#postgres(ql)?://[^ ]+#<oculto>#g' "$TMP/error.log" >&2 2>/dev/null || true
  exit 1
}

pg_dump "$URL" --format=custom --data-only --schema=rma \
  --file="$TMP/rma.dump" 2>"$TMP/error.log" || fallar "volcado de rma"
pg_dump "$URL" --format=custom --no-owner --no-privileges \
  --table=auth.users --table=auth.identities \
  --file="$TMP/auth.dump" 2>"$TMP/error.log" || fallar "volcado de auth"

psql "$URL" -X -q -A -t -v ON_ERROR_STOP=1 >"$TMP/manifiesto.json" 2>"$TMP/error.log" <<'SQL' || fallar "manifiesto"
select json_build_object(
  'formato', 'rma-respaldo-1',
  'creado_en', now(),
  'servidor', current_setting('server_version'),
  'migraciones', (select json_agg(version order by version) from supabase_migrations.schema_migrations),
  'tablas', (select json_object_agg(t, n) from (
      select c.relname as t,
             (xpath('/row/n/text()', query_to_xml(format('select count(*) as n from rma.%I', c.relname), false, true, '')))[1]::text::bigint as n
        from pg_class c join pg_namespace s on s.oid = c.relnamespace
       where s.nspname = 'rma' and c.relkind = 'r' order by c.relname) x),
  'secuencias', (select json_object_agg(sequencename, last_value) from pg_sequences where schemaname = 'rma'),
  'cuentas_auth', (select count(*) from auth.users),
  'identidades_auth', (select count(*) from auth.identities)
);
SQL
sed -i "s/^/{\"herramienta\":\"$(pg_dump --version | sed 's/"//g')\",\"respaldo\":/; s/\$/}/" "$TMP/manifiesto.json"

DIR="$RMA_RESPALDO_DESTINO/$ETIQUETA/$MARCA"
mkdir -p "$DIR"
age -r "$RMA_RESPALDO_DESTINATARIO" -o "$DIR/rma.dump.age" "$TMP/rma.dump"
age -r "$RMA_RESPALDO_DESTINATARIO" -o "$DIR/auth.dump.age" "$TMP/auth.dump"
cp "$TMP/manifiesto.json" "$DIR/manifiesto.json"
(cd "$DIR" && sha256sum rma.dump.age auth.dump.age manifiesto.json > SHA256SUMS)

echo "RESPALDO_OK $ETIQUETA/$MARCA rma=$(wc -c < "$DIR/rma.dump.age")B auth=$(wc -c < "$DIR/auth.dump.age")B"
