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
    `insert into rma.medio_pago (codigo, nombre) values\n${medios.map(([c, n]) => `  (${q(c)}, ${q(n)})`).join(",\n")}\non conflict (codigo) do nothing;\n\n` +
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

// --- Desarrollo (ficticios) ---------------------------------------------------------
const usuarios = leer("app/backend/data/catalogs/usuarios.json");
const estaciones = leer("app/backend/data/catalogs/estaciones.json");
const tipos = leer("app/backend/data/catalogs/tipos_reparacion.json");
const insumos = leer("app/backend/data/catalogs/insumos.json");
const tipoInsumos = leer("app/backend/data/catalogs/tipo_reparacion_insumos.json");
const tipoEstaciones = leer("app/backend/data/catalogs/tipo_reparacion_estaciones.json");
const conOtros = tipos.some((t) => t.id === "TR-OTROS")
  ? tipos
  : [...tipos, { id: "TR-OTROS", nombre: "Otros — Reparación no tipificada", precio: "0", puntaje: 0, garantia_dias: 0, activo: true }];

escribir(
  "desarrollo/01_catalogos_demo.sql",
  cabecera("DATOS FICTICIOS DE DESARROLLO — nunca cargar en producción", "app/backend/data/catalogs/*.json") +
    `-- Idempotente: volver a cargarlo no duplica ni cambia nada.\n\n` +
    `insert into rma.usuario (codigo, nombre, activo) values\n${usuarios.map((u) => `  (${q(u.id)}, ${q(u.nombre)}, ${!!u.activo})`).join(",\n")}\non conflict (codigo) do nothing;\n\n` +
    `insert into rma.usuario_rol (usuario_id, rol_id)\nselect u.id, r.id from (values\n${usuarios.map((u) => `  (${q(u.id)}, ${q(u.rol)})`).join(",\n")}\n) as v (usuario, rol)\njoin rma.usuario u on u.codigo = v.usuario\njoin rma.rol r on r.codigo = v.rol\non conflict do nothing;\n\n` +
    `insert into rma.mesa_trabajo (codigo, nombre, activa) values\n${estaciones.map((e) => `  (${q(e.id)}, ${q(e.nombre)}, ${!!e.activa})`).join(",\n")}\non conflict (codigo) do nothing;\n\n` +
    `insert into rma.tipo_reparacion (codigo, nombre, precio, puntaje, garantia_dias, activo) values\n${conOtros.map((t) => `  (${q(t.id)}, ${q(t.nombre)}, ${t.precio}, ${t.puntaje}, ${t.garantia_dias}, ${!!t.activo})`).join(",\n")}\non conflict (codigo) do nothing;\n\n` +
    `insert into rma.mesa_tipo_reparacion (mesa_trabajo_id, tipo_reparacion_id)\nselect m.id, t.id from (values\n${tipoEstaciones.map((x) => `  (${q(x.estacion_id)}, ${q(x.tipo_reparacion_id)})`).join(",\n")}\n) as v (mesa, tipo)\njoin rma.mesa_trabajo m on m.codigo = v.mesa\njoin rma.tipo_reparacion t on t.codigo = v.tipo\non conflict do nothing;\n\n` +
    `insert into rma.insumo (codigo, nombre, unidad, activo) values\n${insumos.map((i) => `  (${q(i.codigo)}, ${q(i.nombre)}, ${q(i.unidad)}, ${!!i.activo})`).join(",\n")}\non conflict (codigo) do nothing;\n\n` +
    `insert into rma.tipo_reparacion_insumo (tipo_reparacion_id, insumo_id, cantidad)\nselect t.id, i.id, v.cantidad from (values\n${tipoInsumos.map((x) => `  (${q(x.tipo_reparacion_id)}, ${q(insumos.find((i) => i.id === x.insumo_id).codigo)}, ${x.cantidad}::numeric)`).join(",\n")}\n) as v (tipo, insumo, cantidad)\njoin rma.tipo_reparacion t on t.codigo = v.tipo\njoin rma.insumo i on i.codigo = v.insumo\non conflict do nothing;\n\n` +
    `-- Stock inicial: un INGRESO por insumo, registrado por el proceso de carga inicial.\n` +
    `-- Sin ON CONFLICT: el libro no lo admite, porque aplica los saldos antes de resolver conflictos.\n` +
    `-- Solo se registran los ingresos que todavía no existen, y la acción solo si hay alguno.\n` +
    `do $$\ndeclare\n  v_accion uuid;\n  r record;\nbegin\n  for r in\n    select i.id, i.codigo, v.cantidad\n    from (values\n${insumos.map((i) => `      (${q(i.codigo)}, ${i.stock_fisico}::numeric)`).join(",\n")}\n    ) as v (insumo, cantidad)\n    join rma.insumo i on i.codigo = v.insumo\n    where v.cantidad > 0\n      and not exists (select 1 from rma.movimiento_inventario m where m.codigo = 'MST-INICIAL-' || i.codigo)\n  loop\n    if v_accion is null then\n      insert into rma.accion_usuario (proceso, operacion, resultado)\n      values ('CARGA_INICIAL_DESARROLLO', 'INGRESO_STOCK_INICIAL', 'CONFIRMADA')\n      returning id into v_accion;\n    end if;\n    insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, motivo_texto, accion_id)\n    values ('MST-INICIAL-' || r.codigo, 'INGRESO', r.id, r.cantidad, 'Saldo inicial de desarrollo', v_accion);\n  end loop;\nend;\n$$;\n`
);
