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

## Resultado de la revisión del 11/11/2026 (`00020-tux`, Oregón)

- **Correcto:**
  - todos los puntos de backend, base de datos y frontend;
  - registro deshabilitado y ES256 en los dos proyectos.
- **Hallazgo corregido en código (sin desplegar):** `/docs`, `/redoc` y `/openapi.json` eran públicos y mostraban 78 rutas; se corrige en `4af9854`. Queda pendiente para el próximo despliegue.
- **Pendiente de confirmar en el panel:** el largo mínimo 10 en los dos proyectos.
