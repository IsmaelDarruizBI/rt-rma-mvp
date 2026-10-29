/**
 * Selector del catálogo técnico de modelos: búsqueda (marca, modelo,
 * variante, número de modelo; sin mayúsculas ni acentos), elección, carga
 * manual con variante, color opcional y Órdenes anteriores (modelo
 * técnico, producto de Ventas o carga manual).
 *
 * Se ejecuta con `npm test` (node --test). Catálogo ficticio con la forma
 * de la respuesta real de `GET /api/catalogs/device-models`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { Equipo, ModeloEquipo } from "../src/types/api.ts";
import {
  EQUIPO_VACIO,
  buscarModelos,
  datosDelEquipo,
  elegirModelo,
  equipoElegidoDe,
  modoEfectivo,
  normalizar,
  quitarModelo,
} from "../src/features/ordenes-reparacion/modelosEquipo.ts";

const modelo = (
  id: string,
  nombreModelo: string,
  variante: string | null = null,
  numeros: string[] = [],
  marca = "Apple",
): ModeloEquipo => ({
  id,
  marca,
  modelo: nombreModelo,
  variante,
  numeros_modelo: numeros,
  nombre: [marca, nombreModelo, variante].filter(Boolean).join(" "),
});

const MODELOS: ModeloEquipo[] = [
  modelo("MOD-0001", "iPhone 15"),
  modelo("MOD-0002", "iPhone 15", "Pro"),
  modelo("MOD-0003", "iPhone 15", "Pro Max", ["A2849", "A3106"]),
  modelo("MOD-0004", "iPhone 16e"),
  modelo("MOD-0005", "iPhone 16"),
  modelo("MOD-0006", "Galaxy S23", "Ultra", [], "Samsung"),
];

const ids = (lista: ModeloEquipo[]) => lista.map((m) => m.id);

const EQUIPO: Equipo = {
  id: "EQP-1",
  marca: "Apple",
  modelo: "iPhone 15",
  variante: "Pro Max",
  falla_reportada: "No enciende.",
  imei: null,
  numero_serie: null,
};

test("normaliza mayúsculas, acentos y espacios", () => {
  assert.equal(normalizar("  Teléfono   PRO  "), "telefono pro");
});

test("busca por modelo y variante, primero el nombre más corto", () => {
  assert.deepEqual(ids(buscarModelos(MODELOS, "15 pro")), ["MOD-0002", "MOD-0003"]);
  assert.deepEqual(ids(buscarModelos(MODELOS, "15 PRO MAX")), ["MOD-0003"]);
  assert.deepEqual(ids(buscarModelos(MODELOS, "promax")), ["MOD-0003"]);
});

test("busca por número de modelo del fabricante y por marca", () => {
  assert.deepEqual(ids(buscarModelos(MODELOS, "a3106")), ["MOD-0003"]);
  assert.deepEqual(ids(buscarModelos(MODELOS, "samsung ultra")), ["MOD-0006"]);
  assert.deepEqual(ids(buscarModelos(MODELOS, "iphone 16e")), ["MOD-0004"]);
});

test("sin consulta o sin coincidencias, nada; con límite", () => {
  assert.deepEqual(buscarModelos(MODELOS, "   "), []);
  assert.deepEqual(buscarModelos(MODELOS, "nokia"), []);
  assert.equal(buscarModelos(MODELOS, "iphone", 2).length, 2);
});

test("elegir un modelo manda su ID y el color, si se cargó", () => {
  let elegido = elegirModelo(EQUIPO_VACIO, MODELOS[2]);
  assert.equal(elegido.nombreModelo, "Apple iPhone 15 Pro Max");
  assert.deepEqual(datosDelEquipo(true, elegido), {
    modelo_tecnico_id: "MOD-0003",
    color: null,
  });
  elegido = { ...elegido, color: " Negro " };
  assert.deepEqual(datosDelEquipo(true, elegido), {
    modelo_tecnico_id: "MOD-0003",
    color: "Negro",
  });
  // «Cambiar»: hay que volver a elegir.
  assert.equal(datosDelEquipo(true, quitarModelo(elegido)), null);
});

test("a mano: marca y modelo obligatorios, variante y color opcionales", () => {
  const manual = { ...EQUIPO_VACIO, modo: "manual" as const };
  assert.equal(datosDelEquipo(true, { ...manual, marca: "Samsung" }), null);
  assert.deepEqual(
    datosDelEquipo(true, {
      ...manual,
      marca: " Samsung ",
      modelo: "Galaxy S24",
      variante: "Ultra",
    }),
    { marca: "Samsung", modelo: "Galaxy S24", variante: "Ultra", color: null },
  );
  assert.deepEqual(
    datosDelEquipo(true, { ...manual, marca: "Motorola", modelo: "Moto G13" }),
    { marca: "Motorola", modelo: "Moto G13", variante: null, color: null },
  );
});

test("sin catálogo se carga a mano", () => {
  assert.equal(modoEfectivo(false, EQUIPO_VACIO), "manual");
  assert.equal(modoEfectivo(true, EQUIPO_VACIO), "catalogo");
});

test("corregir una Orden con modelo técnico lo conserva", () => {
  const elegido = equipoElegidoDe({
    ...EQUIPO,
    modelo_tecnico_id: "MOD-0003",
    color: "Azul",
  });
  assert.equal(elegido.nombreModelo, "Apple iPhone 15 Pro Max");
  // Aunque el modelo ya no se ofrezca (catálogo vacío).
  assert.deepEqual(datosDelEquipo(false, elegido), {
    modelo_tecnico_id: "MOD-0003",
    color: "Azul",
  });
});

test("una Orden anterior con producto de Ventas lo conserva hasta elegir otro", () => {
  const anterior: Equipo = {
    ...EQUIPO,
    tipo_producto_id: "apple_usados_iPhone_15_Pro Max_256gb_black",
    capacidad: "256 GB",
    color: "Black",
  };
  const elegido = equipoElegidoDe(anterior);
  assert.equal(modoEfectivo(false, elegido), "catalogo");
  assert.deepEqual(datosDelEquipo(true, elegido), {
    tipo_producto_id: "apple_usados_iPhone_15_Pro Max_256gb_black",
  });
  const otro = elegirModelo(elegido, MODELOS[0]);
  assert.equal(otro.productoVentas, null);
  assert.deepEqual(datosDelEquipo(true, otro), {
    modelo_tecnico_id: "MOD-0001",
    color: "Black",
  });
});

test("una Orden cargada a mano se corrige a mano, con su variante", () => {
  const elegido = equipoElegidoDe({ ...EQUIPO, marca: "Samsung", modelo: "S23", variante: "Ultra" });
  assert.equal(elegido.modo, "manual");
  assert.deepEqual(datosDelEquipo(true, elegido), {
    marca: "Samsung",
    modelo: "S23",
    variante: "Ultra",
    color: null,
  });
});
