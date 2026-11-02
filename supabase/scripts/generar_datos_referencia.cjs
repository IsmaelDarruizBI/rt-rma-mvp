// Genera supabase/migrations/20261102001200_datos_referencia.sql. Uso: node supabase/scripts/generar_datos_referencia.cjs <destino.sql>
const fs = require("fs");
const path = require("path");
const q = (s) => (s === null ? "null" : `'${String(s).replace(/'/g, "''")}'`);

// [codigo, nombre, entidad, visible en el historial actual, referencias del historial]
// referencias: "PROC-REP-nnn" (cualquier accion) o "PROC-REP-nnn:ACCION" o "ACC-REP-nnn:ACCION".
const tipos = [
  ["EV-REP-001", "Orden creada", "orden", true, ["PROC-REP-040", "PROC-REP-030", "PROC-REP-020"]],
  ["EV-REP-002", "Datos del ingreso corregidos", "recepcion", true, ["ACC-REP-023:REGISTRAR_DATOS_RECEPCION"]],
  ["EV-REP-003", "Recepción física confirmada", "recepcion", true, ["ACC-REP-024:CONFIRMAR_RECEPCION_FISICA"]],
  ["EV-REP-004", "Equipo registrado como no recibido", "recepcion", true, ["ACC-REP-027:REGISTRAR_EQUIPO_NO_RECIBIDO"]],
  ["EV-REP-005", "Nota agregada", "recepcion", true, ["ACC-REP-025:AGREGAR_OBSERVACION_RECEPCION"]],
  ["EV-REP-006", "Foto agregada", "foto", false, []],
  ["EV-REP-007", "Comprobante emitido", "documento_emitido", true, ["PROC-REP-060", "PROC-REP-280", "ACC-REP-002:EMITIR_DOCUMENTO", "ACC-REP-060:EMITIR_DOCUMENTO"]],
  ["EV-REP-008", "Orden enviada a revisión", "orden", true, ["PROC-REP-055"]],
  ["EV-REP-009", "Revisión técnica registrada", "orden", true, ["PROC-REP-065"]],
  ["EV-REP-010", "Detalle definido", "detalle", true, ["PROC-REP-070", "PROC-REP-075"]],
  ["EV-REP-011", "Decisión del cliente registrada", "decision_cliente", true, ["PROC-REP-046:REGISTRAR_DECISION_CLIENTE", "PROC-REP-046", "PROC-REP-047", "PROC-REP-129"]],
  ["EV-REP-012", "Factibilidad evaluada", "orden", true, ["PROC-REP-080", "PROC-REP-090", "PROC-REP-100", "PROC-REP-120"]],
  ["EV-REP-013", "Override de recursos autorizado", "override_recursos", true, ["ACC-REP-049:AUTORIZAR_OVERRIDE_RECURSOS", "PROC-REP-130"]],
  ["EV-REP-014", "Recursos revalidados", "orden", true, ["ACC-REP-028:REVALIDAR_RECURSOS"]],
  ["EV-REP-015", "Orden habilitada", "orden", true, ["PROC-REP-140"]],
  ["EV-REP-016", "Prioridad asignada o cambiada", "orden", true, ["PROC-REP-150", "ACC-REP-007:CAMBIAR_PRIORIDAD"]],
  ["EV-REP-017", "Finalizada sin reparación", "orden", true, ["PROC-REP-069"]],
  ["EV-REP-018", "Orden ingresada a la cola", "orden", true, ["PROC-REP-170"]],
  ["EV-REP-019", "Toma iniciada", "toma", true, ["PROC-REP-172", "PROC-REP-180"]],
  ["EV-REP-020", "Detalle seleccionado", "detalle", true, ["PROC-REP-174", "PROC-REP-181"]],
  ["EV-REP-021", "Ejecución iniciada", "ejecucion", true, ["PROC-REP-185", "PROC-REP-190"]],
  ["EV-REP-022", "Reserva fallida", "detalle", true, ["PROC-REP-186"]],
  ["EV-REP-023", "Ejecución completada, interrumpida o con redefinición requerida", "ejecucion", true, ["PROC-REP-200", "PROC-REP-125"]],
  ["EV-REP-024", "Movimientos de inventario generados", "movimiento_inventario", true, ["PROC-REP-210"]],
  ["EV-REP-025", "Detalle revisado", "detalle", true, ["PROC-REP-126"]],
  ["EV-REP-026", "Detalle redefinido", "detalle_version", true, ["PROC-REP-127"]],
  ["EV-REP-027", "Toma liberada", "toma", true, ["PROC-REP-213"]],
  ["EV-REP-028", "Control registrado", "control_tecnico", true, ["PROC-REP-220", "PROC-REP-230", "PROC-REP-235"]],
  ["EV-REP-029", "Puntaje acreditado", "detalle", true, ["PROC-REP-245"]],
  ["EV-REP-030", "Reparación lista", "orden", true, ["PROC-REP-240"]],
  ["EV-REP-031", "Cliente notificado", "orden", true, ["PROC-REP-250", "PROC-REP-260"]],
  ["EV-REP-032", "Resultado informado a Gestión RT", "orden", true, ["PROC-REP-290"]],
  ["EV-REP-033", "Check-in registrado", "checkin", false, []],
  ["EV-REP-034", "Garantía ajustada", "ajuste_garantia", false, []],
  ["EV-REP-035", "Entrega registrada", "salida", true, ["PROC-REP-270:ENTREGAR_EQUIPO"]],
  ["EV-REP-036", "Devolución física registrada", "salida", true, ["PROC-REP-270:DEVOLVER_EQUIPO_SIN_REPARAR", "PROC-REP-270:DEVOLVER_EQUIPO_RT", "PROC-REP-270"]],
  ["EV-REP-037", "Proceso cerrado", "orden", false, []],
  ["EV-REP-038", "Pago registrado", "pago", true, ["ACC-REP-020:REGISTRAR_PAGO"]],
  ["EV-REP-039", "Pago anulado", "pago", true, ["ACC-REP-021:ANULAR_PAGO"]],
  ["EV-REP-040", "Dinero devuelto", "devolucion_dinero", true, ["ACC-REP-022:REGISTRAR_DEVOLUCION_DINERO"]],
  ["EV-REP-041", "Descuento aplicado, cambiado o quitado", "descuento", false, []],
  ["EV-REP-042", "Entrega bloqueada por saldo", "orden", true, ["PROC-REP-265", "PROC-REP-266"]],
  ["EV-REP-043", "Saldo a favor verificado", "orden", true, ["PROC-REP-268"]],
  ["EV-REP-044", "Detalle cancelado", "detalle", true, ["PROC-REP-300", "PROC-REP-046:REGISTRAR_DESISTIMIENTO_CLIENTE"]],
  ["EV-REP-045", "Orden cancelada", "orden", true, ["PROC-REP-305", "PROC-REP-306"]],
  ["EV-REP-046", "Desistimiento solicitado", "orden", false, []],
  ["EV-REP-047", "Garantía RMA iniciada", "orden", true, ["PROC-REP-035"]],
  ["EV-REP-048", "Stock ingresado o ajustado", "movimiento_inventario", false, []],
  ["EV-REP-049", "Cliente creado", "cliente", false, []],
  ["EV-REP-050", "Datos del cliente modificados", "cliente", false, []],
  ["EV-REP-051", "Documento del cliente corregido", "documento_cliente", false, []],
];
// Paso tecnico: decisiones del proceso que hoy aparecen en el historial pero no son eventos de negocio.
const tecnico = ["EV-SIS-001", "Paso de decisión del proceso", "orden", true,
  ["PROC-REP-010", "PROC-REP-045", "PROC-REP-050", "PROC-REP-068", "PROC-REP-110", "PROC-REP-211", "PROC-REP-212"]];

if (tipos.length !== 51) throw new Error("deben ser 51 tipos de negocio");
const equivalencias = [];
const vistas = new Set();
for (const [codigo, , , , refs] of [...tipos, tecnico]) {
  for (const ref of refs) {
    const [id, accion] = ref.split(":");
    const tipoRef = id.startsWith("PROC-REP") ? "PROCESS_NODE" : "FUNCTIONAL_ACTION";
    const clave = `${tipoRef}|${id}|${accion || ""}`;
    if (vistas.has(clave)) throw new Error("equivalencia repetida " + clave);
    vistas.add(clave);
    equivalencias.push([tipoRef, id, accion || null, codigo]);
  }
}
// Toda accion transversal sin equivalencia por defecto recibe la de su unica accion.
for (const [tipoRef, id, accion, codigo] of [...equivalencias]) {
  if (tipoRef === "FUNCTIONAL_ACTION" && accion && !vistas.has(`${tipoRef}|${id}|`) && id !== "ACC-REP-060" && id !== "ACC-REP-002") {
    vistas.add(`${tipoRef}|${id}|`);
    equivalencias.push([tipoRef, id, null, codigo]);
  }
}

const filasTipo = [...tipos.map((t) => [...t, true]), [...tecnico, false]]
  .map(([codigo, nombre, entidad, visible, , negocio]) => `  (${q(codigo)}, ${q(nombre)}, ${q(entidad)}, ${negocio}, ${visible})`)
  .join(",\n");
const filasEq = equivalencias
  .map(([t, id, a, c]) => `  (${q(t)}, ${q(id)}, ${q(a)}, ${q(c)})`)
  .join(",\n");

const sql = `-- Rosario Tecno RMA — Esquema físico PostgreSQL
-- 1200. Datos de referencia: parte del modelo, iguales en todos los entornos.
--
-- Generado por supabase/scripts/generar_datos_referencia.cjs a partir del mapa de equivalencias del
-- historial del MVP (rt-rma-mvp 6516d4c). Incluye:
--   * los cuatro roles operativos;
--   * el tipo de documento DNI, cuya regla de normalización usa el MVP;
--   * los 51 tipos de evento de negocio aprobados y un tipo técnico para los
--     pasos de decisión del proceso (EV-SIS-001);
--   * ${equivalencias.length} equivalencias entre las entradas del historial actual y esos tipos.
-- No incluye datos operativos (catálogos, stock, usuarios): van en supabase/seeds.

insert into rma.rol (codigo, nombre) values
  ('RECEPCION', 'Recepción'),
  ('TECNICO', 'Técnico'),
  ('COORDINADOR_RMA', 'Coordinación RMA'),
  ('ADMINISTRADOR', 'Administración');

insert into rma.tipo_documento (codigo, nombre, aplica_a, regla_normalizacion, exige_unicidad) values
  ('DNI', 'DNI', 'FISICA', 'DNI_AR', true);

insert into rma.tipo_evento (codigo, nombre, entidad, es_negocio, visible_historial_actual) values
${filasTipo};

insert into rma.equivalencia_historial (tipo_referencia, referencia_id, accion, tipo_evento_id)
select v.tipo_referencia, v.referencia_id, v.accion, t.id
from (values
${filasEq}
) as v (tipo_referencia, referencia_id, accion, codigo)
join rma.tipo_evento t on t.codigo = v.codigo;
`;
const destino = process.argv[2];
fs.writeFileSync(destino, sql);
console.log("tipos", tipos.length + 1, "equivalencias", equivalencias.length);
