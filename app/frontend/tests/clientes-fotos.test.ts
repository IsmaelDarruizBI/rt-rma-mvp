/**
 * UAT-010: DNI en el alta y fotos del equipo (validación y
 * reducción). Solo funciones sin DOM.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { normalizarDni } from "../src/features/ordenes-reparacion/clientes.ts";
import {
  MAX_BYTES_FOTO,
  MAX_FOTOS,
  dimensionesReducidas,
  fotosQueCaben,
  motivoArchivoInvalido,
} from "../src/features/ordenes-reparacion/fotos.ts";

test("DNI: acepta puntos y espacios, devuelve solo dígitos", () => {
  assert.equal(normalizarDni("30.123.456"), "30123456");
  assert.equal(normalizarDni(" 7 123 456 "), "7123456");
  assert.equal(normalizarDni("07.123.456"), "7123456");
});

test("DNI: rechaza letras y largos inválidos", () => {
  for (const texto of ["", "123456", "123456789", "30A23456", "00123456"]) {
    assert.equal(normalizarDni(texto), null, texto);
  }
});

test("fotos: el lado mayor queda en 1600 px y conserva la proporción", () => {
  assert.deepEqual(dimensionesReducidas(4032, 3024), { ancho: 1600, alto: 1200 });
  assert.deepEqual(dimensionesReducidas(3024, 4032), { ancho: 1200, alto: 1600 });
  assert.deepEqual(dimensionesReducidas(800, 600), { ancho: 800, alto: 600 });
});

test("fotos: solo imágenes, no vacías y hasta 8 MB", () => {
  assert.equal(motivoArchivoInvalido("image/jpeg", 300_000), null);
  assert.equal(motivoArchivoInvalido("image/heic", 2_000_000), null);
  assert.equal(motivoArchivoInvalido("application/pdf", 1000), "no es una imagen");
  assert.equal(motivoArchivoInvalido("image/png", 0), "está vacío");
  assert.equal(
    motivoArchivoInvalido("image/jpeg", MAX_BYTES_FOTO + 1),
    "pesa más de 8 MB",
  );
});

test("fotos: hasta 10 por Orden, contando las guardadas y las por revisar", () => {
  assert.equal(MAX_FOTOS, 10);
  assert.equal(fotosQueCaben(0, 0, 3), 3);
  assert.equal(fotosQueCaben(7, 0, 5), 3);
  assert.equal(fotosQueCaben(6, 2, 5), 2);
  assert.equal(fotosQueCaben(10, 0, 1), 0);
  assert.equal(fotosQueCaben(9, 3, 1), 0);
});
