# (Re)crea la base LOCAL de validacion manual "rma_validacion" (PostgreSQL
# local, puerto 54329) con las 51 migraciones, las 4 cargas de referencia y
# la carga de desarrollo. Borra lo que hubiera en esa base.
#
# Solo admite "rma_validacion": rma_dev, rma_ensayo_integral y cualquier otra
# base se rechazan sin conectarse.
#
# Uso, desde la raiz del repositorio:
#   powershell -ExecutionPolicy Bypass -File supabase\scripts\validacion_local\crear_base_validacion.ps1
#
# Esperado: "56 archivos SQL; 80 tablas en rma".
param(
    [string]$Base = "rma_validacion"
)
$ErrorActionPreference = "Stop"
if ($Base -ne "rma_validacion") {
    [Console]::Error.WriteLine("Rechazado: este script solo (re)crea rma_validacion, no '$Base'.")
    exit 2
}
$repo = (Resolve-Path "$PSScriptRoot\..\..\..").Path
$py = Join-Path $repo "app\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    [Console]::Error.WriteLine("Falta el entorno del backend ($py). Ver docs\VALIDACION_LOCAL.md, paso 1.")
    exit 1
}
& $py (Join-Path $PSScriptRoot "crear_base_validacion.py") --base $Base
exit $LASTEXITCODE
