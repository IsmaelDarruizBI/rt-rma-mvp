#!/bin/sh
# Ensayo de restauración de punta a punta en el propio Job de respaldo, sin
# clave privada real y sin tocar ninguna base remota salvo para leer.
#
#   gcloud run jobs execute rt-rma-respaldo-db --region southamerica-east1 \
#     --args /respaldos/_herramientas/ensayar_restauracion.sh --wait
#
# 1. Respalda la base del UAT con respaldar.sh (la misma conexión de solo
#    lectura del Job), cifrado con una clave de age descartable que se genera
#    y se borra dentro del contenedor. Nada se escribe en el bucket.
# 2. Levanta un PostgreSQL temporal en el contenedor y le aplica las
#    migraciones de _herramientas/migraciones (las del repositorio).
# 3. restaurar.sh rma en ensayo y en aplicar: conteos de cada tabla contra el
#    manifiesto y verificar_integridad() sin problemas.
# 4. Compara las secuencias restauradas con el manifiesto.
# 5. restaurar.sh auth en una base de trabajo: las cuentas del manifiesto.
#
# Prueba la cadena completa (lectura, pg_dump, cifrado, SHA256SUMS,
# descifrado, pg_restore, triggers en modo replica e integridad). Que el
# respaldo real se descifra con la clave privada de la persona responsable se
# prueba aparte, en su máquina (docs/RESPALDOS.md, sección 3).

set -eu
umask 077

HERR=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d)
# initdb y pg_ctl no corren como root. La imagen trae gosu o su-exec según la
# versión; si no, el su de busybox. Los argumentos no llevan espacios.
como_postgres() {
  if command -v gosu >/dev/null 2>&1; then gosu postgres "$@"
  elif command -v su-exec >/dev/null 2>&1; then su-exec postgres "$@"
  else su postgres -s /bin/sh -c "$*"; fi
}
parar() {
  como_postgres pg_ctl -D "$T/pg" -m immediate stop >/dev/null 2>&1 || true
  rm -rf "$T"
}
trap parar EXIT INT TERM

command -v age >/dev/null 2>&1 || apk add --no-cache age >/dev/null
age-keygen -o "$T/clave.txt" 2>/dev/null
PUBLICA=$(grep -o 'age1[a-z0-9]*' "$T/clave.txt")

echo "== 1. Respaldo con una clave descartable"
RMA_RESPALDO_DESTINATARIO="$PUBLICA" RMA_RESPALDO_DESTINO="$T/salida" \
  RMA_RESPALDO_ETIQUETA=ensayo sh "$HERR/respaldar.sh"
DIR=$(ls -d "$T"/salida/ensayo/* | head -1)

echo "== 2. PostgreSQL temporal con las migraciones"
# postgres tiene que poder atravesar el temporal (711: sin listar). La clave
# descartable y los volcados siguen en 600, solo para root.
chmod 711 "$T"
mkdir -p "$T/pg" "$T/sock"
chown postgres "$T/pg" "$T/sock"
como_postgres initdb -D "$T/pg" -U postgres -A trust >/dev/null
echo "listen_addresses = ''" >> "$T/pg/postgresql.conf"
echo "unix_socket_directories = '$T/sock'" >> "$T/pg/postgresql.conf"
como_postgres pg_ctl -D "$T/pg" -l "$T/pg/arranque.log" -w start >/dev/null
BASE="postgresql://postgres@/postgres?host=$T/sock"
psql "$BASE" -X -q -v ON_ERROR_STOP=1 \
  -c "create role anon nologin" -c "create role authenticated nologin" \
  -c "create role service_role nologin" \
  -c "create database restauracion" -c "create database auth_trabajo"
DESTINO="postgresql://postgres@/restauracion?host=$T/sock"
TRABAJO="postgresql://postgres@/auth_trabajo?host=$T/sock"
VERSIONES=""
for f in "$HERR"/migraciones/*.sql; do
  psql "$DESTINO" -X -q -v ON_ERROR_STOP=1 -f "$f" >/dev/null
  VERSIONES="$VERSIONES('$(basename "$f" | cut -d_ -f1)'),"
done
psql "$DESTINO" -X -q -v ON_ERROR_STOP=1 \
  -c "create schema supabase_migrations" \
  -c "create table supabase_migrations.schema_migrations (version text primary key)" \
  -c "insert into supabase_migrations.schema_migrations values ${VERSIONES%,}"
echo "  migraciones aplicadas: $(psql "$DESTINO" -X -A -t -c 'select count(*) from supabase_migrations.schema_migrations')"

# Sin tubería: en sh, «restaurar.sh | sed» tomaría el código de salida de sed
# y una restauración fallida pasaría como buena.
restaurar() {
  if RMA_RESTAURAR_DB_URL="$1" RMA_RESPALDO_DIR="$DIR" RMA_RESPALDO_IDENTIDAD="$T/clave.txt" \
    RMA_RESTAURAR_PARTE="$2" RMA_RESTAURAR_MODO="$3" sh "$HERR/restaurar.sh" >"$T/restaurar.log" 2>&1; then
    sed 's/^/  /' "$T/restaurar.log"
  else
    sed 's/^/  /' "$T/restaurar.log" >&2
    echo "  FALLA: restaurar.sh $2 $3" >&2
    exit 1
  fi
}

echo "== 3. Restauración de rma"
restaurar "$DESTINO" rma ensayo
restaurar "$DESTINO" rma aplicar

echo "== 4. Secuencias"
IGUALES=$(psql "$DESTINO" -X -A -t -v ON_ERROR_STOP=1 -v m="$(cat "$DIR/manifiesto.json")" <<'SQL'
select ((:'m')::jsonb -> 'respaldo' -> 'secuencias')
       = (select jsonb_object_agg(sequencename, last_value) from pg_sequences where schemaname = 'rma');
SQL
)
[ "$IGUALES" = "t" ] || { echo "  FALLA: las secuencias no coinciden con el manifiesto." >&2; exit 1; }
echo "  OK: secuencias iguales al manifiesto"

echo "== 5. Cuentas de Auth en una base de trabajo"
restaurar "$TRABAJO" auth ensayo
restaurar "$TRABAJO" auth aplicar

echo "ENSAYO_RESTAURACION_OK $(basename "$DIR")"
