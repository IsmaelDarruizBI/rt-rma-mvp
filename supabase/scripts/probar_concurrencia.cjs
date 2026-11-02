// Pruebas de concurrencia del esquema rma con conexiones simultáneas reales.
//
// Uso: RMA_DB_URL=postgresql://usuario@host:puerto/base node supabase/scripts/probar_concurrencia.cjs
//
// Requiere el paquete «pg» (npm install pg en una carpeta de herramientas; no es
// dependencia del proyecto). La base debe tener las migraciones aplicadas y el
// usuario de conexión debe poder asumir el rol rma_backend. Nunca correr contra
// producción: crea datos de prueba y los deja en la base.
const { Client } = require("pg");

const url = process.env.RMA_DB_URL;
if (!url) {
  console.error("Falta RMA_DB_URL.");
  process.exit(2);
}
const nuevo = async () => {
  const c = new Client({ connectionString: url });
  await c.connect();
  await c.query("set role rma_backend");
  return c;
};
const sufijo = Date.now().toString(36);
let fallas = 0;
const resultado = (caso, ok, detalle) => {
  if (!ok) fallas++;
  console.log(ok ? "ok   " : "FALLA", caso, detalle ? `(${detalle})` : "");
};

async function preparar(c) {
  const uno = async (sql, params) => (await c.query(sql, params)).rows[0];
  const usuario = await uno("insert into rma.usuario (codigo, nombre) values ($1, 'Concurrencia') returning id", [`USR-C-${sufijo}`]);
  const accion = await uno(
    "insert into rma.accion_usuario (usuario_id, operacion, resultado) values ($1, 'PREPARAR', 'CONFIRMADA') returning id", [usuario.id]);
  const cliente = await uno("insert into rma.cliente (codigo, nombre) values ($1, 'Cliente concurrencia') returning id", [`CLI-C-${sufijo}`]);
  const equipo = await uno("insert into rma.equipo (codigo) values ($1) returning id", [`EQ-C-${sufijo}`]);
  const orden = await uno(
    `insert into rma.orden (origen, estado_workflow, posicion_proceso, cliente_id, equipo_id, cliente_nombre, equipo_marca, equipo_modelo, falla_reportada)
     values ('CLIENTE_EXTERNO', 'EN_COLA', 'PROC-REP-170', $1, $2, 'Cliente concurrencia', 'Apple', 'iPhone 14', 'No carga') returning id`,
    [cliente.id, equipo.id]);
  const tipo = await uno(
    "insert into rma.tipo_reparacion (codigo, nombre, precio, puntaje, garantia_dias) values ($1, 'Batería', 1, 1, 90) returning id", [`TR-C-${sufijo}`]);
  const detalle = await uno("insert into rma.detalle (orden_id, codigo, garantia_dias) values ($1, 'DET-001', 90) returning id", [orden.id]);
  const version = await uno(
    "insert into rma.detalle_version (detalle_id, numero, tipo_reparacion_id, precio, puntaje, garantia_dias) values ($1, 1, $2, 1, 1, 90) returning id",
    [detalle.id, tipo.id]);
  const mesa = await uno("insert into rma.mesa_trabajo (codigo, nombre) values ($1, 'Mesa') returning id", [`MESA-C-${sufijo}`]);
  const toma = await uno(
    "insert into rma.toma (codigo, orden_id, usuario_id, mesa_trabajo_id) values ($1, $2, $3, $4) returning id",
    [`TOM-C-${sufijo}`, orden.id, usuario.id, mesa.id]);
  const insumo = await uno("insert into rma.insumo (codigo, nombre) values ($1, 'Batería concurrencia') returning id", [`INS-C-${sufijo}`]);
  await c.query(
    "insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, motivo_texto, usuario_id, accion_id) values ($1, 'INGRESO', $2, 2, 'Prueba', $3, $4)",
    [`MOV-C-I-${sufijo}`, insumo.id, usuario.id, accion.id]);
  return { usuario, accion, orden, detalle, version, toma, insumo };
}

// Ejecuta B mientras A tiene su transacción abierta; devuelve el error de B, si lo hubo.
async function enParalelo(sqlA, paramsA, sqlB, paramsB) {
  const a = await nuevo();
  const b = await nuevo();
  try {
    await a.query("begin");
    await a.query(sqlA, paramsA);
    await b.query("begin");
    const pendienteB = b.query(sqlB, paramsB).then(() => null, (e) => e);
    await new Promise((r) => setTimeout(r, 300)); // B queda esperando el bloqueo de A
    await a.query("commit");
    const errorB = await pendienteB;
    await b.query(errorB ? "rollback" : "commit");
    return errorB;
  } finally {
    await a.end();
    await b.end();
  }
}

(async () => {
  const c = await nuevo();
  const d = await preparar(c);
  const reserva = (codigo) => [
    "insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, orden_id, detalle_id, accion_id) values ($1, 'RESERVA', $2, 2, $3, $4, $5)",
    [codigo, d.insumo.id, d.orden.id, d.detalle.id, d.accion.id],
  ];

  // 1. Dos reservas simultáneas que juntas superan el disponible (2 + 2 sobre 2).
  let error = await enParalelo(...reserva(`MOV-C-R1-${sufijo}`), ...reserva(`MOV-C-R2-${sufijo}`));
  const { rows } = await c.query("select stock_fisico, stock_reservado from rma.insumo where id = $1", [d.insumo.id]);
  resultado("reservas simultáneas: la segunda espera y se rechaza", error && error.code === "23514", error && error.code);
  resultado("reservas simultáneas: el reservado queda en 2", Number(rows[0].stock_reservado) === 2, rows[0].stock_reservado);

  // 2. Ajuste negativo simultáneo con una reserva del mismo insumo: el ajuste se rechaza.
  const motivo = (await c.query(
    "insert into rma.motivo_ajuste (codigo, descripcion, aplica_a) values ($1, 'Recuento', 'AMBOS') returning id", [`MOT-C-${sufijo}`])).rows[0];
  const lib = await c.query("select id from rma.movimiento_inventario where codigo = $1", [`MOV-C-R1-${sufijo}`]);
  error = await enParalelo(
    "insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, motivo_texto, usuario_id, accion_id) values ($1, 'INGRESO', $2, 1, 'Compra', $3, $4)",
    [`MOV-C-I2-${sufijo}`, d.insumo.id, d.usuario.id, d.accion.id],
    "insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, motivo_ajuste_id, motivo_texto, usuario_id, accion_id) values ($1, 'AJUSTE_NEGATIVO', $2, 2, $3, 'Recuento', $4, $5)",
    [`MOV-C-A1-${sufijo}`, d.insumo.id, motivo.id, d.usuario.id, d.accion.id]);
  resultado("ajuste negativo con reservas vigentes, en paralelo con un ingreso: se rechaza", error && error.code === "23514", error && error.code);

  // 3. Dos Ejecuciones en curso simultáneas en la misma Orden.
  const ejecucion = (codigo) => [
    "insert into rma.ejecucion (codigo, orden_id, detalle_id, detalle_version_id, toma_id, usuario_id) values ($1, $2, $3, $4, $5, $6)",
    [codigo, d.orden.id, d.detalle.id, d.version.id, d.toma.id, d.usuario.id],
  ];
  error = await enParalelo(...ejecucion(`EJE-C1-${sufijo}`), ...ejecucion(`EJE-C2-${sufijo}`));
  resultado("dos Ejecuciones en curso simultáneas: la segunda se rechaza", error && error.code === "23505", error && error.code);

  // 4. Reintento simultáneo con la misma clave de idempotencia.
  const accion = [
    "insert into rma.accion_usuario (usuario_id, operacion, clave_idempotencia, resultado) values ($1, 'REGISTRAR_PAGO', $2, 'CONFIRMADA')",
    [d.usuario.id, `clave-${sufijo}`],
  ];
  error = await enParalelo(...accion, ...accion);
  resultado("misma clave de idempotencia en paralelo: el reintento se rechaza", error && error.code === "23505", error && error.code);

  // 5. Eventos simultáneos de la misma Orden: secuencias distintas y consecutivas.
  const tipo = (await c.query("select id from rma.tipo_evento where codigo = 'EV-REP-016'")).rows[0];
  const evento = [
    "insert into rma.evento_negocio (orden_id, tipo_evento_id, accion_id, responsable_tipo, usuario_id) values ($1, $2, $3, 'USUARIO', $4)",
    [d.orden.id, tipo.id, d.accion.id, d.usuario.id],
  ];
  error = await enParalelo(...evento, ...evento);
  const sec = (await c.query("select array_agg(secuencia order by secuencia) as s from rma.evento_negocio where orden_id = $1", [d.orden.id])).rows[0].s;
  resultado("eventos simultáneos: sin error y con secuencias 1 y 2", !error && JSON.stringify(sec) === "[1,2]", JSON.stringify(sec));

  // 6. La conciliación sigue en cero diferencias.
  const dif = (await c.query("select count(*)::int as n from rma.verificar_integridad() where verificacion = 'CONCILIACION_INVENTARIO'")).rows[0].n;
  resultado("conciliación del inventario después de las pruebas", dif === 0, `${dif} diferencias`);

  await c.end();
  process.exit(fallas ? 1 : 0);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
