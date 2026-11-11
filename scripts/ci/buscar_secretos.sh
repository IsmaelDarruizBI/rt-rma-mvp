#!/usr/bin/env bash
# Busca credenciales en los archivos versionados (y en los nuevos sin
# ignorar). Falla si encuentra alguna fuera de la lista permitida.
#
#   bash scripts/ci/buscar_secretos.sh
#
# Patrones: scripts/ci/patrones_secretos.txt (claves de Supabase, JWT,
# cadenas de conexión con contraseña, claves privadas, hashes bcrypt, claves
# de Google y claves privadas de age). Excepciones exactas, de texto
# ilustrativo o de la pila local: scripts/ci/secretos_permitidos.txt.
# Solo imprime archivo y línea, nunca el valor encontrado.

set -euo pipefail
cd "$(dirname "$0")/../.."

hallazgos=$(
  { git ls-files; git ls-files --others --exclude-standard; } \
    | sort -u \
    | grep -vE '^(scripts/ci/patrones_secretos\.txt|scripts/ci/secretos_permitidos\.txt)$' \
    | grep -vE '(^|/)node_modules/' \
    | tr '\n' '\0' \
    | xargs -0 grep -InEf scripts/ci/patrones_secretos.txt 2>/dev/null \
    | grep -vFf scripts/ci/secretos_permitidos.txt || true
)

if [ -n "$hallazgos" ]; then
  echo "Posibles credenciales en el repositorio (archivo:línea):"
  echo "$hallazgos" | cut -d: -f1,2
  exit 1
fi
echo "Sin credenciales en los archivos versionados."
