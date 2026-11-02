-- Rosario Tecno RMA — Esquema físico PostgreSQL
-- 0500. M1 Clientes y equipos.

-- ---------------------------------------------------------------------------
-- cliente
-- ---------------------------------------------------------------------------
create table rma.cliente (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  tipo_persona text not null default 'FISICA' check (tipo_persona in ('FISICA', 'JURIDICA')),
  nombre text not null check (btrim(nombre) <> ''),
  telefono text,
  email text,
  clasificacion text check (clasificacion in ('MINORISTA', 'MAYORISTA')),
  creado_por uuid references rma.usuario (id),
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now()
);

create index cliente_telefono on rma.cliente (telefono) where telefono is not null;
create index cliente_nombre on rma.cliente (lower(nombre));

create trigger cliente_modificacion before update on rma.cliente
  for each row execute function rma.marcar_modificacion();
create trigger cliente_sin_borrado before delete on rma.cliente
  for each row execute function rma.impedir_borrado();

comment on table rma.cliente is
  'Personas físicas o jurídicas que dejan equipos de cliente externo o de garantía RMA (ABI-24). El ID es la identidad; un documento nunca lo es. Las correcciones se registran como eventos y no hay fusión de Clientes en esta etapa.';
comment on column rma.cliente.id is 'Identificador interno del Cliente.';
comment on column rma.cliente.codigo is 'Identificador público del Cliente, el que hoy conserva la API entre Órdenes.';
comment on column rma.cliente.tipo_persona is 'FISICA o JURIDICA.';
comment on column rma.cliente.nombre is 'Nombre y apellido de una persona física, o razón social de una jurídica, en un único campo.';
comment on column rma.cliente.telefono is 'Teléfono de contacto vigente; también se usa para advertir posibles duplicados sin documento.';
comment on column rma.cliente.email is 'Correo de contacto vigente.';
comment on column rma.cliente.clasificacion is 'Clasificación MINORISTA o MAYORISTA prevista por DC19; sin uso en esta etapa y sin efecto sobre precios.';
comment on column rma.cliente.creado_por is 'Usuario que dio de alta al Cliente (referencia a usuario).';
comment on column rma.cliente.creado_en is 'Fecha y hora de alta del Cliente.';
comment on column rma.cliente.modificado_en is 'Fecha y hora de la última modificación de sus datos vigentes.';

-- ---------------------------------------------------------------------------
-- documento_cliente
-- ---------------------------------------------------------------------------
create table rma.documento_cliente (
  id uuid primary key default gen_random_uuid(),
  cliente_id uuid not null references rma.cliente (id),
  tipo_documento_id uuid not null,
  exige_unicidad boolean not null,
  numero_ingresado text not null check (btrim(numero_ingresado) <> ''),
  numero_normalizado text not null check (btrim(numero_normalizado) <> ''),
  registrado_por uuid references rma.usuario (id),
  registrado_en timestamptz not null default now(),
  vigente_hasta timestamptz,
  reemplazado_por_id uuid references rma.documento_cliente (id),
  constraint documento_tipo foreign key (tipo_documento_id, exige_unicidad)
    references rma.tipo_documento (id, exige_unicidad) on update cascade,
  constraint documento_reemplazo_coherente check (
    reemplazado_por_id is null or vigente_hasta is not null
  ),
  constraint documento_vigencia_ordenada check (
    vigente_hasta is null or vigente_hasta >= registrado_en
  )
);

-- Como máximo un documento vigente por Cliente y tipo.
create unique index documento_cliente_vigente_por_tipo
  on rma.documento_cliente (cliente_id, tipo_documento_id)
  where vigente_hasta is null;
-- Un número vigente no pertenece a dos Clientes cuando el tipo exige unicidad.
create unique index documento_cliente_numero_unico
  on rma.documento_cliente (tipo_documento_id, numero_normalizado)
  where vigente_hasta is null and exige_unicidad;
create index documento_cliente_busqueda on rma.documento_cliente (numero_normalizado);

create or replace function rma.documento_cliente_solo_cierre()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Los documentos de un Cliente no se borran: se reemplazan.'
      using errcode = 'restrict_violation';
  end if;
  -- Solo se permite cerrar la vigencia una vez; el resto del registro es inmutable.
  -- exige_unicidad puede cambiar en cascada si cambia la regla de su tipo.
  if (old.vigente_hasta is not null
        and (new.vigente_hasta is distinct from old.vigente_hasta
             or new.reemplazado_por_id is distinct from old.reemplazado_por_id))
     or new.cliente_id is distinct from old.cliente_id
     or new.tipo_documento_id is distinct from old.tipo_documento_id
     or new.numero_ingresado is distinct from old.numero_ingresado
     or new.numero_normalizado is distinct from old.numero_normalizado
     or new.registrado_por is distinct from old.registrado_por
     or new.registrado_en is distinct from old.registrado_en then
    raise exception 'Un documento de Cliente solo admite cerrar su vigencia una vez; una corrección es un documento nuevo.'
      using errcode = 'restrict_violation';
  end if;
  return new;
end;
$$;

comment on function rma.documento_cliente_solo_cierre() is
  'Permite únicamente cerrar la vigencia de un documento de Cliente (al reemplazarlo); impide cualquier otro cambio o el borrado.';

create trigger documento_cliente_solo_cierre before update or delete on rma.documento_cliente
  for each row execute function rma.documento_cliente_solo_cierre();

comment on table rma.documento_cliente is
  'Documentos de identidad de cada Cliente, con su historia de correcciones. Son opcionales; puede haber varios vigentes, uno por tipo.';
comment on column rma.documento_cliente.id is 'Identificador interno del documento.';
comment on column rma.documento_cliente.cliente_id is 'Cliente al que pertenece (referencia a cliente).';
comment on column rma.documento_cliente.tipo_documento_id is 'Tipo de documento (referencia a tipo_documento).';
comment on column rma.documento_cliente.exige_unicidad is 'Copia de la regla de unicidad del tipo, mantenida por la clave foránea, para poder aplicar la restricción de número único.';
comment on column rma.documento_cliente.numero_ingresado is 'Número tal como lo cargó Recepción, con puntos, espacios o guiones.';
comment on column rma.documento_cliente.numero_normalizado is 'Número normalizado según la regla del tipo; es el que se compara para buscar y para la unicidad.';
comment on column rma.documento_cliente.registrado_por is 'Usuario que registró el documento (referencia a usuario).';
comment on column rma.documento_cliente.registrado_en is 'Fecha y hora en que se registró el documento.';
comment on column rma.documento_cliente.vigente_hasta is 'Fecha y hora en que dejó de estar vigente por una corrección; vacía mientras está vigente.';
comment on column rma.documento_cliente.reemplazado_por_id is 'Documento que lo reemplazó en una corrección (referencia a documento_cliente); vacío si sigue vigente o se dio de baja sin reemplazo.';

-- ---------------------------------------------------------------------------
-- modelo_equipo
-- ---------------------------------------------------------------------------
create table rma.modelo_equipo (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique check (codigo ~ '^MOD-[0-9]{4,}$'),
  marca text not null check (btrim(marca) <> ''),
  modelo text not null check (btrim(modelo) <> ''),
  variante text,
  numeros_modelo text[] not null default '{}',
  activo boolean not null default true,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now(),
  constraint modelo_equipo_unico unique nulls not distinct (marca, modelo, variante)
);

create trigger modelo_equipo_modificacion before update on rma.modelo_equipo
  for each row execute function rma.marcar_modificacion();
create trigger modelo_equipo_sin_borrado before delete on rma.modelo_equipo
  for each row execute function rma.impedir_borrado();

comment on table rma.modelo_equipo is
  'Catálogo técnico propio de RMA: qué equipo es (marca, modelo comercial y variante). No depende del catálogo comercial de Ventas; un modelo no se borra, se desactiva.';
comment on column rma.modelo_equipo.id is 'Identificador interno del modelo.';
comment on column rma.modelo_equipo.codigo is 'Identificador público estable del modelo, con formato MOD-0001.';
comment on column rma.modelo_equipo.marca is 'Marca del equipo, por ejemplo Apple.';
comment on column rma.modelo_equipo.modelo is 'Modelo comercial, por ejemplo iPhone 15.';
comment on column rma.modelo_equipo.variante is 'Variante del modelo, por ejemplo Pro Max; vacía en la versión estándar.';
comment on column rma.modelo_equipo.numeros_modelo is 'Números de modelo del fabricante (por ejemplo A2849), cargados solo con información verificada (P-02); lista vacía mientras no haya.';
comment on column rma.modelo_equipo.activo is 'Si el modelo se ofrece en el buscador al ingresar o corregir un equipo.';
comment on column rma.modelo_equipo.creado_en is 'Fecha y hora de alta del modelo.';
comment on column rma.modelo_equipo.modificado_en is 'Fecha y hora de la última modificación de la fila.';

-- ---------------------------------------------------------------------------
-- equipo
-- ---------------------------------------------------------------------------
create table rma.equipo (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  imei text,
  numero_serie text,
  modelo_equipo_id uuid references rma.modelo_equipo (id),
  capacidad_gb integer check (capacidad_gb > 0),
  capacidad_texto text,
  color text,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now()
);

create index equipo_imei on rma.equipo (imei) where imei is not null;
create index equipo_numero_serie on rma.equipo (numero_serie) where numero_serie is not null;
create index equipo_modelo on rma.equipo (modelo_equipo_id) where modelo_equipo_id is not null;

create trigger equipo_modificacion before update on rma.equipo
  for each row execute function rma.marcar_modificacion();
create trigger equipo_sin_borrado before delete on rma.equipo
  for each row execute function rma.impedir_borrado();

comment on table rma.equipo is
  'La unidad física que se repara. Pertenece a la Orden de ingreso y a las garantías RMA que nacen de ella. Cada ingreso crea su Equipo: no hay reutilización por IMEI en esta etapa (ABI-05).';
comment on column rma.equipo.id is 'Identificador interno del Equipo.';
comment on column rma.equipo.codigo is 'Identificador público del Equipo, el que hoy usa la API.';
comment on column rma.equipo.imei is 'IMEI del equipo, si tiene; no es su identidad.';
comment on column rma.equipo.numero_serie is 'Número de serie del equipo, si tiene.';
comment on column rma.equipo.modelo_equipo_id is 'Modelo técnico elegido del catálogo (referencia a modelo_equipo); vacío si el equipo se cargó a mano.';
comment on column rma.equipo.capacidad_gb is 'Capacidad de almacenamiento normalizada en GB, con 1 TB = 1024 GB; vacía si no se informó o no se pudo convertir.';
comment on column rma.equipo.capacidad_texto is 'Capacidad tal como se cargó originalmente (por ejemplo «256 GB»), conservada para revisar lo que no se pudo convertir.';
comment on column rma.equipo.color is 'Color del equipo físico, si se informó.';
comment on column rma.equipo.creado_en is 'Fecha y hora de alta del Equipo.';
comment on column rma.equipo.modificado_en is 'Fecha y hora de la última modificación de sus datos vigentes.';
