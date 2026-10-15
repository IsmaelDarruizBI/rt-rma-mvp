/**
 * Formulario de priorización: propone la predeterminada del catálogo.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { Prioridad } from "../src/types/api.ts";
import {
  opcionDePrioridad,
  prioridadPropuesta,
} from "../src/features/ordenes-reparacion/prioridad.ts";

// Lo que publica GET /api/catalogs/priorities.
const CATALOGO: Prioridad[] = [
  { valor: 1, nombre: "Urgente", predeterminada: false },
  { valor: 2, nombre: "Alta", predeterminada: false },
  { valor: 3, nombre: "Media", predeterminada: false },
  { valor: 4, nombre: "Normal", predeterminada: true },
];

test("el formulario propone 4 — Normal", () => {
  assert.equal(prioridadPropuesta(CATALOGO), 4);
  assert.deepEqual(CATALOGO.map(opcionDePrioridad), [
    "1 — Urgente",
    "2 — Alta",
    "3 — Media",
    "4 — Normal",
  ]);
});

test("sin catálogo todavía no hay propuesta (no se asigna nada)", () => {
  assert.equal(prioridadPropuesta([]), null);
});
