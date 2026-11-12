# Validación autenticada y E2E del UAT (macroiteración V1.4).
#
# La ejecuta la persona responsable, porque pide las contraseñas sin eco
# (administracion dos veces y luego las cuatro cuentas). No guarda
# contraseñas ni tokens: las salidas solo tienen resultados.
#
# Antes, en la misma terminal, las claves PUBLICABLES (no las secretas):
#   $env:SUPABASE_PUBLISHABLE_KEY_ORIGEN  = "<clave publicable de Oregón>"
#   $env:SUPABASE_PUBLISHABLE_KEY_DESTINO = "<clave publicable de São Paulo>"
# Uso, desde la raíz del repositorio:
#   powershell -ExecutionPolicy Bypass -File supabase\scripts\validacion_uat\validar_uat.ps1 -Salida <carpeta fuera del repositorio>
#
# El paso 3 ESCRIBE datos ficticios: hace falta autorización y, después, la
# limpieza con supabase/scripts/reinicio_uat/ (ver el README de esta carpeta).
param(
    [Parameter(Mandatory = $true)][string]$Salida,
    [switch]$SinOregon
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path "$PSScriptRoot\..\..\..").Path
$py = "$repo\app\backend\.venv\Scripts\python.exe"
if (-not $env:SUPABASE_PUBLISHABLE_KEY_DESTINO -or -not $env:SUPABASE_PUBLISHABLE_KEY_DESTINO.StartsWith("sb_publishable_")) {
    throw "Falta SUPABASE_PUBLISHABLE_KEY_DESTINO (clave publicable de São Paulo)."
}
New-Item -ItemType Directory -Force $Salida | Out-Null
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:SUPABASE_PUBLISHABLE_KEY = $env:SUPABASE_PUBLISHABLE_KEY_DESTINO
Set-Location $repo
$oregon = @()
if ($SinOregon) { $oregon = @("--sin-oregon") }

Write-Host "`n=== 1/3 Inicio de sesión, aislamiento y lecturas (administracion) ===" -ForegroundColor Cyan
& $py supabase/scripts/migracion_sp/probar_entornos.py @oregon | Tee-Object -FilePath "$Salida\resultado_entornos.txt"

Write-Host "`n=== 2/3 Lecturas autenticadas y tiempos (administracion) ===" -ForegroundColor Cyan
& $py supabase/scripts/migracion_sp/medir_api.py --backend https://rt-rma-uat-api-nszqooxxla-rj.a.run.app --supabase-url https://pcdnmhzwhzymznojndrn.supabase.co --repeticiones 5 --pausa 1 | Tee-Object -FilePath "$Salida\resultado_medir_api.txt"

Write-Host "`n=== 3/3 E2E con datos ficticios (las cuatro cuentas) ===" -ForegroundColor Cyan
& $py supabase/scripts/validacion_uat/probar_macro_v14.py --escribir --informe "$Salida\resultado_e2e.json" | Tee-Object -FilePath "$Salida\resultado_e2e.txt"

Remove-Item Env:SUPABASE_PUBLISHABLE_KEY
Write-Host "`nListo. Resultados en $Salida (Tee-Object de PowerShell 5.1 los guarda en UTF-16)." -ForegroundColor Green
