// Arma un único script con las pruebas SQL envueltas en una transacción que termina en ROLLBACK,
// para correrlas en un proyecto remoto sin dejar datos.
//
// Uso (desde la raíz de rt-rma-mvp):
//   node supabase/scripts/armar_pruebas_remotas.cjs <destino.sql>
//   npx supabase db query --remote --yes --file <destino.sql>
//
// Una regla incumplida lanza una excepción y aborta todo el script. La prueba 40 opera como
// rma_backend: el script le da al usuario de la conexión una membresía temporal en ese rol,
// que el ROLLBACK final también deshace.
//
// Las secuencias no son transaccionales: después de correrlo, la numeración de Órdenes avanza.
// Para volver a OR-000001 en un proyecto sin Órdenes reales:
//   select setval('rma.orden_numero_seq', 1, false);
const fs = require("fs");
const path = require("path");

const destino = process.argv[2];
if (!destino) {
  console.error("Uso: node supabase/scripts/armar_pruebas_remotas.cjs <destino.sql>");
  process.exit(2);
}
const dir = path.resolve(__dirname, "..", "tests");
const pruebas = fs
  .readdirSync(dir)
  .filter((f) => /^\d+_.+\.sql$/.test(f) && !f.startsWith("00_") && !f.startsWith("99_"))
  .sort();
const sinTransaccion = (texto) =>
  texto
    .replace(/\r\n/g, "\n")
    .split("\n")
    .filter((linea) => !/^(begin|rollback);$/.test(linea.trim()))
    .join("\n");

const partes = [
  "begin;",
  "-- Membresía temporal para ejecutar las pruebas como rma_backend; se revierte con el ROLLBACK final.",
  "grant rma_backend to current_user with set true, inherit false;",
  fs.readFileSync(path.join(dir, "00_utilidades.sql"), "utf8").replace(/\r\n/g, "\n"),
  ...pruebas.map((f) => `-- ==== ${f}\n${sinTransaccion(fs.readFileSync(path.join(dir, f), "utf8"))}`),
  "rollback;",
  "",
];
fs.writeFileSync(destino, partes.join("\n"));
console.log(`escrito ${destino} con ${pruebas.length} pruebas: ${pruebas.join(", ")}`);
