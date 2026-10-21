/**
 * Check-in al cierre (UAT-009): se registra antes de entregar, con la
 * reparación lista, y define la garantía de cada trabajo (90 o 30 días).
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  NOMBRE_ACCION,
  SITUACION,
  descripcionCheckin,
} from "../src/features/ordenes-reparacion/etiquetas.ts";

test("verificado: garantía de 90 días", () => {
  assert.equal(
    descripcionCheckin(true),
    "Funciones básicas verificadas (garantía sugerida: 90 días)",
  );
});

test("no verificado: garantía de 30 días", () => {
  assert.equal(
    descripcionCheckin(false),
    "No se pudieron verificar las funciones básicas (garantía sugerida: 30 días)",
  );
});

test("sin registrar: pendiente hasta antes de la entrega", () => {
  for (const valor of [null, undefined]) {
    assert.equal(
      descripcionCheckin(valor),
      "Pendiente: se registra antes de entregar el equipo",
    );
  }
});

test("la acción tiene nombre legible", () => {
  assert.equal(NOMBRE_ACCION.REGISTRAR_CHECKIN, "Registrar el check-in");
});

test("avisada y saldada sin check-in: advertencia, no «lista para entregar»", () => {
  assert.equal(
    SITUACION.PENDIENTE_CHECKIN,
    "Pendiente de verificación de funciones básicas",
  );
});
