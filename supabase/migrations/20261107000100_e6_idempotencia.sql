-- E6 (B1): idempotencia de los comandos que crean registros.
--
-- Aditiva: agrega una columna nula. La clave, su alcance y su unicidad ya
-- existen: accion_usuario_idempotencia, única por usuario y clave entre las
-- acciones CONFIRMADAS (G-9). Un rechazo no bloquea el reintento.
-- Diseño: docs/postgresql/e4-e7-diseno-integrado.md (secciones 6 y 20).

-- DE6-3: la huella de la operación y sus parámetros. La misma clave con otra
-- huella es una clave reutilizada (422), no un reintento.
alter table rma.accion_usuario add column huella text
  check (huella is null or huella ~ '^[0-9a-f]{64}$');

comment on column rma.accion_usuario.huella is 'SHA-256, en hexadecimal, de la operación y de sus parámetros normalizados. Con la misma clave de idempotencia y otra huella, la clave se reutilizó para otra operación.';
comment on column rma.accion_usuario.respuesta is 'Respuesta que se devolvió (código HTTP y cuerpo): un reintento con la misma clave y la misma huella recibe exactamente lo mismo.';
