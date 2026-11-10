# Autenticación y autorización

Supabase Auth autentica (email y contraseña); FastAPI autoriza con los roles de PostgreSQL (decisión G-5 de [`postgresql/diseno-logico.md`](postgresql/diseno-logico.md)). El frontend no accede a tablas. Estado y próximos pasos: [`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md).

## 1. Cómo funciona

- **Modos** (`RMA_AUTH_MODO`):
  - `demo`: sin login real; la API confía en el `usuario_id` que recibe. Solo desarrollo local y tests.
  - `supabase`: obligatorio en UAT. La app **no arranca** en `demo` si corre en Cloud Run (`K_SERVICE`) o con una base remota (`RMA_DB_REMOTO_HABILITADO`). Tampoco arranca en `supabase` sin URL `https` o con algoritmos no asimétricos.
- **Token:** se verifica localmente con las claves públicas del proyecto (JWKS, `/auth/v1/.well-known/jwks.json`), sin llamar a Supabase en cada pedido. Se exige:
  - firma `ES256` (la del proyecto `rt-rma-db`, verificada el 09/11/2026); `HS*` y `none` se rechazan siempre;
  - `iss` = `<proyecto>/auth/v1`, `aud` = `authenticated`, `exp`, `iat`, `sub` y `role` = `authenticated`.
- **Identidad:** `sub` del token = `rma.usuario.auth_user_id`. Rol y estado salen de PostgreSQL (`usuario_rol`), nunca del token, y se leen **en cada pedido** (sin memoria entre pedidos): desactivar a alguien o cambiarle el rol vale desde el pedido siguiente. Costo: una lectura más por pedido (en UAT, un viaje a la base, unos 0,18 s).
- **Respuestas:** 401 `NO_AUTENTICADO` (falta, inválido o vencido); 403 `USUARIO_NO_HABILITADO` (sin vínculo), `USUARIO_INACTIVO`, `IDENTIDAD_NO_COINCIDE` o `ROL_NO_AUTORIZADO`; 503 `AUTENTICACION_NO_DISPONIBLE` si no se pueden obtener las claves.
- **Transición del contrato:** los endpoints siguen recibiendo `usuario_id` (cuerpo o consulta) y los casos de uso no cambian. Con sesión, ese `usuario_id` debe ser el del token (también si se repite en la consulta). Por eso las claves de idempotencia, cuyo alcance es `(usuario_id, clave)`, quedan aisladas por identidad. Quitar `usuario_id` del contrato es un paso posterior.

## 2. Endpoints

| Grupo | Protección |
|---|---|
| `GET /health` | Público |
| `GET /api/me` | Sesión: el usuario de RMA de la sesión |
| Lecturas (`/api/orders…`, `/api/catalogs/*`, `/api/inventory`, `/api/work/*`, documentos, PDF) | Sesión |
| Comandos de la Orden (`POST/PUT /api/orders…`) | Sesión + `usuario_id` = sesión; rol, titular y estado los valida el caso de uso (409 como hasta ahora) |
| Eventos de sistema sin actor (`resources/wait`, `resources/revalidate`, `inform-rt`) | Sesión (el proceso no asigna un rol: `ACT-SYSTEM`) |
| Fotos: subir y ver (`/api/orders/{id}/photos…`) | Sesión + `ROLES_FOTOS` |
| Inventario: ingresos y ajustes | Sesión + `ROLES_GESTION_STOCK` (Administración, Coordinación) |
| Inventario: revalidar Órdenes | Sesión + `ROLES_REVALIDACION_RECURSOS` |
| Catálogo de Ventas: `POST /api/catalogs/equipment/sync` | Sesión + `ROLES_SINCRONIZACION_CATALOGO` |
| Clientes: `GET /api/clients/lookup` | Sesión + `ROLES_BUSQUEDA_CLIENTE` (Recepción, Administración) |
| Mantenimiento: `POST /api/maintenance/photos/cleanup` | Sesión + Administración |

Las rutas con rol responden 403 antes de ejecutar nada; usan las mismas constantes que ya validan los casos de uso (no hay reglas nuevas). En `demo` se comportan como antes.

## 3. Frontend

- `@supabase/auth-js` 2.118.0, solo para la sesión: inicio con email y contraseña, renovación automática del token, cierre (`scope: local`).
- Cada pedido a la API lleva `Authorization: Bearer`; las fotos se descargan con el token (ya no `<img src>` directo).
- Después del inicio, `GET /api/me` decide el usuario. Un 401 cierra la sesión y vuelve al acceso con «Tu sesión venció»; un 403 de `/api/me` muestra el motivo.
- Variables (`app/frontend/.env.example`): `VITE_AUTH_MODO`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` (la clave **publicable**; una clave secreta o `service_role` se rechaza). Un build de producción sin `supabase` muestra «Configuración de acceso incompleta»: nunca el acceso de prueba.

## 4. Configuración requerida (UAT)

Nada de esto se aplicó. Cada paso remoto necesita autorización explícita.

**Supabase Auth** (proyecto `rt-rma-db`, ref `okcscsglnujnxtgobjfw`):
1. *Authentication → Sign In / Providers → Email*: habilitado. **«Allow new users to sign up»: desactivado.**
2. *JWT Keys*: la clave actual ES256 (ya en uso). No volver a HS256: el backend lo rechaza.
3. *URL Configuration*: Site URL `https://rt-rma-uat.vercel.app`.
4. *Users → Add user → Create new user*: las cuatro cuentas de prueba (emails a definir por negocio), con «Auto Confirm User». Las contraseñas se entregan fuera del repositorio.
5. Vincular cada cuenta con [`supabase/scripts/vincular_usuarios_auth.sql`](../supabase/scripts/vincular_usuarios_auth.sql), por persona: `RECEP-001`, `TECH-001`, `COORD-001`, `ADMIN-001`. Solo completa vínculos vacíos y falla sin cambiar nada si algo no coincide (probado en local).

**Cloud Run** (`rt-rma-uat-api`): agregar `RMA_AUTH_MODO=supabase` y `RMA_AUTH_SUPABASE_URL=https://okcscsglnujnxtgobjfw.supabase.co`. Sin secretos nuevos. La imagen instala `PyJWT[crypto]` (dependencia de `pyproject.toml`).

**Vercel** (`rt-rma-uat`, producción): `VITE_AUTH_MODO=supabase`, `VITE_SUPABASE_URL=https://okcscsglnujnxtgobjfw.supabase.co`, `VITE_SUPABASE_PUBLISHABLE_KEY=<clave publicable>`, y el `VITE_API_BASE_URL` actual. Nunca una clave secreta.

## 5. Despliegue y vuelta atrás

Comandos y revisiones actuales: [`CHECKPOINT_UAT_OPTIMIZADO.md`](CHECKPOINT_UAT_OPTIMIZADO.md), secciones 2 y 6.

1. **Supabase Auth** (pasos 1 a 5 de arriba). No afecta al UAT actual: el backend publicado ignora los tokens.
2. **Backend sin tráfico**, con las dos variables y `--tag auth`. Humo sobre la URL de la etiqueta: `/health` 200; `/api/orders` sin token 401; con el token de cada cuenta, `/api/me` devuelve su usuario; un `usuario_id` ajeno da 403.
3. **Corte coordinado** (ventana anunciada; el frontend actual no envía token, así que entre los dos pasos el UAT responde 401): `update-traffic --to-latest` del backend y, enseguida, `vercel deploy --prod` del frontend con las variables.
4. **Verificación:** iniciar sesión con las cuatro cuentas, un recorrido por rol, una foto, cierre de sesión.

**Vuelta atrás** (los dos juntos): backend `update-traffic --to-revisions <revisión anterior>=100` (hoy `rt-rma-uat-api-00017-wer`) y frontend `vercel rollback` al despliegue anterior. No hay cambios de esquema ni de datos de negocio: el vínculo `auth_user_id` puede quedar cargado. Las cuentas de Supabase Auth no afectan a la versión anterior.

## 6. Riesgos y pendientes

- Un token emitido sigue siendo válido hasta su vencimiento (1 h por defecto) aunque se cierre la sesión: es propio de la verificación local. Para cortar el acceso de inmediato, desactivar al usuario en RMA (`rma.usuario.activo = false`): vale desde el pedido siguiente.
- `usuario_id` sigue en el contrato durante la transición.
- Sin recuperación de contraseña en la pantalla: la restablece Administración desde Supabase.
- Las cuentas y sus emails reales los define negocio. Sin datos de clientes hasta completar el paso 4.
