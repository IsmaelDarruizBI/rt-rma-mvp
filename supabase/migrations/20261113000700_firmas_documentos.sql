-- Firma opcional de los documentos emitidos (macroiteración integral,
-- DEC-MI-06; cierra ABI-08).
--
-- Aditiva: `firma_documento` guarda la evidencia de una firma —en pantalla
-- o foto del documento firmado— ligada al documento emitido. Ningún
-- documento la exige. La imagen vive en el almacenamiento privado de las
-- fotos; acá solo sus datos. Inmutable y fuera de la Orden: se puede
-- registrar también después de la entrega, sin modificar la Orden cerrada.

create table if not exists rma.firma_documento (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  documento_id uuid not null references rma.documento_emitido (id),
  forma text not null check (forma in ('PANTALLA', 'FOTO_DOCUMENTO')),
  objeto_clave text not null unique,
  tipo_contenido text not null check (tipo_contenido like 'image/%'),
  tamano_bytes integer not null check (tamano_bytes > 0),
  firmante text,
  usuario_id uuid not null references rma.usuario (id),
  registrada_en timestamptz not null
);

create index if not exists firma_documento_documento
  on rma.firma_documento (documento_id, registrada_en);

drop trigger if exists firma_documento_inmutable on rma.firma_documento;
create trigger firma_documento_inmutable before update or delete on rma.firma_documento
  for each row execute function rma.impedir_modificacion();

comment on table rma.firma_documento is
  'Firma opcional de un documento emitido (DEC-MI-06, BR-REP-042): en pantalla o foto del documento firmado. Inmutable; no modifica la Orden.';
comment on column rma.firma_documento.id is 'Identificador interno de la firma.';
comment on column rma.firma_documento.codigo is 'Código público de la firma (FIR-...).';
comment on column rma.firma_documento.documento_id is 'Documento firmado (referencia a documento_emitido).';
comment on column rma.firma_documento.forma is 'PANTALLA (trazo en el dispositivo) o FOTO_DOCUMENTO (foto del papel firmado).';
comment on column rma.firma_documento.objeto_clave is 'Clave de la imagen en el almacenamiento privado.';
comment on column rma.firma_documento.tipo_contenido is 'Tipo de la imagen (verificado por su contenido).';
comment on column rma.firma_documento.tamano_bytes is 'Tamaño de la imagen.';
comment on column rma.firma_documento.firmante is 'Nombre de quien firmó, si se indicó.';
comment on column rma.firma_documento.usuario_id is 'Quién registró la firma (referencia a usuario).';
comment on column rma.firma_documento.registrada_en is 'Fecha y hora del registro.';

grant select, insert on rma.firma_documento to rma_backend;
