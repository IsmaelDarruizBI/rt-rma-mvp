-- Rosario Tecno RMA — Esquema físico PostgreSQL
-- 0200. M6 Usuarios, permisos y configuración.
--
-- Convenciones de todo el esquema:
--   * id: identificador interno opaco (uuid), usado por todas las relaciones (G-1).
--   * codigo: identificador público legible, el mismo que usa hoy la API (G-1).
--   * Los catálogos no se borran: se desactivan con «activo».
--   * Estados y tipos son texto con CHECK, para poder ampliarlos con una migración simple.

-- ---------------------------------------------------------------------------
-- rol
-- ---------------------------------------------------------------------------
create table rma.rol (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique
    check (codigo in ('RECEPCION', 'TECNICO', 'COORDINADOR_RMA', 'ADMINISTRADOR')),
  nombre text not null
);

comment on table rma.rol is
  'Roles operativos de RMA. Los permisos de cada rol están fijos en el código de FastAPI; los permisos configurables son una función futura (DC08).';
comment on column rma.rol.id is 'Identificador interno del rol.';
comment on column rma.rol.codigo is 'Código del rol: RECEPCION, TECNICO, COORDINADOR_RMA o ADMINISTRADOR, el mismo que usa la API.';
comment on column rma.rol.nombre is 'Nombre del rol tal como se muestra a las personas.';

-- ---------------------------------------------------------------------------
-- usuario
-- ---------------------------------------------------------------------------
create table rma.usuario (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  auth_user_id uuid unique,
  nombre text not null check (btrim(nombre) <> ''),
  email text,
  activo boolean not null default true,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now()
);

create unique index usuario_email_unico on rma.usuario (lower(email)) where email is not null;

create trigger usuario_modificacion before update on rma.usuario
  for each row execute function rma.marcar_modificacion();
create trigger usuario_sin_borrado before delete on rma.usuario
  for each row execute function rma.impedir_borrado();

comment on table rma.usuario is
  'Personas que operan RMA. La autenticación la hace Supabase Auth y la autorización, FastAPI según los roles asignados.';
comment on column rma.usuario.id is 'Identificador interno del usuario.';
comment on column rma.usuario.codigo is 'Identificador público del usuario (por ejemplo RECEP-001), el que registran los eventos y documentos de la API actual.';
comment on column rma.usuario.auth_user_id is 'Identidad del usuario en Supabase Auth; vacío mientras no tenga acceso con inicio de sesión real. No tiene clave foránea para que el esquema no dependa del esquema auth.';
comment on column rma.usuario.nombre is 'Nombre de la persona tal como aparece en pantallas y documentos.';
comment on column rma.usuario.email is 'Correo de la persona; único sin distinguir mayúsculas cuando está cargado.';
comment on column rma.usuario.activo is 'Si el usuario puede operar. Un usuario inactivo se conserva porque es responsable de registros históricos.';
comment on column rma.usuario.creado_en is 'Fecha y hora de alta del usuario.';
comment on column rma.usuario.modificado_en is 'Fecha y hora de la última modificación de la fila.';

-- ---------------------------------------------------------------------------
-- usuario_rol
-- ---------------------------------------------------------------------------
create table rma.usuario_rol (
  usuario_id uuid not null references rma.usuario (id),
  rol_id uuid not null references rma.rol (id),
  otorgado_en timestamptz not null default now(),
  otorgado_por uuid references rma.usuario (id),
  primary key (usuario_id, rol_id)
);

create index usuario_rol_rol on rma.usuario_rol (rol_id);

comment on table rma.usuario_rol is
  'Roles asignados a cada usuario. Los permisos efectivos son la unión de sus roles. Retirar un rol es borrar su fila; los eventos conservan el rol con que se actuó.';
comment on column rma.usuario_rol.usuario_id is 'Usuario que recibe el rol (referencia a usuario).';
comment on column rma.usuario_rol.rol_id is 'Rol asignado (referencia a rol).';
comment on column rma.usuario_rol.otorgado_en is 'Fecha y hora en que se asignó el rol.';
comment on column rma.usuario_rol.otorgado_por is 'Usuario que asignó el rol (referencia a usuario); vacío en la carga inicial.';

-- ---------------------------------------------------------------------------
-- mesa_trabajo
-- ---------------------------------------------------------------------------
create table rma.mesa_trabajo (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  nombre text not null check (btrim(nombre) <> ''),
  activa boolean not null default true,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now()
);

create trigger mesa_trabajo_modificacion before update on rma.mesa_trabajo
  for each row execute function rma.marcar_modificacion();
create trigger mesa_trabajo_sin_borrado before delete on rma.mesa_trabajo
  for each row execute function rma.impedir_borrado();

comment on table rma.mesa_trabajo is
  'Mesas de trabajo (estaciones) desde las que los técnicos toman Órdenes.';
comment on column rma.mesa_trabajo.id is 'Identificador interno de la Mesa.';
comment on column rma.mesa_trabajo.codigo is 'Identificador público de la Mesa (por ejemplo EST-001).';
comment on column rma.mesa_trabajo.nombre is 'Nombre de la Mesa tal como lo ven los técnicos.';
comment on column rma.mesa_trabajo.activa is 'Si la Mesa puede usarse para tomar Órdenes.';
comment on column rma.mesa_trabajo.creado_en is 'Fecha y hora de alta de la Mesa.';
comment on column rma.mesa_trabajo.modificado_en is 'Fecha y hora de la última modificación de la fila.';

-- ---------------------------------------------------------------------------
-- tipo_reparacion
-- ---------------------------------------------------------------------------
create table rma.tipo_reparacion (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  nombre text not null check (btrim(nombre) <> ''),
  precio numeric(14, 2) not null check (precio >= 0),
  puntaje integer not null check (puntaje >= 0),
  garantia_dias integer not null check (garantia_dias >= 0),
  activo boolean not null default true,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now()
);

create trigger tipo_reparacion_modificacion before update on rma.tipo_reparacion
  for each row execute function rma.marcar_modificacion();
create trigger tipo_reparacion_sin_borrado before delete on rma.tipo_reparacion
  for each row execute function rma.impedir_borrado();

comment on table rma.tipo_reparacion is
  'Catálogo de reparaciones con su precio, puntaje y garantía vigentes. Cambiarlo no altera las definiciones ya registradas, que guardan su propia copia. El código TR-OTROS está reservado para la reparación no tipificada «Otros».';
comment on column rma.tipo_reparacion.id is 'Identificador interno del tipo de reparación.';
comment on column rma.tipo_reparacion.codigo is 'Identificador público del tipo (por ejemplo TR-001); TR-OTROS es la reparación no tipificada, con descripción y precio manual.';
comment on column rma.tipo_reparacion.nombre is 'Nombre de la reparación tal como aparece en pantallas y comprobantes.';
comment on column rma.tipo_reparacion.precio is 'Precio vigente en pesos, con dos decimales. Se copia en cada versión de definición al usarlo.';
comment on column rma.tipo_reparacion.puntaje is 'Puntaje informativo que acredita la reparación aprobada; no se usa para liquidaciones.';
comment on column rma.tipo_reparacion.garantia_dias is 'Plazo de garantía de catálogo, en días corridos desde la entrega.';
comment on column rma.tipo_reparacion.activo is 'Si el tipo puede elegirse para Detalles nuevos.';
comment on column rma.tipo_reparacion.creado_en is 'Fecha y hora de alta del tipo.';
comment on column rma.tipo_reparacion.modificado_en is 'Fecha y hora de la última modificación de la fila.';

-- ---------------------------------------------------------------------------
-- mesa_tipo_reparacion
-- ---------------------------------------------------------------------------
create table rma.mesa_tipo_reparacion (
  mesa_trabajo_id uuid not null references rma.mesa_trabajo (id),
  tipo_reparacion_id uuid not null references rma.tipo_reparacion (id),
  primary key (mesa_trabajo_id, tipo_reparacion_id)
);

create index mesa_tipo_reparacion_tipo on rma.mesa_tipo_reparacion (tipo_reparacion_id);

comment on table rma.mesa_tipo_reparacion is
  'Qué tipos de reparación puede trabajar cada Mesa. La reparación «Otros» no restringe Mesas y no necesita filas aquí.';
comment on column rma.mesa_tipo_reparacion.mesa_trabajo_id is 'Mesa habilitada (referencia a mesa_trabajo).';
comment on column rma.mesa_tipo_reparacion.tipo_reparacion_id is 'Tipo de reparación que la Mesa puede trabajar (referencia a tipo_reparacion).';

-- ---------------------------------------------------------------------------
-- medio_pago
-- ---------------------------------------------------------------------------
create table rma.medio_pago (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  nombre text not null check (btrim(nombre) <> ''),
  activo boolean not null default true,
  admite_devolucion boolean not null default true,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now()
);

create trigger medio_pago_modificacion before update on rma.medio_pago
  for each row execute function rma.marcar_modificacion();
create trigger medio_pago_sin_borrado before delete on rma.medio_pago
  for each row execute function rma.impedir_borrado();

comment on table rma.medio_pago is
  'Medios con que se cobra o se devuelve dinero al cliente.';
comment on column rma.medio_pago.id is 'Identificador interno del medio de pago.';
comment on column rma.medio_pago.codigo is 'Identificador público del medio (por ejemplo EFECTIVO o TRANSFERENCIA).';
comment on column rma.medio_pago.nombre is 'Nombre del medio tal como se muestra.';
comment on column rma.medio_pago.activo is 'Si el medio puede usarse en cobros y devoluciones nuevos.';
comment on column rma.medio_pago.admite_devolucion is 'Si el medio puede usarse para devolver dinero al cliente.';
comment on column rma.medio_pago.creado_en is 'Fecha y hora de alta del medio.';
comment on column rma.medio_pago.modificado_en is 'Fecha y hora de la última modificación de la fila.';

-- ---------------------------------------------------------------------------
-- tipo_documento
-- ---------------------------------------------------------------------------
create table rma.tipo_documento (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  nombre text not null check (btrim(nombre) <> ''),
  aplica_a text not null check (aplica_a in ('FISICA', 'JURIDICA', 'AMBAS')),
  regla_normalizacion text not null,
  exige_unicidad boolean not null default true,
  activo boolean not null default true,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now(),
  unique (id, exige_unicidad)
);

create trigger tipo_documento_modificacion before update on rma.tipo_documento
  for each row execute function rma.marcar_modificacion();
create trigger tipo_documento_sin_borrado before delete on rma.tipo_documento
  for each row execute function rma.impedir_borrado();

comment on table rma.tipo_documento is
  'Tipos de documento de identidad admitidos para los Clientes (ABI-24). La lista inicial más allá del DNI es una decisión de negocio pendiente.';
comment on column rma.tipo_documento.id is 'Identificador interno del tipo de documento.';
comment on column rma.tipo_documento.codigo is 'Código del tipo de documento (por ejemplo DNI).';
comment on column rma.tipo_documento.nombre is 'Nombre del tipo de documento tal como se muestra.';
comment on column rma.tipo_documento.aplica_a is 'A qué personas aplica: FISICA, JURIDICA o AMBAS.';
comment on column rma.tipo_documento.regla_normalizacion is 'Regla que aplica FastAPI para normalizar el número; DNI_AR deja solo dígitos, exige 7 u 8 y quita ceros a la izquierda.';
comment on column rma.tipo_documento.exige_unicidad is 'Si un número normalizado de este tipo no puede pertenecer a dos Clientes distintos.';
comment on column rma.tipo_documento.activo is 'Si el tipo puede usarse en documentos nuevos.';
comment on column rma.tipo_documento.creado_en is 'Fecha y hora de alta del tipo.';
comment on column rma.tipo_documento.modificado_en is 'Fecha y hora de la última modificación de la fila.';

-- ---------------------------------------------------------------------------
-- motivo_ajuste
-- ---------------------------------------------------------------------------
create table rma.motivo_ajuste (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  descripcion text not null check (btrim(descripcion) <> ''),
  aplica_a text not null check (aplica_a in ('POSITIVO', 'NEGATIVO', 'AMBOS')),
  activo boolean not null default true,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now()
);

create trigger motivo_ajuste_modificacion before update on rma.motivo_ajuste
  for each row execute function rma.marcar_modificacion();
create trigger motivo_ajuste_sin_borrado before delete on rma.motivo_ajuste
  for each row execute function rma.impedir_borrado();

comment on table rma.motivo_ajuste is
  'Motivos parametrizables de los ajustes manuales de stock (ABI-22). Un motivo dado de baja se conserva en los movimientos que lo usaron.';
comment on column rma.motivo_ajuste.id is 'Identificador interno del motivo.';
comment on column rma.motivo_ajuste.codigo is 'Código del motivo (por ejemplo RECUENTO o DANIO).';
comment on column rma.motivo_ajuste.descripcion is 'Descripción del motivo tal como se muestra al registrar un ajuste.';
comment on column rma.motivo_ajuste.aplica_a is 'A qué ajustes aplica: POSITIVO, NEGATIVO o AMBOS.';
comment on column rma.motivo_ajuste.activo is 'Si el motivo puede elegirse en ajustes nuevos.';
comment on column rma.motivo_ajuste.creado_en is 'Fecha y hora de alta del motivo.';
comment on column rma.motivo_ajuste.modificado_en is 'Fecha y hora de la última modificación de la fila.';

-- ---------------------------------------------------------------------------
-- empresa
-- ---------------------------------------------------------------------------
create table rma.empresa (
  id boolean primary key default true check (id),
  nombre text not null check (btrim(nombre) <> ''),
  razon_social text,
  cuit text,
  direccion text,
  telefono text,
  email text,
  condiciones_garantia text,
  modificado_en timestamptz not null default now()
);

create trigger empresa_modificacion before update on rma.empresa
  for each row execute function rma.marcar_modificacion();
create trigger empresa_sin_borrado before delete on rma.empresa
  for each row execute function rma.impedir_borrado();

comment on table rma.empresa is
  'Datos de Rosario Tecno que salen en los comprobantes. Tiene una sola fila; cambiarla no altera los documentos ya emitidos, que guardan su copia.';
comment on column rma.empresa.id is 'Clave fija que garantiza una única fila.';
comment on column rma.empresa.nombre is 'Nombre comercial de la empresa.';
comment on column rma.empresa.razon_social is 'Razón social de la empresa.';
comment on column rma.empresa.cuit is 'CUIT de la empresa, tal como sale en los comprobantes.';
comment on column rma.empresa.direccion is 'Dirección del local.';
comment on column rma.empresa.telefono is 'Teléfono de contacto del local.';
comment on column rma.empresa.email is 'Correo de contacto del local.';
comment on column rma.empresa.condiciones_garantia is 'Texto de condiciones de garantía que acompaña al certificado de garantía.';
comment on column rma.empresa.modificado_en is 'Fecha y hora de la última modificación de la fila.';

-- ---------------------------------------------------------------------------
-- texto_legal
-- ---------------------------------------------------------------------------
create table rma.texto_legal (
  id uuid primary key default gen_random_uuid(),
  tipo text not null check (tipo in ('TERMINOS_CONDICIONES_ENTREGA')),
  version integer not null check (version >= 1),
  titulo text not null,
  contenido jsonb not null check (jsonb_typeof(contenido) = 'object'),
  vigente_desde timestamptz not null default now(),
  publicado_por uuid references rma.usuario (id),
  creado_en timestamptz not null default now(),
  unique (tipo, version)
);

create trigger texto_legal_inmutable before update or delete on rma.texto_legal
  for each row execute function rma.impedir_modificacion();

comment on table rma.texto_legal is
  'Versiones inmutables de los textos legales que acompañan a los documentos, como los Términos y Condiciones del comprobante de entrega (G-8). Rige la de mayor versión ya vigente; un documento emitido apunta a la versión que usó.';
comment on column rma.texto_legal.id is 'Identificador interno de la versión del texto.';
comment on column rma.texto_legal.tipo is 'Qué texto es: TERMINOS_CONDICIONES_ENTREGA, impreso en el comprobante de entrega de una reparación terminada.';
comment on column rma.texto_legal.version is 'Número de versión del texto, desde 1; cada corrección crea una versión nueva.';
comment on column rma.texto_legal.titulo is 'Título del texto tal como se imprime.';
comment on column rma.texto_legal.contenido is 'Contenido completo del texto en el momento de su publicación: encabezado, apartados en orden con sus líneas, apartados destacados y pie.';
comment on column rma.texto_legal.vigente_desde is 'Desde cuándo rige esta versión para los documentos que se emitan.';
comment on column rma.texto_legal.publicado_por is 'Usuario que publicó la versión (referencia a usuario); vacío en la carga inicial.';
comment on column rma.texto_legal.creado_en is 'Fecha y hora en que se registró la versión.';
