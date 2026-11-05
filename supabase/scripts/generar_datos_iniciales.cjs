// Genera las cargas iniciales de supabase/seeds a partir de las fuentes del MVP.
// Uso (desde la raíz de rt-rma-mvp): node supabase/scripts/generar_datos_iniciales.cjs
//
//   seeds/referencia_operativa/  Datos operativos iniciales válidos para producción:
//                                medios de pago, empresa, Términos y Condiciones v1,
//                                catálogo técnico de modelos y motivos de ajuste propuestos.
//   seeds/desarrollo/            Datos ficticios de prueba (usuarios demo, Mesas, tipos de
//                                reparación, insumos y stock). Nunca se cargan en producción.
const fs = require("fs");
const path = require("path");

const RAIZ = path.resolve(__dirname, "..", "..");
const SEEDS = path.join(RAIZ, "supabase", "seeds");
const q = (s) => (s === null || s === undefined ? "null" : `'${String(s).replace(/'/g, "''")}'`);
const leer = (rel) => JSON.parse(fs.readFileSync(path.join(RAIZ, rel), "utf8"));
const cabecera = (titulo, fuente) =>
  `-- Rosario Tecno RMA — ${titulo}\n-- Generado por supabase/scripts/generar_datos_iniciales.cjs desde ${fuente}.\n-- No editar a mano: regenerar.\n\n`;

function escribir(rel, contenido) {
  const destino = path.join(SEEDS, rel);
  fs.mkdirSync(path.dirname(destino), { recursive: true });
  fs.writeFileSync(destino, contenido);
  console.log("escrito", path.relative(RAIZ, destino));
}

// --- Términos y Condiciones v1, desde el texto vigente del frontend -----------------
function terminosCondiciones() {
  const ts = fs
    .readFileSync(path.join(RAIZ, "app/frontend/src/features/ordenes-reparacion/terminosCondiciones.ts"), "utf8")
    .replace(/\r\n/g, "\n");
  const literal = (nombre) => {
    const inicio = ts.indexOf(`export const ${nombre}`);
    if (inicio < 0) throw new Error(`no se encontró ${nombre}`);
    const igual = ts.indexOf("=", inicio);
    const fin = ts.indexOf(";\n", igual);
    const texto = ts.slice(igual + 1, fin).replace(/\s+as const\s*$/, "");
    return Function(`"use strict"; return (${texto});`)();
  };
  return {
    encabezado: literal("ENCABEZADO_TERMINOS"),
    apartados: literal("APARTADOS_TERMINOS").map((a, i) => ({ numero: i + 1, lineas: a.lineas, destacado: !!a.destacado })),
    pie: literal("PIE_TERMINOS"),
  };
}

// --- Referencia operativa ---------------------------------------------------------
function generarReferenciaOperativa() {
const medios = [
  ["EFECTIVO", "Efectivo"],
  ["TRANSFERENCIA", "Transferencia"],
  ["TARJETA_DEBITO", "Tarjeta de debito"],
  ["TARJETA_CREDITO", "Tarjeta de credito"],
  ["OTRO", "Otro"],
];
escribir(
  "referencia_operativa/01_medios_pago_empresa.sql",
  cabecera("Medios de pago y datos de la empresa", "app/backend/app/domain/models/catalogos.py (valores predeterminados del MVP)") +
    // orden: la posicion en la lista predeterminada (E3, DE3-2).
    `insert into rma.medio_pago (codigo, nombre, orden) values\n${medios.map(([c, n], i) => `  (${q(c)}, ${q(n)}, ${i + 1})`).join(",\n")}\non conflict (codigo) do update set orden = excluded.orden\n  where rma.medio_pago.orden is distinct from excluded.orden;\n\n` +
    `insert into rma.empresa (nombre) values ('Rosario Tecno')\non conflict (id) do nothing;\n`
);

const terminos = terminosCondiciones();
if (terminos.apartados.length !== 19) throw new Error("se esperaban 19 apartados de Términos y Condiciones");
escribir(
  "referencia_operativa/02_terminos_condiciones.sql",
  cabecera("Términos y Condiciones del comprobante de entrega, versión 1", "app/frontend/src/features/ordenes-reparacion/terminosCondiciones.ts") +
    `-- El texto sigue en revisión (P-04, P-05): una corrección es una versión nueva.\n` +
    `insert into rma.texto_legal (tipo, version, titulo, contenido, vigente_desde) values (\n` +
    `  'TERMINOS_CONDICIONES_ENTREGA', 1, ${q(terminos.encabezado.titulo)},\n  ${q(JSON.stringify(terminos))}::jsonb,\n  '2026-10-28T00:00:00-03:00'\n)\non conflict (tipo, version) do nothing;\n`
);

const modelos = leer("app/backend/app/datos/modelos_equipo.json");
escribir(
  "referencia_operativa/03_modelos_equipo.sql",
  cabecera("Catálogo técnico de modelos de equipo", "app/backend/app/datos/modelos_equipo.json") +
    `insert into rma.modelo_equipo (codigo, marca, modelo, variante, numeros_modelo, activo) values\n` +
    modelos
      .map((m) => `  (${q(m.id)}, ${q(m.marca)}, ${q(m.modelo)}, ${q(m.variante)}, ${q(`{${(m.numeros_modelo || []).map((n) => `"${n}"`).join(",")}}`)}::text[], ${!!m.activo})`)
      .join(",\n") +
    `\non conflict (codigo) do nothing;\n`
);

escribir(
  "referencia_operativa/04_motivos_ajuste.sql",
  cabecera("Motivos de ajuste de stock", "la lista aprobada por el responsable de producto el 02/11/2026") +
    `-- Aprobados el 02/11/2026: RECUENTO y ERROR_CARGA para ajustes positivos y negativos; DANIO y PERDIDA solo negativos.\n` +
    `insert into rma.motivo_ajuste (codigo, descripcion, aplica_a) values\n` +
    `  ('RECUENTO', 'Diferencia de recuento físico', 'AMBOS'),\n` +
    `  ('ERROR_CARGA', 'Corrección de un error de carga', 'AMBOS'),\n` +
    `  ('DANIO', 'Insumo dañado en el depósito', 'NEGATIVO'),\n` +
    `  ('PERDIDA', 'Insumo perdido o faltante', 'NEGATIVO')\n` +
    `on conflict (codigo) do nothing;\n`
);
}

// --- Desarrollo (ficticios) ---------------------------------------------------------
const TIPO_OTROS = { id: "TR-OTROS", nombre: "Otros — Reparación no tipificada", precio: "0", puntaje: 0, garantia_dias: 0, activo: true };

// Las referencias se validan antes de generar (QA-E3-5): un id que no existe, un id
// repetido o un id de insumo igual al código de otro detienen la generación con el
// detalle. Ninguna relación se descarta en silencio.
function validarDesarrollo({ usuarios, estaciones, tipos, insumos, tipoInsumos, tipoEstaciones }) {
  const errores = [];
  const vacio = (v) => v === undefined || v === null || String(v).trim() === "";
  const unicos = (lista, campo, nombre) => {
    const vistos = new Set();
    lista.forEach((x, n) => {
      const valor = x[campo];
      if (vacio(valor)) errores.push(`${nombre} ${n + 1}: falta ${campo}`);
      else if (vistos.has(valor)) errores.push(`${nombre} repetido: ${campo} ${valor}`);
      vistos.add(valor);
    });
    return vistos;
  };
  unicos(usuarios, "id", "usuario");
  usuarios.forEach((u) => vacio(u.rol) && errores.push(`usuario ${u.id}: falta el rol`));
  const idsEstaciones = unicos(estaciones, "id", "estación");
  const idsTipos = unicos(tipos, "id", "tipo de reparación");
  const idsInsumos = unicos(insumos, "id", "insumo");
  const codigos = unicos(insumos, "codigo", "insumo");
  // Una fila anterior a E3 tiene clave = código: si el id de un insumo es el código de
  // otro, la clave del dominio chocaría con esa clave provisoria.
  insumos.forEach((i) => {
    if (i.id !== i.codigo && codigos.has(i.id)) errores.push(`insumo ${i.codigo}: su id ${i.id} es el código de otro insumo`);
  });
  const relacion = (lista, nombre, campos) => {
    const vistos = new Set();
    lista.forEach((x, n) => {
      for (const [campo, existentes, que] of campos) {
        if (!existentes.has(x[campo])) errores.push(`${nombre} ${n + 1}: no existe ${que} ${x[campo]}`);
      }
      const par = campos.map(([campo]) => x[campo]).join(" / ");
      if (vistos.has(par)) errores.push(`${nombre} repetido: ${par}`);
      vistos.add(par);
    });
  };
  relacion(tipoInsumos, "insumo previsto", [
    ["tipo_reparacion_id", idsTipos, "el tipo de reparación"],
    ["insumo_id", idsInsumos, "el insumo"],
  ]);
  relacion(tipoEstaciones, "estación de un tipo", [
    ["estacion_id", idsEstaciones, "la estación"],
    ["tipo_reparacion_id", idsTipos, "el tipo de reparación"],
  ]);
  if (errores.length) throw new Error(`Datos de desarrollo inconsistentes:\n- ${errores.join("\n- ")}`);
}

// Verificación al aplicar la carga: si una fila esperada no quedó en la base (por
// ejemplo, una identidad existente que la carga no pisa), falla con el detalle.
function verificacion(titulo, filas, columnas, condicion) {
  if (!filas.length) return "";
  return (
    `  select string_agg(concat_ws(' / ', ${columnas.map((c) => `v.${c}`).join(", ")}), ', ') into v_faltan\n` +
    `  from (values\n${filas.map((f) => `    (${f.join(", ")})`).join(",\n")}\n  ) as v (${columnas.join(", ")})\n` +
    `  where not exists (\n${condicion}\n  );\n` +
    `  if v_faltan is not null then\n    raise exception 'Carga de desarrollo: % sin cargar: %', ${q(titulo)}, v_faltan;\n  end if;\n`
  );
}

function cargaDesarrollo(datos) {
  const { usuarios, estaciones, insumos, tipoInsumos, tipoEstaciones } = datos;
  const tipos = datos.tipos.some((t) => t.id === TIPO_OTROS.id) ? datos.tipos : [...datos.tipos, TIPO_OTROS];
  validarDesarrollo({ ...datos, tipos });
  const codigoDe = new Map(insumos.map((i) => [i.id, i.codigo]));
  return (
    cabecera("DATOS FICTICIOS DE DESARROLLO — nunca cargar en producción", "app/backend/data/catalogs/*.json") +
    `-- Idempotente: volver a cargarlo no duplica ni cambia nada.\n` +
    `-- Aplicarlo entero o nada (psql: -v ON_ERROR_STOP=1 --single-transaction).\n\n` +
    // orden: la posicion en usuarios.json (E3, DE3-2).
    `insert into rma.usuario (codigo, nombre, activo, orden) values\n${usuarios.map((u, i) => `  (${q(u.id)}, ${q(u.nombre)}, ${!!u.activo}, ${i + 1})`).join(",\n")}\non conflict (codigo) do update set orden = excluded.orden\n  where rma.usuario.orden is distinct from excluded.orden;\n\n` +
    `insert into rma.usuario_rol (usuario_id, rol_id)\nselect u.id, r.id from (values\n${usuarios.map((u) => `  (${q(u.id)}, ${q(u.rol)})`).join(",\n")}\n) as v (usuario, rol)\njoin rma.usuario u on u.codigo = v.usuario\njoin rma.rol r on r.codigo = v.rol\non conflict do nothing;\n\n` +
    `insert into rma.mesa_trabajo (codigo, nombre, activa) values\n${estaciones.map((e) => `  (${q(e.id)}, ${q(e.nombre)}, ${!!e.activa})`).join(",\n")}\non conflict (codigo) do nothing;\n\n` +
    `insert into rma.tipo_reparacion (codigo, nombre, precio, puntaje, garantia_dias, activo) values\n${tipos.map((t) => `  (${q(t.id)}, ${q(t.nombre)}, ${t.precio}, ${t.puntaje}, ${t.garantia_dias}, ${!!t.activo})`).join(",\n")}\non conflict (codigo) do nothing;\n\n` +
    `insert into rma.mesa_tipo_reparacion (mesa_trabajo_id, tipo_reparacion_id)\nselect m.id, t.id from (values\n${tipoEstaciones.map((x) => `  (${q(x.estacion_id)}, ${q(x.tipo_reparacion_id)})`).join(",\n")}\n) as v (mesa, tipo)\njoin rma.mesa_trabajo m on m.codigo = v.mesa\njoin rma.tipo_reparacion t on t.codigo = v.tipo\non conflict do nothing;\n\n` +
    // clave: el id del dominio (INS-001), distinto del codigo (E3, DE3-1). Solo se
    // completa la clave provisoria de una fila anterior a E3 (clave = codigo): una
    // identidad ya asignada nunca se pisa (QA-E3-5).
    `insert into rma.insumo (clave, codigo, nombre, unidad, activo) values\n${insumos.map((i) => `  (${q(i.id)}, ${q(i.codigo)}, ${q(i.nombre)}, ${q(i.unidad)}, ${!!i.activo})`).join(",\n")}\non conflict (codigo) do update set clave = excluded.clave\n  where rma.insumo.clave = rma.insumo.codigo\n    and rma.insumo.clave is distinct from excluded.clave;\n\n` +
    // Por clave y codigo: una clave provisoria (= codigo de otro insumo) no matchea.
    `insert into rma.tipo_reparacion_insumo (tipo_reparacion_id, insumo_id, cantidad)\nselect t.id, i.id, v.cantidad from (values\n${tipoInsumos.map((x) => `  (${q(x.tipo_reparacion_id)}, ${q(x.insumo_id)}, ${q(codigoDe.get(x.insumo_id))}, ${x.cantidad}::numeric)`).join(",\n")}\n) as v (tipo, insumo, codigo, cantidad)\njoin rma.tipo_reparacion t on t.codigo = v.tipo\njoin rma.insumo i on i.clave = v.insumo and i.codigo = v.codigo\non conflict do nothing;\n\n` +
    `-- Verificación (QA-E3-5): cada fila de las fuentes quedó en la base, con su identidad.\n` +
    `do $$\ndeclare\n  v_faltan text;\nbegin\n` +
    verificacion(
      "usuarios con su rol",
      usuarios.map((u) => [q(u.id), q(u.rol)]),
      ["usuario", "rol"],
      "    select 1 from rma.usuario u\n    join rma.usuario_rol ur on ur.usuario_id = u.id\n    join rma.rol r on r.id = ur.rol_id\n    where u.codigo = v.usuario and r.codigo = v.rol"
    ) +
    verificacion(
      "estaciones de los tipos",
      tipoEstaciones.map((x) => [q(x.estacion_id), q(x.tipo_reparacion_id)]),
      ["mesa", "tipo"],
      "    select 1 from rma.mesa_tipo_reparacion x\n    join rma.mesa_trabajo m on m.id = x.mesa_trabajo_id\n    join rma.tipo_reparacion t on t.id = x.tipo_reparacion_id\n    where m.codigo = v.mesa and t.codigo = v.tipo"
    ) +
    verificacion(
      "insumos con su clave y su código",
      insumos.map((i) => [q(i.id), q(i.codigo)]),
      ["clave", "codigo"],
      "    select 1 from rma.insumo i where i.clave = v.clave and i.codigo = v.codigo"
    ) +
    verificacion(
      "insumos previstos",
      tipoInsumos.map((x) => [q(x.tipo_reparacion_id), q(x.insumo_id), q(codigoDe.get(x.insumo_id)), `${x.cantidad}::numeric`]),
      ["tipo", "insumo", "codigo", "cantidad"],
      "    select 1 from rma.tipo_reparacion_insumo x\n    join rma.tipo_reparacion t on t.id = x.tipo_reparacion_id\n    join rma.insumo i on i.id = x.insumo_id\n    where t.codigo = v.tipo and i.clave = v.insumo and i.codigo = v.codigo\n      and x.cantidad = v.cantidad"
    ) +
    `end;\n$$;\n\n` +
    `-- Stock inicial: un INGRESO por insumo, registrado por el proceso de carga inicial.\n` +
    `-- Sin ON CONFLICT: el libro no lo admite, porque aplica los saldos antes de resolver conflictos.\n` +
    `-- Solo se registran los ingresos que todavía no existen, y la acción solo si hay alguno.\n` +
    // QAF-8: antes de tocar el stock se confirma la identidad de cada insumo (clave y
    // codigo). Si alguno no la tiene, falla sin registrar nada, aun aplicada la carga
    // sentencia por sentencia.
    `-- Antes de tocar el stock se confirma la identidad de cada insumo (clave y código).\n` +
    `do $$\ndeclare\n  v_accion uuid;\n  v_faltan text;\n  r record;\nbegin\n` +
    `  select string_agg(concat_ws(' / ', v.clave, v.insumo), ', ') into v_faltan\n  from (values\n${insumos.map((i) => `    (${q(i.id)}, ${q(i.codigo)})`).join(",\n")}\n  ) as v (clave, insumo)\n  where not exists (select 1 from rma.insumo i where i.clave = v.clave and i.codigo = v.insumo);\n` +
    `  if v_faltan is not null then\n    raise exception 'Carga de desarrollo: stock inicial sin registrar, insumos sin su clave y su código: %', v_faltan;\n  end if;\n` +
    `  for r in\n    select i.id, i.codigo, v.cantidad\n    from (values\n${insumos.map((i) => `      (${q(i.id)}, ${q(i.codigo)}, ${i.stock_fisico}::numeric)`).join(",\n")}\n    ) as v (clave, insumo, cantidad)\n    join rma.insumo i on i.clave = v.clave and i.codigo = v.insumo\n    where v.cantidad > 0\n      and not exists (select 1 from rma.movimiento_inventario m where m.codigo = 'MST-INICIAL-' || i.codigo)\n  loop\n    if v_accion is null then\n      insert into rma.accion_usuario (proceso, operacion, resultado)\n      values ('CARGA_INICIAL_DESARROLLO', 'INGRESO_STOCK_INICIAL', 'CONFIRMADA')\n      returning id into v_accion;\n    end if;\n    insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, motivo_texto, accion_id)\n    values ('MST-INICIAL-' || r.codigo, 'INGRESO', r.id, r.cantidad, 'Saldo inicial de desarrollo', v_accion);\n  end loop;\nend;\n$$;\n`
  );
}

function datosDesarrollo() {
  return {
    usuarios: leer("app/backend/data/catalogs/usuarios.json"),
    estaciones: leer("app/backend/data/catalogs/estaciones.json"),
    tipos: leer("app/backend/data/catalogs/tipos_reparacion.json"),
    insumos: leer("app/backend/data/catalogs/insumos.json"),
    tipoInsumos: leer("app/backend/data/catalogs/tipo_reparacion_insumos.json"),
    tipoEstaciones: leer("app/backend/data/catalogs/tipo_reparacion_estaciones.json"),
  };
}

module.exports = { validarDesarrollo, cargaDesarrollo, datosDesarrollo };

if (require.main === module) {
  // Primero se valida y se arma todo; recién después se escribe.
  const desarrollo = cargaDesarrollo(datosDesarrollo());
  generarReferenciaOperativa();
  escribir("desarrollo/01_catalogos_demo.sql", desarrollo);
}
