// Genera la credencial del usuario de conexión rma_api, la guarda en GCP Secret Manager y crea
// (o rota) el rol en el proyecto Supabase vinculado.
//
// - La contraseña es aleatoria (32 bytes, base64url) y nunca se muestra ni se escribe en disco.
// - Secret Manager recibe la cadena de conexión completa del pooler de Supabase en modo
//   transacción por la entrada estándar de gcloud: no pasa por la línea de comandos, ni por una
//   tubería de PowerShell (que agregaría un salto de línea), ni por archivos.
// - El SQL del rol lleva solo el verificador SCRAM-SHA-256 y llega a «supabase db query --remote»
//   por la entrada estándar: no se escribe en ningún archivo. La contraseña en texto plano nunca
//   viaja al servidor de base de datos.
// - La salida de la CLI se filtra antes de mostrarse: un verificador, una cadena de conexión o la
//   contraseña que aparecieran en un mensaje se reemplazan por «<oculto>».
// - En pantalla solo se informan el secreto, la versión creada y el resultado del SQL.
//
// Uso, desde la raíz de rt-rma-mvp, con gcloud autenticado y el proyecto Supabase vinculado
// (funciona igual en PowerShell y en bash):
//   node supabase/scripts/generar_credencial_rma_api.cjs crear --proyecto-gcp <proyecto> --secreto <secreto> --project-ref <ref> --pooler-host <host>
//
// «crear» exige que el secreto exista y no tenga versiones activas: nunca sobrescribe una
// credencial. «rotar» exige al menos una versión activa y aplica un ALTER ROLE; la versión
// anterior queda en el secreto y se deshabilita a mano después de verificar la nueva.
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const RAIZ_REPO = path.resolve(__dirname, "..", "..");

const argv = process.argv.slice(2);
const o = { modo: argv[0] };
for (let i = 1; i < argv.length; i += 2) o[argv[i].replace(/^--/, "")] = argv[i + 1];
const faltan = ["proyecto-gcp", "secreto", "project-ref", "pooler-host"].filter((k) => !o[k]);
if (!["crear", "rotar"].includes(o.modo) || faltan.length) {
  console.error(
    "Uso: node supabase/scripts/generar_credencial_rma_api.cjs crear|rotar --proyecto-gcp <p> --secreto <s> --project-ref <ref> --pooler-host <host>"
  );
  if (faltan.length) console.error("Faltan: " + faltan.join(", "));
  process.exit(2);
}
if (!/^[a-z0-9]{20}$/.test(o["project-ref"]) || !/^[a-z0-9.-]+\.pooler\.supabase\.com$/.test(o["pooler-host"])) {
  console.error("project-ref o pooler-host con formato inesperado.");
  process.exit(2);
}
const vinculado = (() => {
  try {
    return fs.readFileSync(path.join(RAIZ_REPO, "supabase", ".temp", "project-ref"), "utf8").trim();
  } catch {
    return "";
  }
})();
if (vinculado !== o["project-ref"]) {
  console.error(`El proyecto Supabase vinculado (${vinculado || "ninguno"}) no es ${o["project-ref"]}.`);
  process.exit(2);
}

// En Windows gcloud y npx son .cmd: se invocan por el shell con argumentos fijos y sin espacios.
const ejecutar = (comando, args, entrada) => {
  const r = spawnSync(comando, args, {
    cwd: RAIZ_REPO,
    input: entrada,
    encoding: "utf8",
    shell: process.platform === "win32",
  });
  return { ok: r.status === 0, salida: (r.stdout || "").trim(), error: (r.stderr || "").trim() };
};
const gcloud = (args, entrada) => ejecutar("gcloud", [...args, `--project=${o["proyecto-gcp"]}`], entrada);

const existe = gcloud(["secrets", "describe", o.secreto, "--format=value(name)"]);
if (!existe.ok) {
  console.error(`El secreto ${o.secreto} no existe o no es accesible en ${o["proyecto-gcp"]}. Este script no crea secretos.`);
  process.exit(1);
}
const versiones = gcloud(["secrets", "versions", "list", o.secreto, "--filter=state=ENABLED", "--format=value(name)"]);
if (!versiones.ok) {
  console.error("No se pudieron listar las versiones del secreto.");
  process.exit(1);
}
const activas = versiones.salida ? versiones.salida.split(/\s+/).length : 0;
if (o.modo === "crear" && activas > 0) {
  console.error(`El secreto ${o.secreto} ya tiene ${activas} versión(es) activa(s): «crear» no sobrescribe credenciales.`);
  process.exit(1);
}
if (o.modo === "rotar" && activas === 0) {
  console.error(`El secreto ${o.secreto} no tiene versiones activas: usá «crear».`);
  process.exit(1);
}

const password = crypto.randomBytes(32).toString("base64url");
function verificadorScram(clave, iteraciones = 4096) {
  const sal = crypto.randomBytes(16);
  const salada = crypto.pbkdf2Sync(Buffer.from(clave, "utf8"), sal, iteraciones, 32, "sha256");
  const claveCliente = crypto.createHmac("sha256", salada).update("Client Key").digest();
  const claveAlmacenada = crypto.createHash("sha256").update(claveCliente).digest();
  const claveServidor = crypto.createHmac("sha256", salada).update("Server Key").digest();
  return `SCRAM-SHA-256$${iteraciones}:${sal.toString("base64")}$${claveAlmacenada.toString("base64")}:${claveServidor.toString("base64")}`;
}
const verificador = verificadorScram(password);
const cadena = `postgresql://rma_api.${o["project-ref"]}:${password}@${o["pooler-host"]}:6543/postgres?sslmode=verify-full`;
const ocultar = (texto) =>
  [password, verificador, cadena].reduce(
    (t, valor) => t.split(valor).join("<oculto>"),
    String(texto || "")
      .replace(/SCRAM-SHA-256\$[^'"\s]+/g, "<oculto>")
      .replace(/postgres(ql)?:\/\/\S+/g, "<oculto>")
  );

const agregado = gcloud(["secrets", "versions", "add", o.secreto, "--data-file=-", "--format=value(name)"], cadena);
if (!agregado.ok) {
  console.error("No se pudo guardar la versión del secreto: " + ocultar(agregado.error).split("\n")[0]);
  console.error("No se aplicó el SQL: el rol no se crea sin su credencial guardada.");
  process.exit(1);
}
console.log(`Secreto ${o.secreto}: versión ${agregado.salida.split("/").pop()} guardada en ${o["proyecto-gcp"]}.`);

const sql =
  o.modo === "crear"
    ? [
        `create role rma_api login password '${verificador}' in role rma_backend connection limit 20;`,
        "alter role rma_api set statement_timeout = '30s';",
        "alter role rma_api set idle_in_transaction_session_timeout = '60s';",
        "comment on role rma_api is 'Usuario de conexión del backend FastAPI de Rosario Tecno RMA; permisos heredados de rma_backend.';",
      ]
    : [`alter role rma_api password '${verificador}';`];
// Versión fija de la CLI: sin ella, npx podría pedir confirmación para instalar y consumir el SQL
// de la entrada estándar.
const aplicado = ejecutar("npx", ["-y", "supabase@3.1.0", "db", "query", "--remote", "--yes"], sql.join("\n"));
const salida = ocultar(`${aplicado.salida}\n${aplicado.error}`);
if (!aplicado.ok || /"_tag"\s*:\s*"Error"/.test(salida)) {
  console.error("El SQL del rol falló en Supabase. La versión del secreto quedó guardada sin un rol que la use; no se rotó nada.");
  console.error(salida.split("\n").filter((l) => /error|message/i.test(l)).slice(0, 5).join("\n"));
  process.exit(1);
}
console.log(`rma_api: ${o.modo === "crear" ? "creado" : "contraseña rotada"} en el proyecto Supabase ${o["project-ref"]}.`);
