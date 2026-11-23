/**
 * Términos y Condiciones del comprobante de entrega y garantía: los
 * apartados de la hoja de Rosario Tecno (sin el que anulaba la garantía si
 * retiraba otra persona, DEC-AJ-09), uno resaltado, y solo en la entrega
 * de un equipo reparado.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  APARTADOS_TERMINOS,
  ENCABEZADO_TERMINOS,
  PIE_TERMINOS,
  llevaTerminos,
} from "../src/features/ordenes-reparacion/terminosCondiciones.ts";

test("los 18 apartados de la hoja, sin líneas vacías", () => {
  assert.equal(APARTADOS_TERMINOS.length, 18);
  for (const apartado of APARTADOS_TERMINOS) {
    assert.ok(apartado.lineas.length > 0);
    for (const linea of apartado.lineas) {
      assert.equal(linea, linea.trim());
      assert.ok(linea.length > 0);
    }
  }
  assert.match(APARTADOS_TERMINOS[0].lineas[0], /^La reparación cuenta con una garantía de seis meses \(180 días de corrido\)/);
  assert.match(APARTADOS_TERMINOS[2].lineas[0], /el repuesto debe estar entero y en óptimas condiciones\.$/);
  assert.match(APARTADOS_TERMINOS[17].lineas[0], /^El cliente declara haber leído, comprendido y aceptado/);
});

test("solo se resaltan los plazos estimativos", () => {
  const destacados = APARTADOS_TERMINOS.flatMap((apartado, indice) =>
    apartado.destacado ? [{ numero: indice + 1, texto: apartado.lineas.join(" ") }] : [],
  );
  assert.deepEqual(
    destacados.map((destacado) => destacado.numero),
    [16],
  );
  assert.equal(
    destacados[0].texto,
    "Los plazos de reparación son estimativos y pueden variar sin que ello genere derecho a reclamo alguno.",
  );
});

test("DEC-AJ-09: que retire otra persona no anula la garantía", () => {
  const texto = APARTADOS_TERMINOS.flatMap((apartado) => apartado.lineas).join(" ");
  assert.doesNotMatch(texto, /quedará automáticamente anulada/);
  assert.doesNotMatch(texto, /misma persona que dejó el equipo/);
  assert.match(
    texto,
    /entregado únicamente contra el pago total de la reparación y la presentación del comprobante correspondiente\./,
  );
});

test("encabezado de Rosario Tecno y pie con firma, aclaración y fecha", () => {
  assert.deepEqual(ENCABEZADO_TERMINOS, {
    marca: "ROSARIO | TECNO",
    titulo: "TÉRMINOS Y CONDICIONES",
    subtitulo: "SERVICIO TÉCNICO",
  });
  assert.deepEqual([...PIE_TERMINOS], ["FIRMA DEL CLIENTE", "ACLARACIÓN", "FECHA"]);
});

test("solo la entrega de un equipo reparado lleva los términos", () => {
  assert.equal(llevaTerminos({ tipo_entrega: "REPARACION_TERMINADA" }), true);
  assert.equal(llevaTerminos({ tipo_entrega: "DEVOLUCION_SIN_REPARACION" }), false);
});
