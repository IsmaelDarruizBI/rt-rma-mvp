# Checklist de seguridad para cada despliegue

Controles críticos para revisar antes y después de publicar. No es una auditoría: confirma que se mantienen las decisiones vigentes ([`autenticacion.md`](autenticacion.md), [`postgresql/e8-activacion-supabase.md`](postgresql/e8-activacion-supabase.md)). El resultado de cada despliegue se anota en [`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md).

## Repositorio

- [ ] `bash scripts/ci/buscar_secretos.sh` sin hallazgos. También lo corre el workflow `seguridad`.
- [ ] Sin `.env` (solo `.env.example`), respaldos, volcados ni capturas locales (`.playwright-mcp/`) versionados.
- [ ] Las migraciones nuevas son aditivas y pasaron el workflow `postgres`.

## Backend (revisión nueva, por su URL de etiqueta)

- [ ] `RMA_AUTH_MODO=supabase`. Fuera de desarrollo local, el modo `demo` impide arrancar.
- [ ] `RMA_AUTH_SUPABASE_URL` es el proyecto correcto y coincide con el frontend.
- [ ] **Token:** sin token → 401; token inválido → 401; token de otro proyecto → 401 (`supabase/scripts/migracion_sp/probar_entornos.py`).
- [ ] **Identidad y rol:** suplantación (`usuario_id` ajeno) → 403 `IDENTIDAD_NO_COINCIDE`; rol sin permiso → 403 `ROL_NO_AUTORIZADO`.
- [ ] `/docs`, `/redoc` y `/openapi.json` → 404 (desde `4af9854`).
- [ ] `RMA_CORS_ALLOW_ORIGINS` solo con los orígenes necesarios, sin `*`. Un origen ajeno no recibe `Access-Control-Allow-Origin`.
- [ ] **Base de datos:**
  - `RMA_DATABASE_URL` sale de Secret Manager con la **versión fijada**;
  - el secreto lo lee solo la cuenta de la API;
  - `sslmode=verify-full`, con la CA incluida en la imagen.
- [ ] Registros sin `ERROR`, sin 5xx y sin credenciales (`postgresql://`, `sb_secret`, `password`).

## Base de datos

- [ ] `rma_api`:
  - miembro solo de `rma_backend`;
  - sin `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `BYPASSRLS` ni `REPLICATION`;
  - `connection limit` 20.
- [ ] `rma_backend` sin `DELETE` (salvo `usuario_rol`) ni `TRUNCATE`.
- [ ] `anon`, `authenticated` y `service_role` sin `usage` en `rma`.

`migrar_uat.py verificar` comprueba los dos últimos puntos; `comparar` compara los permisos con otro proyecto.

## Supabase Auth

- [ ] `GET /auth/v1/settings`, con la clave publicable:
  - `disable_signup: true`;
  - solo el proveedor `email`.
- [ ] JWKS con `ES256`.
- [ ] **En el panel:** largo mínimo de contraseña 10, Site URL del frontend, límites por IP, sin Redirect URLs de más.
- [ ] Ninguna cuenta ficticia (`prueba-%`) y cada cuenta vinculada a un usuario de RMA activo.

## Frontend

- [ ] El bundle contiene solo `sb_publishable_`; ninguna `sb_secret_` con valor ni JWT de `service_role`.
- [ ] Apunta al mismo ref de Supabase que el backend y a la URL pública del backend.
- [ ] La pantalla de acceso no revela qué usuarios existen: mismo mensaje para usuario inexistente o contraseña incorrecta.

## Preparación de la macroiteración integral (15/11/2026, sin desplegar)

- **Verificado en local** (ensayo del despliegue, [`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md), sección 7):
  - repositorio: escaneo de secretos sin hallazgos; las 12 migraciones nuevas son aditivas y no crean ni modifican roles; la función del libro sigue `security definer` con `search_path` fijo, como antes;
  - base, después de las 35 migraciones: `rma_backend` lee las 69 tablas, con DELETE solo en `usuario_rol` y `mesa_tipo_reparacion` (este último desde la migración 23) y sin TRUNCATE; UPDATE en las tablas nuevas solo en los catálogos de configuración; `anon`, `authenticated` y `service_role` sin `usage` en `rma`; la API del ensayo conectó con un rol miembro de `rma_backend`, como `rma_api`;
  - API: ninguna ruta ni campo de la anterior desaparece; las rutas nuevas de administración, compras, costos, roles, permisos y la copia del catálogo responden 403 sin el permiso con sesión real (`test_seguridad_de_roles_compras_y_configuracion`); nadie se asigna administración ni actúa en nombre de otro;
  - DC12: `RMA_TIPO_EQUIPO_CAMPO` no se configura; sin ella no se lee el catálogo de Ventas para tipos y no se escribe nada.
- **A verificar en el despliegue:** los puntos de Backend, Base de datos, Supabase Auth y Frontend de arriba, por la URL de la etiqueta y con sesión real; que la plantilla heredada no tenga `RMA_TIPO_EQUIPO_CAMPO`.

## Resultado de la revisión del 11/11/2026 (`00020-tux`, Oregón)

- **Correcto:**
  - todos los puntos de backend, base de datos y frontend;
  - registro deshabilitado y ES256 en los dos proyectos.
- **Hallazgo corregido en código (sin desplegar):** `/docs`, `/redoc` y `/openapi.json` eran públicos y mostraban 78 rutas; se corrige en `4af9854`. Queda pendiente para el próximo despliegue.
- **Pendiente de confirmar en el panel:** el largo mínimo 10 en los dos proyectos.

## Resultado de la revisión del 16/11/2026 (`00031-ror`, macroiteración integral, São Paulo)

- **Correcto:**
  - repositorio: escaneo de secretos sin hallazgos; CI en verde en `9176921`; las 12 migraciones son aditivas y no cambian roles;
  - backend: plantilla heredada de `00029-kay` (14 variables, `RMA_AUTH_MODO=supabase` con el Auth de São Paulo, `RMA_DATABASE_URL` desde `rma-uat-sp-database-url:1`, CORS solo del frontend) y **sin `RMA_TIPO_EQUIPO_CAMPO`** (DC12 desactivada); 401 sin token y con token inválido, también en compras, administración, lotes y checklist; `/docs`, `/redoc` y `/openapi.json` 404; un origen ajeno no recibe CORS; registros sin errores, 5xx ni credenciales;
  - base, después de migrar: `rma_backend` lee las 69 tablas, con DELETE solo en `usuario_rol` y `mesa_tipo_reparacion` y sin TRUNCATE; `rma_api` miembro solo de `rma_backend`, sin `SUPERUSER`, `BYPASSRLS` ni `CREATEROLE`, límite 20; `anon`, `authenticated` y `service_role` sin `usage` en `rma`; `rma_respaldo` lee las tablas nuevas; `verificar_integridad()` vacío;
  - Supabase Auth: **largo mínimo de contraseña 10** (estaba en 6; lo cambió la persona responsable el 15/11/2026, y las cuatro contraseñas cumplen);
  - frontend: solo la clave publicable, sin JWT ni `sb_secret_` con valor; mismo ref que el backend y el mismo servicio de Cloud Run; Vercel sin vínculo con Git.
- **Verificado con sesiones reales:** `probar_entornos.py` contra la etiqueta y, ya publicado, los dos E2E con las cuatro cuentas: Recepción, Técnico y Coordinación reciben 403 donde corresponde (administración, permisos, compras, devoluciones, reclamos, comunicaciones), y consultar no habilita escribir.
- **No verificado en esta revisión:** suplantación con una sesión real (el script usa siempre el token del actor del pedido); la pasada manual en un navegador real (P2-17).

## Resultado de la revisión del 12/11/2026 (`00029-kay`, macroiteración V1.4, São Paulo)

- **Correcto:**
  - repositorio: escaneo de secretos sin hallazgos y migraciones aditivas con el workflow `postgres` en verde;
  - backend: la plantilla de `00027-sas` sin cambios (14 variables, `RMA_AUTH_MODO=supabase` con el Auth de São Paulo, `RMA_DATABASE_URL` desde `rma-uat-sp-database-url:1`, CORS solo del frontend); 401 sin token y con token inválido, también en reportes, antecedentes, administración, evaluación y adicionales; `/docs`, `/redoc` y `/openapi.json` 404; registros sin errores, 5xx ni credenciales;
  - base: las tablas nuevas solo con SELECT e INSERT para `rma_backend` y con triggers de inmutabilidad; `anon` y `authenticated` sin acceso; `rma_respaldo` solo lee; las pruebas de la macroiteración pasan con un rol miembro de `rma_backend`; la migración no cambia roles; integridad sin problemas en el ensayo de restauración;
  - Supabase Auth: registro deshabilitado, solo `email`, JWKS `ES256`;
  - frontend: solo la clave publicable, sin JWT ni claves secretas; mismo ref que el backend y la URL pública de la API.
- **Verificado después con sesiones reales** (validación del 12/11/2026, [`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md), sección B):
  - un token de Oregón da 401 en São Paulo y viceversa;
  - Recepción, Técnico y Coordinación reciben 403 en la administración, al editar Tipos y al configurar Mesas;
  - Recepción no puede evaluar ni registrar adicionales;
  - reportes y antecedentes no muestran datos personales del cliente.
- **No verificado en esta revisión:** suplantación con una sesión real (el script usa siempre el token del actor del pedido); el largo mínimo de contraseña en el panel.

## Resultado de la revisión del 12/11/2026 (`00027-sas`, iteración 1, São Paulo)

- **Correcto:**
  - repositorio: escaneo de secretos sin hallazgos y migración aditiva con el workflow `postgres` en verde;
  - backend: `RMA_AUTH_MODO=supabase` con el Auth de São Paulo; 401 sin token y con token inválido; `/docs`, `/redoc` y `/openapi.json` 404; CORS solo del frontend; `RMA_DATABASE_URL` desde `rma-uat-sp-database-url:1`; registros sin errores, 5xx ni credenciales;
  - base: permisos de `rma_backend` sobre las columnas nuevas y `verificar_integridad()` sin problemas; la migración no cambia roles ni permisos;
  - Supabase Auth: registro deshabilitado, solo `email`, JWKS `ES256`;
  - frontend: solo la clave publicable, sin JWT; mismo ref que el backend y la URL pública de la API.
- **No verificado en esta revisión:** token de otro proyecto, suplantación y rol sin permiso con una sesión real (piden la contraseña de una cuenta); el largo mínimo de contraseña en el panel.
