/**
 * Progreso de la Orden (DEC-AJ-03, pendiente del bloque 2 resuelto en el
 * bloque 4): avisar al cliente (PROC-REP-260) es opcional; si la Orden
 * siguió sin el aviso, el paso se dice salteado, no pendiente.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { tituloDePaso } from "../src/features/ordenes-reparacion/etiquetas.ts";

test("progreso: avisar al cliente es opcional; salteado no es pendiente", () => {
  const paso = { process_id: "PROC-REP-260", etiqueta: "Notificar cliente", alcanzado: false };
  assert.equal(
    tituloDePaso({ ...paso, opcional: true }),
    "PROC-REP-260 — Notificar cliente (opcional)",
  );
  assert.equal(
    tituloDePaso({ ...paso, opcional: true, omitido: true }),
    "PROC-REP-260 — Notificar cliente (opcional, salteado)",
  );
  // Una API anterior no manda los campos nuevos.
  assert.equal(tituloDePaso(paso), "PROC-REP-260 — Notificar cliente");
});
