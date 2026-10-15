/**
 * Rutas en el hash de la URL y elección del usuario de demostración.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  type Ruta,
  esCanonico,
  hashDe,
  parsearRuta,
} from "../src/features/ordenes-reparacion/rutas.ts";
import { elegirUsuarioDemo } from "../src/features/ordenes-reparacion/usuarioDemo.ts";

describe("rutas", () => {
  test("cada pantalla tiene su URL y se lee de vuelta", () => {
    const rutas: [Ruta, string][] = [
      [{ pantalla: "ordenes" }, "#/ordenes"],
      [{ pantalla: "nueva" }, "#/ordenes/nueva"],
      [{ pantalla: "orden", ordenId: "OR-000001" }, "#/ordenes/OR-000001"],
      [{ pantalla: "inventario" }, "#/inventario"],
    ];
    for (const [ruta, hash] of rutas) {
      assert.equal(hashDe(ruta), hash);
      assert.deepEqual(parsearRuta(hash), ruta);
      assert.ok(esCanonico(hash), hash);
    }
  });

  test("lo vacío o desconocido va al listado", () => {
    for (const hash of ["", "#", "#/", "#/otra", "#/ordenes/a/b", "#/inventario/x"]) {
      assert.deepEqual(parsearRuta(hash), { pantalla: "ordenes" }, hash);
    }
  });

  test("formas no canónicas se normalizan", () => {
    assert.deepEqual(parsearRuta("#/ordenes/"), { pantalla: "ordenes" });
    assert.deepEqual(parsearRuta("#ordenes/OR-000007/"), {
      pantalla: "orden",
      ordenId: "OR-000007",
    });
    assert.ok(!esCanonico(""));
    assert.ok(!esCanonico("#/ordenes/"));
  });

  test("el número de Orden se codifica y decodifica", () => {
    const ruta: Ruta = { pantalla: "orden", ordenId: "OR 1/2" };
    assert.equal(hashDe(ruta), "#/ordenes/OR%201%2F2");
    assert.deepEqual(parsearRuta(hashDe(ruta)), ruta);
    // Un escape inválido no rompe la pantalla.
    assert.deepEqual(parsearRuta("#/ordenes/OR-%E0"), {
      pantalla: "orden",
      ordenId: "OR-%E0",
    });
  });
});

describe("usuario de demostración", () => {
  const usuarios = [{ id: "USR-REC-01" }, { id: "USR-TEC-01" }];

  test("se recupera el guardado si sigue en el catálogo", () => {
    assert.equal(elegirUsuarioDemo(usuarios, "USR-TEC-01"), "USR-TEC-01");
  });

  test("si no existe o no hay nada guardado, el primero", () => {
    assert.equal(elegirUsuarioDemo(usuarios, "USR-BORRADO"), "USR-REC-01");
    assert.equal(elegirUsuarioDemo(usuarios, null), "USR-REC-01");
    assert.equal(elegirUsuarioDemo([], "USR-TEC-01"), "");
  });
});
