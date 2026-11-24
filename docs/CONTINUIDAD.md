# Continuidad: retomar el proyecto en otra computadora

Guía para clonar, preparar el entorno y recuperar el acceso. Es la fuente única para cambiar de computadora. El estado del proyecto está en [`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md) y la última auditoría de portabilidad, en [`AUDITORIA_PORTABILIDAD.md`](AUDITORIA_PORTABILIDAD.md).

Esta guía no contiene contraseñas, tokens ni claves.

## 1. Arquitectura vigente (11/11/2026)

| Pieza | Dónde | Detalle |
|---|---|---|
| Backend | Cloud Run `rt-rma-uat-api`, proyecto `rosariotecno-460217`, `southamerica-east1` | Revisión `rt-rma-uat-api-00024-top` (código `d226fd2`), 100 % del tráfico |
| Frontend | Vercel `rt-rma-uat` (equipo `ismaeldarruizbis-projects`, Root Directory `app/frontend`) | Producción `dpl_6vsLwpAzxE2yS5K7RLHBMNVvETN8`, en `https://rt-rma-uat.vercel.app`. **Desconectado de GitHub:** se despliega a mano ([`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md)) |
| Base y Auth | Supabase São Paulo `pcdnmhzwhzymznojndrn` | 20 migraciones. La API usa `rma_api` (secreto `rma-uat-sp-database-url:1`) y el respaldo usa `rma_respaldo` |
| Respaldo | Job `rt-rma-respaldo-db`, Scheduler `rt-rma-respaldo-diario` (03:00 de Argentina) y bucket `rt-rma-uat-respaldos` | Cifrado con `age`; la clave privada la guarda la persona responsable ([`RESPALDOS.md`](RESPALDOS.md)) |
| Vuelta atrás, hasta el 25/11/2026 | Oregón `okcscsglnujnxtgobjfw`, revisión `00020-tux` (sin etiqueta desde el 16/11/2026) y despliegue `dpl_F1M6…` | [`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 16 |

## 2. Repositorios y ramas

| Repositorio | Uso | Rama para continuar |
|---|---|---|
| `https://github.com/IsmaelDarruizBI/rt-rma-mvp` | Aplicación, base, scripts y documentación | **`mvp-v2`**, igual a `feat/postgresql-esquema`. Los módulos nuevos salen de `mvp-v2` en ramas propias. `main` está atrás (P0-2) |
| `https://github.com/IsmaelDarruizBI/rt-rma-app` | Fuente funcional: genera `business/` | **`dc31/cancelacion-explicita`** (`ab928b6`, el origen de `business/`; todavía no está en su `main`). `archivo/test-v1.2-3cf273e` solo conserva un commit viejo de la V1.2 |

`rt-rma-app` va en una carpeta **hermana** de `rt-rma-mvp`: así lo esperan los documentos y la sincronización ([`sincronizacion-funcional.md`](sincronizacion-funcional.md)).

## 3. Herramientas (Windows + VS Code)

| Herramienta | Versión | ¿Obligatoria? |
|---|---|---|
| Git para Windows (con Git Bash) | 2.49 o posterior | Sí. Los comandos de los documentos son para Git Bash |
| Python | **3.11** (la de CI y del Dockerfile) | Sí |
| Node.js | **24** (la de CI), con npm 11 | Sí |
| VS Code | Actual | Sí |
| GitHub CLI `gh` | 2.89 o posterior | Sí: estado de CI y PR |
| Google Cloud SDK `gcloud` | 586 o posterior | Sí, para operar el UAT |
| `age` | 1.3 o posterior | Sí, para leer o verificar respaldos |
| Claude Code (CLI y extensión de VS Code) | 2.1 o posterior | Si se trabaja con agentes. `CLAUDE.md` carga `AGENTS.md` y las skills están en `.claude/skills/` |
| CLI de Supabase | 3.1.0, siempre `npx -y supabase@3.1.0`, sin instalarla | Se usa por npx |
| CLI de Vercel | 65.x, por `npx` | Solo para desplegar el frontend |
| Docker Desktop | Actual | Opcional: pila local de Supabase y `probar_respaldo_local.sh` |
| PostgreSQL 17 local (embedded-postgres) | 17 | Opcional: pruebas `tests/postgres` ([`CHECKPOINT_UAT_OPTIMIZADO.md`](CHECKPOINT_UAT_OPTIMIZADO.md), sección 5) |

Instalación de lo obligatorio, en PowerShell:

```powershell
winget install Git.Git Python.Python.3.11 GitHub.cli Google.CloudSDK Microsoft.VisualStudioCode FiloSottile.age
```

Node.js **24**: desde `nodejs.org`, o con `winget install OpenJS.NodeJS --version <24.x>`. Las versiones disponibles se ven con `winget show OpenJS.NodeJS --versions`. Verificar con `node -v`.

## 4. Clonar y preparar (Git Bash)

```bash
mkdir -p ~/RepositoriosRT && cd ~/RepositoriosRT
git clone https://github.com/IsmaelDarruizBI/rt-rma-mvp.git
git clone https://github.com/IsmaelDarruizBI/rt-rma-app.git
(cd rt-rma-app && git checkout dc31/cancelacion-explicita)
cd rt-rma-mvp && git checkout mvp-v2

npm ci                                         # validaciones de la fuente funcional
cd app/backend && py -3.11 -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev,postgres]" && cd ../..
cd app/frontend && npm ci && cd ../..
```

**Variables locales:** ninguna es obligatoria. El backend arranca en modo JSON con `auth_modo=demo` y el frontend usa los valores por defecto de `.env.example`. **No crear archivos `.env` con credenciales remotas.** Para PostgreSQL local: [`CHECKPOINT_UAT_OPTIMIZADO.md`](CHECKPOINT_UAT_OPTIMIZADO.md), sección 5.

## 5. Recuperar el acceso

Cada persona, con su cuenta; cada comando abre el navegador:

```bash
gh auth login
gcloud auth login && gcloud config set project rosariotecno-460217
npx -y supabase@3.1.0 login
npx -y vercel@65 login          # solo para desplegar
```

- **Supabase:** las herramientas usan `--remote=<ref>`, así que no hace falta `supabase link`. La excepción es `generar_credencial_rma_api.cjs`, que exige el proyecto vinculado: `npx -y supabase@3.1.0 link --project-ref pcdnmhzwhzymznojndrn`.
- **Vercel:** `vercel link` crea `.env.local` con un token. Borrarlo y nunca copiarlo al repositorio. Para desplegar, usar una exportación limpia ([`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md)).

## 6. Validar la computadora nueva

```bash
# Código: lo mismo que CI
npm run validate:all
cd app/backend && .venv/Scripts/python -m ruff check . ../../supabase/scripts --config pyproject.toml && .venv/Scripts/python -m pytest -q && cd ../..
cd app/frontend && npm run typecheck && npm test && npm run build && cd ../..

# Servicios: solo lectura
gh auth status
gcloud run services describe rt-rma-uat-api --region southamerica-east1 --format="value(status.traffic)"
gcloud scheduler jobs describe rt-rma-respaldo-diario --location southamerica-east1 --format="value(state,lastAttemptTime)"
gcloud run jobs executions list --job rt-rma-respaldo-db --region southamerica-east1 --limit 3
gcloud storage ls gs://rt-rma-uat-respaldos/uat/
npx -y supabase@3.1.0 projects list --agent no --output-format json
curl -s -o /dev/null -w "%{http_code}\n" https://rt-rma-uat.vercel.app/
```

**Clave `age` trasladada** (PowerShell). Tiene que imprimir exactamente `age1zen3sqv9sct60w878lfernqua9lf40kchat5hppq4hs2zzq7reqs0yazx5`, la clave pública configurada en el Job:

```powershell
age-keygen -y "<ruta a rma-respaldo.key>"
```

Para una prueba completa, descifrar la última copia ([`RESPALDOS.md`](RESPALDOS.md), sección 3).

## 7. Lo que no está en GitHub (se traslada por separado)

| Qué | Cómo |
|---|---|
| **Clave privada `age`** (`rma-respaldo.key`) | Gestor de contraseñas y una copia fuera de línea (por ejemplo, un pendrive cifrado). Nunca por correo, chat, la nube ni el repositorio. Fuera del repositorio, en una carpeta con acceso solo para el usuario. **Sin ella los respaldos no se pueden leer** |
| Contraseñas de las 4 cuentas del UAT y de los administradores de las bases (São Paulo y Oregón) | Gestor de contraseñas |
| Copias con datos personales (`respaldos-rma\sp-or000001-20261111`, y `uat-reinicio-20261110` en una computadora anterior) | No se trasladan por medios comunes. Vencen el 25/11/2026 ([`RESPALDOS.md`](RESPALDOS.md), sección 5) |
| Memoria de Claude Code (opcional) | Copiar `%USERPROFILE%\.claude\projects\<carpeta del repositorio>\memory\`. No tiene secretos |

Todo lo demás se regenera o se recupera iniciando sesión: dependencias, la base local de desarrollo y las sesiones de las CLI.

## 8. Recursos de QA

- **Guía de pruebas manual del UAT:** [`qa/guia-pruebas-uat.html`](qa/guia-pruebas-uat.html), versión 2 del 15/10/2026. Se abre en el navegador; las marcas quedan solo en ese navegador. **Está desactualizada en un punto:** el rol ya no se elige en «Usuario (modo demo)», ahora se inicia sesión con usuario y contraseña ([`autenticacion.md`](autenticacion.md)). El resto del recorrido sigue valiendo.
- **Pruebas de API del UAT:** `supabase/scripts/migracion_sp/probar_entornos.py` (solo lectura) y la validación E2E de [`supabase/scripts/validacion_uat/`](../supabase/scripts/validacion_uat/README.md), con su limpieza. `probar_recorridos.py` quedó para la revisión `saopaulo---`, que ya no existe. Las que escriben no se usan en el UAT sin autorización, porque crean Órdenes.

## 9. Pendientes con fecha

1. **12/11/2026:** confirmar la primera ejecución programada del respaldo (06:00 UTC), con los comandos de la sección 6.
2. **Hasta el 25/11/2026:** una consulta semanal de solo lectura en Oregón, para que el plan Free no lo pause.
3. **25/11/2026:**
   - decidir sobre Oregón: pausarlo o eliminarlo, junto con `00020-tux`, `rma-uat-database-url` y `dpl_F1M6…`;
   - borrar las copias con datos personales.
4. **Integrar en `main`** (P0-2), con un PR.

## 10. Retomar los ajustes funcionales (ramas de trabajo, 24/11/2026)

Los ocho bloques de ajustes funcionales están en dos ramas de trabajo publicadas, **sin integrar**: ni en `mvp-v2` ni en `main`, y sin desplegar.

| Repositorio | Rama | Contenido |
|---|---|---|
| `rt-rma-mvp` | `feat/ajustes-funcionales-uat` | Código, 9 migraciones nuevas (`20261123000100` a `20261124000600`), pruebas, scripts de validación y documentación |
| `rt-rma-app` | `spec/ajustes-funcionales` | DEC-AJ-01 a 14 y las reglas actualizadas; es el origen de `business/` |

El estado y el próximo paso están en [`ajustes-funcionales-discovery.md`](ajustes-funcionales-discovery.md), secciones 11.1 y 12.

**1. Clonar o actualizar,** en PowerShell. Las dos carpetas van una al lado de la otra:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\RepositoriosRT" | Out-Null
Set-Location "$env:USERPROFILE\RepositoriosRT"
# Primera vez:
git clone https://github.com/IsmaelDarruizBI/rt-rma-mvp.git
git clone https://github.com/IsmaelDarruizBI/rt-rma-app.git
git -C rt-rma-mvp switch feat/ajustes-funcionales-uat
git -C rt-rma-app switch spec/ajustes-funcionales
# Si ya estaban clonados:
git -C rt-rma-mvp fetch origin
git -C rt-rma-mvp switch feat/ajustes-funcionales-uat
git -C rt-rma-mvp pull --ff-only
git -C rt-rma-app fetch origin
git -C rt-rma-app switch spec/ajustes-funcionales
git -C rt-rma-app pull --ff-only
```

**2. Dependencias:** Python 3.11, Node.js 24 y Git (sección 3). Después, desde `rt-rma-mvp`:

```powershell
npm ci
Set-Location app\backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,postgres]"
Set-Location ..\frontend
npm ci
Set-Location ..\..
```

El `pip install` incluye `openpyxl`, la dependencia nueva de la importación de precios.

**3. PostgreSQL 17 local,** la primera vez en esa computadora, fuera del repositorio:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\pg-rma" | Out-Null
Set-Location "$env:USERPROFILE\pg-rma"
npm init -y
npm install embedded-postgres@17.10.0-beta.17
$pgbin = "$env:USERPROFILE\pg-rma\node_modules\@embedded-postgres\windows-x64\native\bin"
& "$pgbin\initdb.exe" -D "$env:USERPROFILE\pg-rma\data" -U postgres -A trust -E UTF8 --locale=C
```

Para iniciarlo, ver [`VALIDACION_LOCAL.md`](VALIDACION_LOCAL.md), sección 2.2.

**4. Base nueva, migraciones y datos ficticios:** [`VALIDACION_LOCAL.md`](VALIDACION_LOCAL.md), sección 2.

- La sección 2.3 crea `rma_validacion`: aplica las 51 migraciones y las 5 cargas, y debe responder «56 archivos SQL; 80 tablas en rma».
- La sección 2.4 levanta el backend sobre esa base.
- La sección 2.5 carga los datos ficticios por la API.
- La sección 2.6 levanta el frontend.

**La base local no se copia:** se reconstruye con esos pasos.

**5. Lo que no está en Git y no hace falta para validar:**
- las bases locales (`rma_validacion`, `rma_dev` y las demás);
- `%USERPROFILE%\rma-validacion-data`, con las fotos y las planillas de ejemplo, que el script de carga vuelve a generar;
- el `.venv` y los `node_modules`;
- los archivos `.env` o `.env.local`. No hace falta ninguno: el backend usa la autenticación de prueba y el frontend llama a `http://localhost:8000` por defecto.

Lo del UAT está en la sección 7.

Deuda técnica: [`DEUDA_TECNICA.md`](DEUDA_TECNICA.md).
