/**
 * Entrega del equipo (ajustes funcionales, bloque 2).
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { textoRetiro } from "../src/features/ordenes-reparacion/entrega.ts";

const dia = (iso: string) => iso.slice(0, 10);

test("DEC-AJ-03: lista para retirar sin aviso, que es opcional", () => {
  assert.equal(
    textoRetiro("2026-11-01T10:00:00Z", null, dia),
    "Lista para retirar desde 2026-11-01 · sin aviso al cliente (es opcional).",
  );
});

test("DEC-AJ-03: la fecha del aviso se muestra aparte", () => {
  assert.equal(
    textoRetiro("2026-11-01T10:00:00Z", "2026-11-03T12:00:00Z", dia),
    "Lista para retirar desde 2026-11-01 · aviso al cliente: 2026-11-03.",
  );
});
