/**
 * Mensajes del backend dichos sin códigos técnicos.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { mensajeLegible } from "../src/features/ordenes-reparacion/etiquetas.ts";

test("usuarios y estaciones conocidos se nombran; la OR queda", () => {
  const texto =
    "No se puede tomar la Orden (PROC-REP-172): La Orden ya esta tomada " +
    "por TECH-002 (estacion EST-001). Orden OR-000010.";
  assert.equal(
    mensajeLegible(texto, null, {
      "TECH-002": "Tecnico Dos",
      "EST-001": "Mesa tecnica 1",
    }),
    "No se puede tomar la Orden (un paso del proceso): La Orden ya esta " +
      "tomada por Tecnico Dos (estacion Mesa tecnica 1). Orden OR-000010.",
  );
  // Sin nombres, el ID queda como estaba.
  assert.match(mensajeLegible(texto, null), /TECH-002/);
});
