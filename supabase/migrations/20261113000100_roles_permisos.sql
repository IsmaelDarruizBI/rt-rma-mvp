-- Roles múltiples y permisos configurables (macroiteración integral,
-- DEC-MI-12; DC08, DC27A, DC27B y BR-REP-039).
--
-- Aditiva y compatible con el código anterior:
--   * tabla nueva `permiso`: los permisos que Administración cambió respecto
--     de su predeterminado. Sin fila rige el predeterminado del código, así
--     que una base sin filas se comporta exactamente como hasta ahora;
--   * `cambio_configuracion.entidad` admite las entidades que se administran
--     en esta macroiteración (usuarios y sus roles, permisos, insumos,
--     motivos, plantillas, parámetros, checklist y proveedores). El código
--     anterior solo escribe TIPO_REPARACION y MESA_TRABAJO, que siguen
--     valiendo.
-- `usuario_rol` ya admitía varios roles por usuario y `evento_negocio`
-- ya tenía `rol_codigo`: no cambian.

create table if not exists rma.permiso (
  codigo text primary key check (codigo ~ '^[A-Z][A-Z_]*$'),
  roles text[] not null
    check (roles <@ array['ADMINISTRADOR', 'RECEPCION', 'COORDINADOR_RMA', 'TECNICO']::text[]),
  modificado_en timestamptz not null default now()
);

comment on table rma.permiso is
  'Permisos configurados por Administración (BR-REP-039): los roles que habilitan cada acción. Sin fila rige el predeterminado del producto. Cada cambio queda en cambio_configuracion (entidad PERMISO).';
comment on column rma.permiso.codigo is 'Código de la acción (por ejemplo PAGO_REGISTRAR).';
comment on column rma.permiso.roles is 'Roles que la habilitan; vacío si ningún rol la tiene.';
comment on column rma.permiso.modificado_en is 'Fecha y hora del último cambio.';

grant select, insert, update on rma.permiso to rma_backend;

alter table rma.cambio_configuracion drop constraint if exists cambio_configuracion_entidad_check;
alter table rma.cambio_configuracion add constraint cambio_configuracion_entidad_check
  check (entidad in (
    'TIPO_REPARACION', 'MESA_TRABAJO', 'USUARIO', 'PERMISO', 'INSUMO',
    'MOTIVO', 'PLANTILLA', 'PARAMETRO', 'CHECKLIST', 'PROVEEDOR'
  ));

comment on column rma.cambio_configuracion.entidad is
  'Catálogo cambiado: TIPO_REPARACION, MESA_TRABAJO, USUARIO (roles), PERMISO, INSUMO, MOTIVO, PLANTILLA, PARAMETRO, CHECKLIST o PROVEEDOR.';
comment on column rma.evento_negocio.rol_codigo is
  'Rol con el que actuó el usuario: el primero de sus roles que habilitó la acción (DC27A). Vacío en los eventos anteriores y en los del sistema.';
