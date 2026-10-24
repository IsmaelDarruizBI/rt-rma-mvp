/**
 * Nombres del ciclo operativo del Detalle de Reparacion (DC17, consolidacion
 * V1.4 del 23/10/2026): DEFINIDO, EN_PROGRESO, COMPLETO y CANCELADO, los mismos
 * que usa la implementacion. V1.3 y la V1.4 previa a la consolidacion decian
 * PENDIENTE y EN_PROCESO para los dos primeros. Es un cambio de nombre, no de
 * significado: los tests comparan V1.4 contra V1.3 aplicando este renombre y
 * verifican que en V1.4 no quede ningun nombre anterior.
 *
 * Pure helpers, no runtime imports (same style as process-core.ts).
 */
export const DETAIL_STATES = ["DEFINIDO", "EN_PROGRESO", "COMPLETO", "CANCELADO"] as const;

export const LEGACY_DETAIL_STATE_NAMES: Readonly<Record<string, string>> = {
  PENDIENTE: "DEFINIDO",
  EN_PROCESO: "EN_PROGRESO",
};

/**
 * Usos de los nombres anteriores que NO nombran el estado operativo del
 * Detalle y se conservan: estados de evaluacion descartados (BR-REP-026,
 * FEAT-REP-002), una solicitud de autorizacion (VAR-REP-019), un saldo
 * (HP-REP-001) y la declaracion de equivalencia de BR-REP-012. Cada patron
 * cubre la forma YAML y la forma JSON (JSON.stringify) del mismo texto.
 */
const NON_STATE_USES: readonly RegExp[] = [
  /estados(\s+)PENDIENTE, CONFIRMADA/g,
  /queda(\s+)PENDIENTE para/g,
  /balance_before_final_payment(["\s:,]+label["\s:]+[^\n"]*["\s,]+value["\s:]+)PENDIENTE/g,
  /llamaba(\s+)PENDIENTE(\s+)y(\s+)EN_PROCESO/g,
];

const LEGACY = /(?<![A-Z_])(PENDIENTE|EN_PROCESO)(?![A-Z_])/g;
const SENTINEL: Readonly<Record<string, string>> = { PENDIENTE: "\u0000", EN_PROCESO: "\u0001" };

function protect(text: string): string {
  return NON_STATE_USES.reduce(
    (acc, pattern) => acc.replace(pattern, (match) => match.replace(LEGACY, (name) => SENTINEL[name])),
    text
  );
}

function restore(text: string): string {
  return Object.entries(SENTINEL).reduce((acc, [name, sentinel]) => acc.split(sentinel).join(name), text);
}

/** Renombra los nombres anteriores del estado del Detalle (PENDIENTE -> DEFINIDO, EN_PROCESO -> EN_PROGRESO). */
export function renameLegacyDetailStates(text: string): string {
  return restore(protect(text).replace(LEGACY, (name) => LEGACY_DETAIL_STATE_NAMES[name]));
}

/** Fragmentos donde todavia aparece un nombre anterior del estado del Detalle (vacio = ninguno). */
export function legacyDetailStateUses(text: string): string[] {
  const found: string[] = [];
  const clean = protect(text);
  for (const match of clean.matchAll(LEGACY)) {
    const at = match.index ?? 0;
    found.push(clean.slice(Math.max(0, at - 40), at + 20).replace(/\s+/g, " "));
  }
  return found;
}
