# Continuidad: retomar el proyecto en otra computadora

Guía breve para clonar, preparar el entorno y recuperar el acceso. El estado y las decisiones están en [`CIERRE_CONSOLIDACION_TECNICA.md`](CIERRE_CONSOLIDACION_TECNICA.md) y [`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md). Esta guía no contiene contraseñas, tokens ni claves.

## 1. Repositorios y rama

| Repositorio | Uso | Rama para continuar |
|---|---|---|
| `https://github.com/IsmaelDarruizBI/rt-rma-mvp` | Aplicación, base, scripts, documentación | **`mvp-v2`**, integrada por avance rápido con `feat/postgresql-esquema` el 11/11/2026. Si la integración no se completó, `feat/postgresql-esquema` |
| `https://github.com/IsmaelDarruizBI/rt-rma-app` | Fuente funcional (`business/`), en la carpeta hermana `../rt-rma-app` | `dc31/cancelacion-explicita` (commit `ab928b6`, sincronizado en `business/`) |

Último commit publicado: `git log -1 origin/mvp-v2` (o la rama de arriba).

## 2. Herramientas

| Herramienta | Versión | Uso |
|---|---|---|
| Git y Git Bash | — | Los comandos de los documentos son para Git Bash |
| Python | 3.11 o posterior (la imagen usa 3.11) | Backend y scripts de `supabase/scripts/` |
| Node.js | 24 (la de CI) | Frontend y validaciones de la raíz |
| Docker Desktop | — | Pila local de Supabase, pruebas de respaldo, `actionlint` |
| Supabase CLI | 3.1.0, siempre por `npx -y supabase@3.1.0`, sin instalarla | Base local, consultas y migraciones remotas |
| Google Cloud SDK (`gcloud`) | — | Cloud Run, Secret Manager, GCS |
| Vercel CLI | 65.14.0, por `npx -y vercel@65.14.0` | Despliegues del frontend |
| GitHub CLI (`gh`) | — | PR y estado de CI |
| `age` | — | Solo para leer o crear respaldos ([`RESPALDOS.md`](RESPALDOS.md)) |

## 3. Clonar y preparar (Git Bash)

```bash
mkdir -p ~/repositorios-rt && cd ~/repositorios-rt
git clone https://github.com/IsmaelDarruizBI/rt-rma-mvp.git
git clone https://github.com/IsmaelDarruizBI/rt-rma-app.git
cd rt-rma-mvp && git checkout mvp-v2

# Raíz: validaciones de la fuente funcional
npm ci && npm run validate:all

# Backend
cd app/backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,postgres]"   # en Linux o macOS: .venv/bin/python
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m pytest tests/test_autenticacion.py -q
cd ../..

# Frontend
cd app/frontend && npm ci && npm run typecheck && npm test && cd ../..

# Base local, opcional (Docker): esquema con las 20 migraciones y datos ficticios
npx -y supabase@3.1.0 start -x studio,storage-api,imgproxy,realtime,edge-runtime,logflare,vector,mailpit,postgres-meta,supavisor
```

Entorno local completo, con PostgreSQL y modo demo: [`CHECKPOINT_UAT_OPTIMIZADO.md`](CHECKPOINT_UAT_OPTIMIZADO.md), sección 5.

## 4. Recuperar el acceso (cada persona, con su cuenta)

```bash
gh auth login
gcloud auth login && gcloud config set project rosariotecno-460217
npx -y supabase@3.1.0 login
npx -y vercel@65.14.0 login
```

**Comprobación de solo lectura:**

```bash
gcloud run services describe rt-rma-uat-api --region southamerica-east1 --format="value(status.traffic[0].revisionName,status.traffic[0].percent)"
npx -y supabase@3.1.0 projects list --agent no --output-format json
```

**Vercel:** `vercel link` en una carpeta de trabajo crea `.env.local` con un token. Borrarlo y nunca copiarlo al repositorio. Para desplegar, usar una exportación limpia ([`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md)).

## 5. Estado al 11/11/2026

| Pieza | Oregón (`okcscsglnujnxtgobjfw`) | São Paulo (`pcdnmhzwhzymznojndrn`) |
|---|---|---|
| Rol | **UAT público** | Preparado; corte pendiente |
| Cloud Run | `rt-rma-uat-api-00020-tux`, 100 % (etiqueta `auth`) | `rt-rma-uat-api-00023-zus`, 0 % (etiqueta `corte`); prueba: `00022-vab` (`saopaulo`) |
| Vercel | Producción `rt-rma-n49rz9qgv…` | Vista previa `rt-rma-k1qeeu33d…` |
| Datos | Cero Órdenes, BAT-IP14 10/0, 4 usuarios | Igual, más `OR-000001` abierta (prueba manual de la vista previa) |
| Secreto | `rma-uat-database-url` | `rma-uat-sp-database-url:1` |

## 6. Pendientes críticos (P0, con autorización)

1. **Corte a São Paulo:** antes, decidir qué pasa con `OR-000001` ([`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 16).
2. **Respaldo automático** ([`RESPALDOS.md`](RESPALDOS.md), sección 4).
3. **Desplegar la corrección de `/docs`** (`4af9854`), con el procedimiento de [`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md).

Lista completa: [`DEUDA_TECNICA.md`](DEUDA_TECNICA.md).

## 7. Lo que no está en GitHub (se traslada por separado)

| Qué | Dónde estaba | Cómo trasladarlo |
|---|---|---|
| Respaldo previo al reinicio de Oregón (contiene datos personales) | `%USERPROFILE%\respaldos-rma\uat-reinicio-20261110\` | Medio cifrado o bóveda de archivos; nunca por correo ni por chat |
| Respaldo de las pruebas de São Paulo (datos ficticios) | `%USERPROFILE%\respaldos-rma\sp-pruebas-20261111\` | Igual; se puede descartar al cerrar el período de vuelta atrás |
| Contraseñas de las 4 cuentas del UAT y de los administradores de las bases (Oregón y São Paulo) | Gestor de contraseñas | Ya viven en el gestor |
| Clave privada de `age`, cuando se active el respaldo | Gestor de contraseñas y copia fuera de línea | Nunca en el repositorio ni en la nube |

No hace falta trasladar nada más. `app/backend/.env` no existe en la computadora anterior; si se crea uno local, se reconstruye desde `.env.example`.
