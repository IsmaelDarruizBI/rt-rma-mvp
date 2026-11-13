/**
 * Motivos de catálogo (DEC-MI-15): cuándo se puede confirmar.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { MotivoOperativo } from "../src/api/operativa.ts";
import {
  etiquetaDelTexto,
  motivoCompleto,
  motivosVigentes,
} from "../src/features/ordenes-reparacion/motivos.ts";

const motivos: MotivoOperativo[] = [
  {
    codigo: "CANC-OTRO",
    tipo: "CANCELACION",
    nombre: "Otro",
    activo: true,
    requiere_descripcion: true,
  },
  {
    codigo: "CANC-PRECIO",
    tipo: "CANCELACION",
    nombre: "Precio no aceptado",
    activo: true,
    requiere_descripcion: false,
  },
  {
    codigo: "CANC-VIEJO",
    tipo: "CANCELACION",
    nombre: "Viejo",
    activo: false,
    requiere_descripcion: false,
  },
];

test("sin motivo de catálogo, el texto es obligatorio", () => {
  assert.equal(motivoCompleto(motivos, { codigo: null, texto: " " }), false);
  assert.equal(motivoCompleto(motivos, { codigo: null, texto: "x" }), true);
});

test("«Otro» exige descripción; los demás no", () => {
  assert.equal(motivoCompleto(motivos, { codigo: "CANC-OTRO", texto: "" }), false);
  assert.equal(motivoCompleto(motivos, { codigo: "CANC-OTRO", texto: "y" }), true);
  assert.equal(motivoCompleto(motivos, { codigo: "CANC-PRECIO", texto: "" }), true);
  assert.equal(
    etiquetaDelTexto(motivos, { codigo: "CANC-OTRO", texto: "" }, "Motivo"),
    "Descripción (obligatoria)",
  );
  assert.equal(
    etiquetaDelTexto(motivos, { codigo: null, texto: "" }, "Motivo"),
    "Motivo",
  );
});

test("un motivo inactivo no se ofrece ni se acepta", () => {
  assert.deepEqual(
    motivosVigentes(motivos).map((m) => m.codigo),
    ["CANC-OTRO", "CANC-PRECIO"],
  );
  assert.equal(motivoCompleto(motivos, { codigo: "CANC-VIEJO", texto: "z" }), false);
});
