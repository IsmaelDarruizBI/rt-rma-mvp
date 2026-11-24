/**
 * Precio por modelo (DEC-AJ-12): el precio del Tipo para el modelo de la
 * Orden sin respaldo del precio único, el pedido de precio manual (solo con
 * el permiso y con motivo), el precio pendiente que nunca se muestra como
 * $0, la grilla de precios por modelo y los modelos repetidos.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  PRECIO_PENDIENTE,
  SIN_MANUAL,
  SIN_PRECIO_PARA_EL_MODELO,
  cambiosDePrecios,
  etiquetaOrigenPrecio,
  modeloRepetido,
  nombreModelo,
  numerosDeModelo,
  pedidoPrecioManual,
  precioDelTipo,
  textoPrecioDelDetalle,
  textoPrecioDelTipo,
} from "../src/features/ordenes-reparacion/precioModelo.ts";

const UNICO = { precio: "80000" };
const POR_MODELO = {
  precio: "999",
  precio_por_modelo: true,
  precios_modelo: { "MOD-0001": "60000" },
};

describe("precio del tipo para el modelo", () => {
  test("precio único, del modelo o sin precio (sin respaldo)", () => {
    assert.deepEqual(precioDelTipo(UNICO, null), { estado: "UNICO", precio: "80000" });
    assert.deepEqual(precioDelTipo(POR_MODELO, "MOD-0001"), {
      estado: "MODELO",
      precio: "60000",
    });
    assert.deepEqual(precioDelTipo(POR_MODELO, "MOD-0003"), { estado: "SIN_PRECIO", precio: null });
    assert.deepEqual(precioDelTipo(POR_MODELO, null), { estado: "SIN_PRECIO", precio: null });
    assert.equal(textoPrecioDelTipo(POR_MODELO, "MOD-0003"), SIN_PRECIO_PARA_EL_MODELO);
    assert.equal(textoPrecioDelTipo(POR_MODELO, "MOD-0001", (x) => `$ ${x}`), "$ 60000");
  });
});

describe("pedido de precio manual", () => {
  test("solo sin precio de catálogo y con el permiso", () => {
    const lleno = { precio: "70000,50", motivo: " Cotizado " };
    assert.deepEqual(pedidoPrecioManual(POR_MODELO, "MOD-0003", true, lleno), {
      pedido: { precio: "70000.50", precio_motivo: "Cotizado" },
      error: null,
    });
    // Con precio de catálogo, de precio único o sin el permiso: nada.
    for (const [tipo, modelo, puede] of [
      [POR_MODELO, "MOD-0001", true],
      [UNICO, null, true],
      [POR_MODELO, "MOD-0003", false],
    ] as const) {
      assert.deepEqual(pedidoPrecioManual(tipo, modelo, puede, lleno), {
        pedido: null,
        error: null,
      });
    }
  });

  test("vacío queda pendiente; incompleto o inválido es un error", () => {
    assert.deepEqual(pedidoPrecioManual(POR_MODELO, null, true, SIN_MANUAL), {
      pedido: null,
      error: null,
    });
    assert.match(
      pedidoPrecioManual(POR_MODELO, null, true, { precio: "100", motivo: "" }).error ?? "",
      /motivo/,
    );
    assert.match(
      pedidoPrecioManual(POR_MODELO, null, true, { precio: "1.234", motivo: "x" }).error ?? "",
      /inválido/,
    );
  });
});

describe("precio del trabajo", () => {
  test("pendiente nunca es $0 y el origen se marca", () => {
    const formato = (x: string) => `$ ${x}`;
    assert.equal(
      textoPrecioDelDetalle({ precio: "0", origen_precio: "PENDIENTE" }, formato),
      PRECIO_PENDIENTE,
    );
    assert.equal(textoPrecioDelDetalle({ precio: "0", precio_pendiente: true }), PRECIO_PENDIENTE);
    assert.equal(textoPrecioDelDetalle({ precio: "500", origen_precio: "MANUAL" }, formato), "$ 500");
    assert.equal(etiquetaOrigenPrecio("MANUAL"), "Precio manual");
    assert.equal(etiquetaOrigenPrecio("PENDIENTE"), "Precio pendiente");
    assert.equal(etiquetaOrigenPrecio("CATALOGO_MODELO"), null);
    assert.equal(etiquetaOrigenPrecio(undefined), null);
  });
});

describe("configuración", () => {
  test("la grilla envía solo los cambios; vacío retira", () => {
    const vigentes = { "MOD-0001": "60000", "MOD-0002": "65000" };
    assert.deepEqual(
      cambiosDePrecios(vigentes, {
        "MOD-0001": "60000.00",
        "MOD-0002": "",
        "MOD-0003": "70000,5",
        "MOD-0004": "",
        "MOD-0005": "abc",
      }),
      {
        cambios: [
          { modelo_equipo_id: "MOD-0002", precio: null },
          { modelo_equipo_id: "MOD-0003", precio: "70000.5" },
        ],
        invalidos: ["MOD-0005"],
      },
    );
  });

  test("modelos repetidos, nombre y números de modelo", () => {
    const modelos = [{ id: "MOD-0001", marca: "Apple", modelo: "iPhone 8", variante: null }];
    assert.equal(modeloRepetido(modelos, { marca: " apple", modelo: "iPhone  8" })?.id, "MOD-0001");
    assert.equal(modeloRepetido(modelos, { marca: "Apple", modelo: "iPhone 8" }, "MOD-0001"), null);
    assert.equal(modeloRepetido(modelos, { marca: "Apple", modelo: "iPhone 8", variante: "Plus" }), null);
    assert.equal(nombreModelo({ marca: "Apple", modelo: "iPhone 15", variante: "Pro Max" }), "Apple iPhone 15 Pro Max");
    assert.deepEqual(numerosDeModelo("A2849, A3090  A3091"), ["A2849", "A3090", "A3091"]);
  });
});
