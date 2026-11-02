// Verifica la conexión del usuario rma_api sin exponer secretos ni dejar datos.
//
// Uso:
//   node supabase/scripts/verificar_conexion_rma_api.cjs --proyecto-gcp <p> --secreto <s>
//     Lee la cadena de conexión de GCP Secret Manager (requiere gcloud autenticado).
//   RMA_DB_URL=<cadena> node supabase/scripts/verificar_conexion_rma_api.cjs
//     Alternativa para bases locales.
//   --ca <archivo>  Certificado raíz con que validar el TLS, si el sistema no lo reconoce.
//
// Requiere el paquete «pg», que no es dependencia del proyecto. Nunca imprime la cadena de
// conexión. Valida el certificado TLS del servidor. Todo lo que escribe va en transacciones que
// terminan en ROLLBACK: no deja filas ni consume la secuencia de Órdenes. La prueba de bloqueos
// usa dos conexiones simultáneas.
const fs = require("fs");
const { spawnSync } = require("child_process");
const { Client } = require("pg");

const args = process.argv.slice(2);
const opcion = (nombre) => {
  const i = args.indexOf(`--${nombre}`);
  return i >= 0 ? args[i + 1] : undefined;
};
let url = process.env.RMA_DB_URL;
if (opcion("secreto")) {
  const r = spawnSync(
    "gcloud",
    ["secrets", "versions", "access", "latest", `--secret=${opcion("secreto")}`, `--project=${opcion("proyecto-gcp")}`],
    { encoding: "utf8", shell: process.platform === "win32" }
  );
  if (r.status !== 0) {
    console.error("No se pudo leer el secreto: " + (r.stderr || "").trim().split("\n")[0]);
    process.exit(1);
  }
  url = r.stdout;
}
if (!url) {
  console.error("Falta la cadena de conexión: --proyecto-gcp y --secreto, o RMA_DB_URL.");
  process.exit(2);
}
// node-postgres trata sslmode por su cuenta: se quita de la cadena y el TLS se configura explícito.
const destino = new URL(url.trim());
destino.searchParams.delete("sslmode");
const local = ["localhost", "127.0.0.1"].includes(destino.hostname);
const tls = local ? false : { rejectUnauthorized: true, ...(opcion("ca") ? { ca: fs.readFileSync(opcion("ca"), "utf8") } : {}) };
url = destino.toString();
// Mensajes de error sin datos de conexión.
const limpio = (e) => `${e.code || "sin código"}: ${String(e.message).replace(/postgres(ql)?:\/\/\S+/g, "<cadena oculta>")}`;
let fallas = 0;
const resultado = (caso, ok, detalle) => {
  if (!ok) fallas++;
  console.log(ok ? "ok   " : "FALLA", caso, detalle ? `(${detalle})` : "");
};
const conectar = async () => {
  const c = new Client({ connectionString: url, ssl: tls });
  await c.connect();
  return c;
};
async function debeFallar(c, caso, sql, codigo) {
  await c.query("begin");
  try {
    await c.query(sql);
    resultado(caso, false, "se ejecutó y debía fallar");
  } catch (e) {
    resultado(caso, e.code === codigo, e.code === codigo ? codigo : limpio(e));
  } finally {
    await c.query("rollback");
  }
}

(async () => {
  const c = await conectar();
  if (!local) {
    const socket = c.connection.stream;
    resultado("conexión TLS con certificado validado", socket.encrypted === true && socket.authorized === true, socket.getProtocol && socket.getProtocol());
  }
  const datos = (await c.query(
    `select current_user as usuario, current_setting('server_version') as version,
            pg_has_role(current_user, 'rma_backend', 'usage') as hereda_rma_backend,
            current_setting('statement_timeout') as statement_timeout`
  )).rows[0];
  resultado("conexión establecida como rma_api", datos.usuario === "rma_api", `usuario ${datos.usuario}, PostgreSQL ${datos.version}`);
  resultado("hereda los permisos de rma_backend", datos.hereda_rma_backend === true);
  resultado("límite de duración de sentencias", datos.statement_timeout === "30s", datos.statement_timeout);

  // Permitido: lectura.
  const tipos = (await c.query("select count(*)::int as n from rma.tipo_evento")).rows[0].n;
  resultado("lee el catálogo de eventos", tipos === 52, `${tipos} tipos`);
  const motivos = (await c.query("select count(*)::int as n from rma.motivo_ajuste where activo")).rows[0].n;
  resultado("lee los motivos de ajuste", motivos === 4, `${motivos} activos`);

  // Permitido: escritura dentro de una transacción revertida.
  await c.query("begin");
  try {
    const accion = (await c.query(
      "insert into rma.accion_usuario (proceso, operacion, resultado) values ('VERIFICACION_CONEXION', 'PRUEBA', 'CONFIRMADA') returning id"
    )).rows[0];
    await c.query("update rma.accion_usuario set respuesta = '{\"ok\": true}' where id = $1", [accion.id]);
    resultado("registra y completa una acción (revertida)", true);
  } catch (e) {
    resultado("registra y completa una acción (revertida)", false, limpio(e));
  } finally {
    await c.query("rollback");
  }

  // Denegado.
  await debeFallar(c, "no borra Órdenes", "delete from rma.orden", "42501");
  await debeFallar(c, "no modifica el stock directamente", "update rma.insumo set stock_fisico = 0", "42501");
  await debeFallar(c, "no modifica el libro de inventario", "update rma.movimiento_inventario set cantidad = 1", "42501");
  await debeFallar(c, "no crea tablas en rma", "create table rma.prueba_no_permitida (id int)", "42501");
  await debeFallar(c, "no carga tipos de evento", "insert into rma.tipo_evento (codigo, nombre, entidad) values ('X', 'X', 'x')", "42501");
  await debeFallar(c, "no lee los usuarios de Supabase Auth", "select count(*) from auth.users", "42501");
  await debeFallar(c, "no asume el rol postgres", "set local role postgres", "42501");

  // Bloqueos a través del pooler: la segunda conexión no puede tomar la fila que bloquea la primera.
  const a = await conectar();
  const b = await conectar();
  try {
    await a.query("begin");
    await a.query("select 1 from rma.empresa for update");
    await b.query("begin");
    await b.query("set local lock_timeout = '2s'");
    try {
      await b.query("select 1 from rma.empresa for update");
      resultado("bloqueo de fila entre conexiones", false, "la segunda conexión tomó la fila");
    } catch (e) {
      resultado("bloqueo de fila entre conexiones", e.code === "55P03", e.code === "55P03" ? "espera y vence el plazo" : limpio(e));
    }
    await b.query("rollback");
    await a.query("rollback");
  } finally {
    await a.end();
    await b.end();
  }

  // Nada quedó escrito.
  const restos = (await c.query(
    "select count(*)::int as n from rma.accion_usuario where proceso = 'VERIFICACION_CONEXION'"
  )).rows[0].n;
  resultado("no quedaron datos de la verificación", restos === 0, `${restos} filas`);
  await c.end();
  process.exit(fallas ? 1 : 0);
})().catch((e) => {
  console.error("Error de conexión:", limpio(e));
  process.exit(1);
});
