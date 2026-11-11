#!/usr/bin/env bash
# Prueba de punta a punta del respaldo y la restauración, solo en local.
#
# Requiere Docker y la pila local (`npx -y supabase@3.1.0 start`) con datos
# ficticios. No toca ningún proyecto remoto. Usa una clave de age descartable,
# generada para la prueba y borrada al terminar.
#
#   bash supabase/scripts/respaldo/probar_respaldo_local.sh
#
# 1. Respalda la base local con respaldar.sh (en postgres:17-alpine).
# 2. Crea la base restauracion_prueba con las migraciones del repositorio.
# 3. Restaura rma en modo ensayo (nada cambia) y en modo aplicar.
# 4. Compara el contenido de cada tabla de rma y las secuencias con el origen.
# 5. Restaura auth en la base de trabajo auth_prueba y compara id, email y
#    hash (solo la huella md5 del conjunto, nunca los hashes).
# 6. Borra las bases y los archivos de la prueba.

set -euo pipefail
export MSYS_NO_PATHCONV=1

RAIZ=$(cd "$(dirname "$0")/../../.." && pwd)
RED=supabase_network_rt-rma-mvp
HOST_DB=supabase_db_rt-rma-mvp
IMAGEN=postgres:17-alpine
ORIGEN="postgresql://postgres:postgres@$HOST_DB:5432/postgres?sslmode=disable"
DESTINO="postgresql://postgres:postgres@$HOST_DB:5432/restauracion_prueba?sslmode=disable"
TRABAJO="postgresql://postgres:postgres@$HOST_DB:5432/auth_prueba?sslmode=disable"
TMP=$(mktemp -d)
CLI=(npx -y supabase@3.1.0)

# Docker Desktop en Windows necesita rutas C:/...; en Linux y macOS sirve la ruta tal cual.
ruta_docker() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else echo "$1"; fi; }
MONTA_TMP=$(ruta_docker "$TMP")
MONTA_HERR=$(ruta_docker "$RAIZ/supabase/scripts/respaldo")

contenedor() {
  docker run --rm --network "$RED" -v "$MONTA_TMP:/trabajo" -v "$MONTA_HERR:/herramientas:ro" "$@"
}
sql_local() { docker exec -i "$HOST_DB" psql -U postgres -X -q -A -t -v ON_ERROR_STOP=1 "$@"; }
limpiar() {
  sql_local -c "drop database if exists restauracion_prueba" >/dev/null 2>&1 || true
  sql_local -c "drop database if exists auth_prueba" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap limpiar EXIT
exigir() { if [ "$1" = "$2" ]; then echo "  OK    $3"; else echo "  FALLA $3 (obtenido: $1, esperado: $2)"; exit 1; fi; }

echo "== Clave descartable de age"
contenedor "$IMAGEN" sh -c 'apk add --no-cache age >/dev/null && age-keygen -o /trabajo/clave.txt 2>/dev/null && grep -o "age1[a-z0-9]*" /trabajo/clave.txt > /trabajo/publica.txt'
PUBLICA=$(cat "$TMP/publica.txt")

echo "== 1. Respaldo de la base local"
contenedor -e RMA_RESPALDO_DB_URL="$ORIGEN" -e RMA_RESPALDO_DESTINATARIO="$PUBLICA" \
  -e RMA_RESPALDO_DESTINO=/trabajo/salida -e RMA_RESPALDO_ETIQUETA=prueba \
  "$IMAGEN" sh /herramientas/respaldar.sh
DIR=$(ls -d "$TMP"/salida/prueba/* | head -1)
MARCA=$(basename "$DIR")
exigir "$(ls "$DIR" | tr '\n' ' ')" "SHA256SUMS auth.dump.age manifiesto.json rma.dump.age " "archivos del respaldo"
exigir "$(grep -c 'PGDMP' "$DIR/rma.dump.age" || true)" "0" "el volcado de rma está cifrado (sin cabecera PGDMP legible)"

echo "== 2. Base destino con las migraciones"
sql_local -c "drop database if exists restauracion_prueba" -c "create database restauracion_prueba" >/dev/null
(cd "$RAIZ" && "${CLI[@]}" db push --remote="postgresql://postgres:postgres@127.0.0.1:54322/restauracion_prueba?sslmode=disable" --yes >/dev/null)

echo "== 3. Restauración de rma"
corre_restaurar() {
  contenedor -e RMA_RESTAURAR_DB_URL="$1" -e RMA_RESPALDO_DIR="/trabajo/salida/prueba/$MARCA" \
    -e RMA_RESPALDO_IDENTIDAD=/trabajo/clave.txt -e RMA_RESTAURAR_PARTE="$2" -e RMA_RESTAURAR_MODO="$3" \
    "$IMAGEN" sh /herramientas/restaurar.sh
}
ANTES=$(sql_local -d restauracion_prueba -c "select count(*) from rma.usuario")
corre_restaurar "$DESTINO" rma ensayo | sed 's/^/  /'
exigir "$(sql_local -d restauracion_prueba -c "select count(*) from rma.usuario")" "$ANTES" "el ensayo no cambió el destino"
corre_restaurar "$DESTINO" rma aplicar | sed 's/^/  /'

echo "== 4. Comparación con el origen"
HUELLA="select string_agg(c.relname || '=' || (xpath('/row/h/text()', query_to_xml(format('select count(*) || '':'' || coalesce(md5(string_agg(t::text, ''|'' order by t::text)), ''-'') as h from rma.%I t', c.relname), false, true, '')))[1]::text, ',' order by c.relname) from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'rma' and c.relkind = 'r'"
SECUENCIAS="select string_agg(sequencename || '=' || coalesce(last_value, 0), ',' order by sequencename) from pg_sequences where schemaname = 'rma'"
exigir "$(sql_local -d restauracion_prueba -c "$HUELLA" | md5sum | cut -c1-12)" "$(sql_local -d postgres -c "$HUELLA" | md5sum | cut -c1-12)" "contenido de las tablas de rma idéntico al origen"
exigir "$(sql_local -d restauracion_prueba -c "$SECUENCIAS")" "$(sql_local -d postgres -c "$SECUENCIAS")" "secuencias iguales al origen"
exigir "$(sql_local -d restauracion_prueba -c "select count(*) from rma.verificar_integridad()")" "0" "verificar_integridad() vacío en el destino"

echo "== 5. Cuentas de Auth en una base de trabajo"
sql_local -c "drop database if exists auth_prueba" -c "create database auth_prueba" >/dev/null
# La base principal de la pila tiene el esquema auth de Supabase: se rechaza
# antes de leer nada. En modo ensayo, para que no cambie nada aunque fallara.
RECHAZO=$(corre_restaurar "$ORIGEN" auth ensayo 2>&1 || true)
if echo "$RECHAZO" | grep -q "base de trabajo"; then
  echo "  OK    la parte auth se rechaza en una base con auth.users"
else
  echo "  FALLA el rechazo de auth sobre una base con auth.users"; exit 1
fi
corre_restaurar "$TRABAJO" auth aplicar | sed 's/^/  /'
CUENTAS="select count(*) || ':' || md5(string_agg(id::text || email || coalesce(encrypted_password, ''), '|' order by id)) from auth.users"
exigir "$(sql_local -d auth_prueba -c "$CUENTAS" | md5sum | cut -c1-12)" "$(sql_local -d postgres -c "$CUENTAS" | md5sum | cut -c1-12)" "cuentas restauradas con el mismo id, email y hash"
exigir "$(sql_local -d auth_prueba -c "select count(*) from auth.identities")" "$(sql_local -d postgres -c "select count(*) from auth.identities")" "identidades restauradas"

echo
echo "PRUEBA DE RESPALDO Y RESTAURACIÓN: OK"
