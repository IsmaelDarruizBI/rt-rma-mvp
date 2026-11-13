-- Comunicaciones asistidas por WhatsApp y consentimiento (macroiteración
-- integral, DEC-MI-08; cierra ABI-31 y la etapa 1 de ABI-13).
--
-- Aditiva:
--   * `plantilla_mensaje`: plantillas de WhatsApp administradas por
--     Administración, con las cinco iniciales (todas operativas). Cada
--     cambio queda en cambio_configuracion (entidad PLANTILLA);
--   * `comunicacion_cliente`: cada intento de envío asistido (se abrió
--     WhatsApp con el mensaje preparado). Inmutable;
--   * `comunicacion_confirmacion`: la confirmación manual del usuario (se
--     envió o no), una por intento e inmutable. Nunca hay «entregado» ni
--     «leído»: no hay un proveedor que lo pruebe;
--   * `consentimiento_comunicacion`: historial de consentimiento por
--     cliente, finalidad y canal. Revocar agrega un registro; nada se borra.

create table if not exists rma.plantilla_mensaje (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique check (codigo ~ '^[A-Z0-9][A-Z0-9_-]*$'),
  nombre text not null check (btrim(nombre) <> ''),
  finalidad text not null check (finalidad in ('OPERATIVA', 'COMERCIAL')),
  texto text not null check (btrim(texto) <> ''),
  activa boolean not null default true,
  orden integer not null default 0,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now()
);

comment on table rma.plantilla_mensaje is
  'Plantillas de WhatsApp (DEC-MI-08, BR-REP-044). No se borran: se desactivan. Cada mensaje registrado guarda el texto que se preparó.';
comment on column rma.plantilla_mensaje.id is 'Identificador interno de la plantilla.';
comment on column rma.plantilla_mensaje.codigo is 'Código público de la plantilla.';
comment on column rma.plantilla_mensaje.nombre is 'Nombre visible de la plantilla.';
comment on column rma.plantilla_mensaje.finalidad is 'OPERATIVA (avisos de la Orden) o COMERCIAL (exige consentimiento expreso).';
comment on column rma.plantilla_mensaje.texto is 'Texto con variables de la Orden entre llaves.';
comment on column rma.plantilla_mensaje.activa is 'Si se ofrece para mensajes nuevos.';
comment on column rma.plantilla_mensaje.orden is 'Orden de presentación.';
comment on column rma.plantilla_mensaje.creado_en is 'Fecha y hora de alta.';
comment on column rma.plantilla_mensaje.modificado_en is 'Fecha y hora del último cambio.';

insert into rma.plantilla_mensaje (codigo, nombre, finalidad, texto, orden) values
  ('INGRESO', 'Ingreso de equipo', 'OPERATIVA',
   'Hola {cliente}! Recibimos tu {equipo} con la orden {orden}. Te avisamos por este medio cuando haya novedades. {empresa}', 1),
  ('AUTORIZACION_PENDIENTE', 'Autorizacion pendiente', 'OPERATIVA',
   'Hola {cliente}! Para seguir con la orden {orden} ({equipo}) necesitamos tu autorizacion. Total: {total}. {empresa}', 2),
  ('LISTO_PARA_RETIRAR', 'Equipo listo para retirar', 'OPERATIVA',
   'Hola {cliente}! Tu {equipo} (orden {orden}) esta listo para retirar. Saldo pendiente: {saldo}. {empresa}', 3),
  ('RECORDATORIO_RETIRO', 'Recordatorio de retiro', 'OPERATIVA',
   'Hola {cliente}! Te recordamos que tu {equipo} (orden {orden}) te espera para retirarlo. Saldo pendiente: {saldo}. {empresa}', 4),
  ('GARANTIA', 'Garantia', 'OPERATIVA',
   'Hola {cliente}! La reparacion de tu {equipo} (orden {orden}) tiene garantia hasta el {garantia_hasta}. {empresa}', 5)
on conflict (codigo) do nothing;

create table if not exists rma.comunicacion_cliente (
  id uuid primary key default gen_random_uuid(),
  orden_id uuid not null references rma.orden (id),
  codigo text not null check (codigo ~ '^COM-[0-9]{3,}$'),
  plantilla_codigo text,
  finalidad text not null check (finalidad in ('OPERATIVA', 'COMERCIAL')),
  canal text not null check (canal in ('WHATSAPP')),
  destinatario text,
  mensaje text not null check (btrim(mensaje) <> ''),
  usuario_id uuid not null references rma.usuario (id),
  registrado_en timestamptz not null,
  posicion integer not null check (posicion >= 1),
  constraint comunicacion_cliente_codigo unique (orden_id, codigo),
  constraint comunicacion_cliente_posicion unique (orden_id, posicion)
);

drop trigger if exists comunicacion_cliente_inmutable on rma.comunicacion_cliente;
create trigger comunicacion_cliente_inmutable before update or delete on rma.comunicacion_cliente
  for each row execute function rma.impedir_modificacion();

comment on table rma.comunicacion_cliente is
  'Intentos de envío asistido por WhatsApp (DEC-MI-08): se abrió WhatsApp con el mensaje preparado. Abrir no es enviar. Inmutables.';
comment on column rma.comunicacion_cliente.id is 'Identificador interno del intento.';
comment on column rma.comunicacion_cliente.orden_id is 'Orden a la que se refiere el mensaje (referencia a orden).';
comment on column rma.comunicacion_cliente.codigo is 'Código del intento en la Orden (COM-001...).';
comment on column rma.comunicacion_cliente.plantilla_codigo is 'Plantilla usada (su código), si el mensaje salió de una.';
comment on column rma.comunicacion_cliente.finalidad is 'OPERATIVA o COMERCIAL, la de la plantilla.';
comment on column rma.comunicacion_cliente.canal is 'Canal: WHATSAPP (etapa 1, sin proveedor).';
comment on column rma.comunicacion_cliente.destinatario is 'Teléfono al que se abrió WhatsApp.';
comment on column rma.comunicacion_cliente.mensaje is 'Mensaje preparado, revisado y quizá editado por el usuario.';
comment on column rma.comunicacion_cliente.usuario_id is 'Quién lo preparó (referencia a usuario).';
comment on column rma.comunicacion_cliente.registrado_en is 'Fecha y hora del intento de apertura.';
comment on column rma.comunicacion_cliente.posicion is 'Orden del intento en la Orden.';

create table if not exists rma.comunicacion_confirmacion (
  comunicacion_id uuid primary key references rma.comunicacion_cliente (id),
  enviado boolean not null,
  nota text,
  usuario_id uuid not null references rma.usuario (id),
  confirmado_en timestamptz not null
);

drop trigger if exists comunicacion_confirmacion_inmutable on rma.comunicacion_confirmacion;
create trigger comunicacion_confirmacion_inmutable before update or delete on rma.comunicacion_confirmacion
  for each row execute function rma.impedir_modificacion();

comment on table rma.comunicacion_confirmacion is
  'Confirmación manual de un intento (DEC-MI-08): el usuario indica si lo envió o no. Una por intento, inmutable. Nunca entregado ni leído.';
comment on column rma.comunicacion_confirmacion.comunicacion_id is 'Intento confirmado (referencia a comunicacion_cliente).';
comment on column rma.comunicacion_confirmacion.enviado is 'Si el usuario confirmó que lo envió.';
comment on column rma.comunicacion_confirmacion.nota is 'Aclaración opcional.';
comment on column rma.comunicacion_confirmacion.usuario_id is 'Quién confirmó (referencia a usuario).';
comment on column rma.comunicacion_confirmacion.confirmado_en is 'Fecha y hora de la confirmación.';

create table if not exists rma.consentimiento_comunicacion (
  id uuid primary key default gen_random_uuid(),
  cliente_id uuid not null references rma.cliente (id),
  finalidad text not null check (finalidad in ('OPERATIVA', 'COMERCIAL')),
  canal text not null check (canal in ('WHATSAPP')),
  otorgado boolean not null,
  origen text not null check (btrim(origen) <> ''),
  usuario_id uuid not null references rma.usuario (id),
  registrado_en timestamptz not null
);

create index if not exists consentimiento_comunicacion_cliente
  on rma.consentimiento_comunicacion (cliente_id, registrado_en);

drop trigger if exists consentimiento_comunicacion_inmutable on rma.consentimiento_comunicacion;
create trigger consentimiento_comunicacion_inmutable before update or delete on rma.consentimiento_comunicacion
  for each row execute function rma.impedir_modificacion();

comment on table rma.consentimiento_comunicacion is
  'Historial de consentimiento de comunicación (DEC-MI-08, BR-REP-043). Rige el último registro por cliente, finalidad y canal. Lo comercial exige un consentimiento expreso. Inmutable.';
comment on column rma.consentimiento_comunicacion.id is 'Identificador interno del registro.';
comment on column rma.consentimiento_comunicacion.cliente_id is 'Cliente (referencia a cliente).';
comment on column rma.consentimiento_comunicacion.finalidad is 'OPERATIVA o COMERCIAL.';
comment on column rma.consentimiento_comunicacion.canal is 'Canal al que se refiere: WHATSAPP.';
comment on column rma.consentimiento_comunicacion.otorgado is 'true: otorga; false: rechaza o revoca.';
comment on column rma.consentimiento_comunicacion.origen is 'Cómo se obtuvo (por ejemplo, firmado en el mostrador).';
comment on column rma.consentimiento_comunicacion.usuario_id is 'Quién lo registró (referencia a usuario).';
comment on column rma.consentimiento_comunicacion.registrado_en is 'Fecha y hora del registro.';

grant select, insert, update on rma.plantilla_mensaje to rma_backend;
grant select, insert on rma.comunicacion_cliente to rma_backend;
grant select, insert on rma.comunicacion_confirmacion to rma_backend;
grant select, insert on rma.consentimiento_comunicacion to rma_backend;
