/**
 * Stock mínimo por insumo (DEC-AJ-11): nombres e indicador del estado de
 * reposición, validación del mínimo que se carga, causa de la sugerencia de
 * Compras y la solicitud que se confirma (con origen STOCK_MINIMO cuando el
 * mínimo aporta a la cantidad). El backend calcula todo de nuevo.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  NOMBRE_ORIGEN,
  NOMBRE_REPOSICION,
  bajoMinimo,
  causaSugerencia,
  leerStockMinimo,
  lineaInsumoBandeja,
  solicitudDeSugerencia,
  tonoReposicion,
} from "../src/features/inventario/stockMinimo.ts";

describe("estado de reposición", () => {
  test("distingue bajo mínimo de reposición solicitada", () => {
    assert.equal(tonoReposicion("BAJO_MINIMO"), "alerta");
    assert.equal(tonoReposicion("BAJO_MINIMO_REPOSICION_SOLICITADA"), "aviso");
    assert.equal(tonoReposicion("SUFICIENTE"), null);
    assert.equal(tonoReposicion("SIN_MINIMO"), null);
    // Un backend anterior no lo informa.
    assert.equal(tonoReposicion(undefined), null);
    assert.equal(bajoMinimo("BAJO_MINIMO_REPOSICION_SOLICITADA"), true);
    assert.equal(bajoMinimo("SUFICIENTE"), false);
    assert.equal(
      NOMBRE_REPOSICION.BAJO_MINIMO_REPOSICION_SOLICITADA,
      "Bajo mínimo · reposición solicitada",
    );
  });

  test("la línea de Inicio suma el mínimo y lo en camino", () => {
    const base = { disponible: "1", stock_fisico: "3", reservado: "2" };
    assert.equal(lineaInsumoBandeja(base), "Disponible 1 · en stock 3 · reservado 2");
    assert.equal(
      lineaInsumoBandeja({ ...base, stock_minimo: "4", en_camino: "0" }),
      "Disponible 1 · en stock 3 · reservado 2 · mínimo 4",
    );
    assert.equal(
      lineaInsumoBandeja({ ...base, stock_minimo: "4", en_camino: "3" }),
      "Disponible 1 · en stock 3 · reservado 2 · mínimo 4 · en camino 3",
    );
  });
});

describe("stock mínimo en Configuración → Insumos", () => {
  test("vacío es sin mínimo; número ≥ 0 con hasta tres decimales", () => {
    assert.deepEqual(leerStockMinimo(""), { valor: null, error: null });
    assert.deepEqual(leerStockMinimo("  "), { valor: null, error: null });
    assert.deepEqual(leerStockMinimo("0"), { valor: "0", error: null });
    assert.deepEqual(leerStockMinimo("5"), { valor: "5", error: null });
    assert.deepEqual(leerStockMinimo("2,125"), { valor: "2.125", error: null });
    for (const invalido of ["-1", "1.2345", "abc", "1e3", "1.2.3"]) {
      const { valor, error } = leerStockMinimo(invalido);
      assert.equal(valor, null, invalido);
      assert.match(error ?? "", /tres decimales/, invalido);
    }
  });
});

describe("sugerencias de reposición en Compras", () => {
  const base = { insumo_id: "INS-001", sugerido: "7", ordenes: ["OR-1"] };

  test("solo faltante (o backend anterior): origen FALTANTE", () => {
    for (const s of [base, { ...base, motivo: "FALTANTE" as const }]) {
      assert.equal(causaSugerencia(s), "Por faltante");
      assert.deepEqual(solicitudDeSugerencia(s), {
        insumo_id: "INS-001",
        cantidad: "7",
        motivo: "Faltante de Órdenes que esperan recursos.",
        origen: "FALTANTE",
        ordenes: ["OR-1"],
      });
    }
  });

  test("solo el mínimo: origen STOCK_MINIMO", () => {
    const s = {
      ...base,
      sugerido: "3",
      ordenes: [],
      motivo: "STOCK_MINIMO" as const,
      por_faltante: "0",
      por_minimo: "3",
      stock_minimo: "4",
    };
    assert.equal(causaSugerencia(s), "Por stock mínimo (4)");
    const solicitud = solicitudDeSugerencia(s);
    assert.equal(solicitud.origen, "STOCK_MINIMO");
    assert.equal(solicitud.cantidad, "3");
    assert.equal(solicitud.motivo, "Reposición hasta el stock mínimo.");
  });

  test("faltante y mínimo: STOCK_MINIMO con las Órdenes del faltante", () => {
    const s = {
      ...base,
      motivo: "STOCK_MINIMO" as const,
      por_faltante: "2",
      por_minimo: "5",
      stock_minimo: "5",
    };
    assert.equal(causaSugerencia(s), "Por faltante (2) y stock mínimo (5)");
    const solicitud = solicitudDeSugerencia(s);
    assert.equal(solicitud.origen, "STOCK_MINIMO");
    assert.deepEqual(solicitud.ordenes, ["OR-1"]);
    assert.match(solicitud.motivo, /y reposición hasta el stock mínimo/);
  });

  test("el origen de cada solicitud se nombra", () => {
    assert.equal(NOMBRE_ORIGEN.STOCK_MINIMO, "por stock mínimo");
    assert.equal(NOMBRE_ORIGEN.FALTANTE, "por faltante");
    assert.equal(NOMBRE_ORIGEN.MANUAL, "manual");
  });
});
