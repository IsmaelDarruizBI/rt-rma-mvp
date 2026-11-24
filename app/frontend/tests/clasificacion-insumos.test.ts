/**
 * Clasificación de insumos y compatibilidad con modelos (DEC-AJ-14):
 * etiquetas, filtros, compatibilidad y el selector de modelos. El backend
 * valida y aplica la misma regla.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  CLASIFICACION_VACIA,
  type ClasificacionInsumos,
  SIN_CLASIFICAR,
  agregarModelos,
  alternarModelo,
  buscarModelos,
  categoriaRaiz,
  compatibleCon,
  enCategoria,
  esUniversal,
  etiquetaInsumo,
  filtraClasificacion,
  filtrarInsumos,
  nombreCategoria,
  nombreRepetido,
  opcionesCategoria,
  resumenClasificacion,
  textoCompatibilidad,
} from "../src/features/inventario/clasificacion.ts";
import {
  ENTIDAD_DE_SECCION,
  seccionesPermitidas,
} from "../src/features/configuracion/secciones.ts";

const CLASIFICACION: ClasificacionInsumos = {
  categorias: [
    { id: "CAT-001", nombre: "Baterías", padre_id: null, activo: true },
    { id: "CAT-002", nombre: "Módulos", padre_id: null, activo: true },
    { id: "CAT-003", nombre: "OLED", padre_id: "CAT-002", activo: true },
    { id: "CAT-004", nombre: "Viejas", padre_id: null, activo: false },
    { id: "CAT-005", nombre: "Sub", padre_id: "CAT-004", activo: true },
  ],
  fabricantes: [
    { id: "FAB-001", nombre: "Acme", activo: true },
    { id: "FAB-002", nombre: "Baja", activo: false },
  ],
  modelos: [
    { id: "MOD-0014", marca: "Apple", nombre: "Apple iPhone 14", activo: true },
    { id: "MOD-0015", marca: "Apple", nombre: "Apple iPhone 14 Pro", activo: true },
    { id: "MOD-0016", marca: "Apple", nombre: "Apple iPhone 15", activo: true },
    { id: "MOD-0003", marca: "Apple", nombre: "Apple iPhone 8", activo: false },
  ],
};

const BATERIA_14 = {
  id: "INS-001",
  codigo: "INS-001",
  nombre: "Batería iPhone 14",
  activo: true,
  categoria_id: "CAT-001",
  fabricante_id: "FAB-001",
  variante: "alta capacidad",
  codigo_fabricante: "APN-661",
  modelos_compatibles: ["MOD-0014"],
};
const OLED_14 = {
  id: "INS-002",
  codigo: "INS-002",
  nombre: "Módulo OLED",
  activo: true,
  categoria_id: "CAT-003",
  fabricante_id: null,
  variante: null,
  modelos_compatibles: ["MOD-0014", "MOD-0015", "MOD-0016"],
};
const ADHESIVO = { id: "INS-003", codigo: "INS-003", nombre: "Adhesivo", activo: true };
const INACTIVO = { ...BATERIA_14, id: "INS-004", codigo: "INS-004", activo: false };
const TODOS = [BATERIA_14, OLED_14, ADHESIVO, INACTIVO];

describe("compatibilidad", () => {
  test("sin modelos es universal; con modelos, solo esos; sin modelo técnico, solo universales", () => {
    assert.equal(esUniversal(ADHESIVO), true);
    assert.equal(compatibleCon(ADHESIVO, "MOD-0016"), true);
    assert.equal(compatibleCon(ADHESIVO, null), true);
    assert.equal(esUniversal(BATERIA_14), false);
    assert.equal(compatibleCon(BATERIA_14, "MOD-0014"), true);
    assert.equal(compatibleCon(BATERIA_14, "MOD-0016"), false);
    assert.equal(compatibleCon(BATERIA_14, null), false);
  });

  test("se muestra como «Universal», los nombres o la cantidad", () => {
    assert.equal(textoCompatibilidad(ADHESIVO, CLASIFICACION), "Universal");
    assert.equal(textoCompatibilidad(BATERIA_14, CLASIFICACION), "Apple iPhone 14");
    assert.equal(textoCompatibilidad(OLED_14, CLASIFICACION), "3 modelos");
    assert.equal(
      textoCompatibilidad(OLED_14, CLASIFICACION, 3),
      "Apple iPhone 14, Apple iPhone 14 Pro, Apple iPhone 15",
    );
    // Un modelo que no está en el catálogo se nombra por su código.
    assert.equal(
      textoCompatibilidad({ ...ADHESIVO, modelos_compatibles: ["MOD-9999"] }, CLASIFICACION),
      "MOD-9999",
    );
  });
});

describe("etiquetas", () => {
  test("categoría con su padre, fabricante y variante", () => {
    assert.equal(nombreCategoria("CAT-003", CLASIFICACION), "Módulos › OLED");
    assert.equal(nombreCategoria("CAT-001", CLASIFICACION), "Baterías");
    assert.equal(nombreCategoria(null, CLASIFICACION), null);
    assert.equal(categoriaRaiz("CAT-003", CLASIFICACION), "CAT-002");
    assert.equal(
      etiquetaInsumo(BATERIA_14, CLASIFICACION),
      "INS-001 · Batería iPhone 14 · Acme · alta capacidad",
    );
    assert.equal(etiquetaInsumo(ADHESIVO, CLASIFICACION), "INS-003 · Adhesivo");
    assert.equal(
      resumenClasificacion(BATERIA_14, CLASIFICACION),
      "Baterías · Acme · alta capacidad",
    );
    assert.equal(resumenClasificacion(ADHESIVO, CLASIFICACION), "Sin clasificar");
  });

  test("sin catálogo (backend anterior o modo JSON) se nombra por código", () => {
    assert.equal(
      etiquetaInsumo(BATERIA_14, CLASIFICACION_VACIA),
      "INS-001 · Batería iPhone 14 · FAB-001 · alta capacidad",
    );
    assert.equal(nombreCategoria("CAT-003", CLASIFICACION_VACIA), "CAT-003");
  });

  test("opciones de categoría en árbol, con las de baja marcadas", () => {
    const todas = opcionesCategoria(CLASIFICACION);
    assert.deepEqual(
      todas.map((o) => [o.id, o.etiqueta, o.activo]),
      [
        ["CAT-001", "Baterías", true],
        ["CAT-002", "Módulos", true],
        ["CAT-003", "Módulos › OLED", true],
        ["CAT-004", "Viejas", false],
        // Vigente, pero su categoría está de baja.
        ["CAT-005", "Viejas › Sub", false],
      ],
    );
    assert.deepEqual(
      opcionesCategoria(CLASIFICACION, { soloVigentes: true, conservar: "CAT-005" }).map((o) => o.id),
      ["CAT-001", "CAT-002", "CAT-003", "CAT-005"],
    );
  });
});

describe("filtros", () => {
  const ids = (lista: { id: string }[]) => lista.map((i) => i.id);

  test("por categoría (incluye subcategorías), sin clasificar, fabricante y modelo", () => {
    assert.equal(enCategoria(OLED_14, "CAT-002", CLASIFICACION), true);
    assert.equal(enCategoria(OLED_14, "CAT-003", CLASIFICACION), true);
    assert.equal(enCategoria(ADHESIVO, SIN_CLASIFICAR, CLASIFICACION), true);
    assert.deepEqual(ids(filtrarInsumos(TODOS, { categoria: "CAT-002" }, CLASIFICACION)), ["INS-002"]);
    assert.deepEqual(ids(filtrarInsumos(TODOS, { categoria: SIN_CLASIFICAR }, CLASIFICACION)), ["INS-003"]);
    assert.deepEqual(
      ids(filtrarInsumos(TODOS, { fabricante: "FAB-001", soloVigentes: true }, CLASIFICACION)),
      ["INS-001"],
    );
    // Los universales sirven para cualquier modelo.
    assert.deepEqual(
      ids(filtrarInsumos(TODOS, { modelo: "MOD-0016" }, CLASIFICACION)),
      ["INS-002", "INS-003"],
    );
    assert.equal(filtraClasificacion({ texto: "x" }), false);
    assert.equal(filtraClasificacion({ modelo: "MOD-0016" }), true);
  });

  test("el texto busca en código, nombre, código del fabricante, fabricante y categoría, sin acentos", () => {
    assert.deepEqual(ids(filtrarInsumos(TODOS, { texto: "apn-6" }, CLASIFICACION)), ["INS-001", "INS-004"]);
    assert.deepEqual(ids(filtrarInsumos(TODOS, { texto: "modulos" }, CLASIFICACION)), ["INS-002"]);
    assert.deepEqual(ids(filtrarInsumos(TODOS, { texto: "acme", soloVigentes: true }, CLASIFICACION)), [
      "INS-001",
    ]);
  });
});

describe("selector de modelos", () => {
  test("busca, alterna y agrega los visibles vigentes", () => {
    const visibles = buscarModelos(CLASIFICACION.modelos, "iphone 14");
    assert.deepEqual(
      visibles.map((m) => m.id),
      ["MOD-0014", "MOD-0015"],
    );
    assert.deepEqual(buscarModelos(CLASIFICACION.modelos, "mod-0003").map((m) => m.id), ["MOD-0003"]);
    assert.deepEqual(agregarModelos(["MOD-0016"], visibles), ["MOD-0014", "MOD-0015", "MOD-0016"]);
    // Un modelo de baja no se agrega en bloque.
    assert.deepEqual(agregarModelos([], buscarModelos(CLASIFICACION.modelos, "iphone 8")), []);
    assert.deepEqual(alternarModelo(["MOD-0016", "MOD-0014"], "MOD-0015"), [
      "MOD-0014",
      "MOD-0015",
      "MOD-0016",
    ]);
    assert.deepEqual(alternarModelo(["MOD-0014"], "MOD-0014"), []);
  });

  test("nombre repetido entre pares, sin distinguir mayúsculas ni espacios", () => {
    const fabricantes = CLASIFICACION.fabricantes;
    assert.equal(nombreRepetido(fabricantes, "  ACME ")?.id, "FAB-001");
    assert.equal(nombreRepetido(fabricantes, "Acme", "FAB-001"), null);
    assert.equal(nombreRepetido(fabricantes, ""), null);
  });
});

describe("Configuración", () => {
  test("categorías y fabricantes con el permiso de insumos, con su auditoría", () => {
    const usuario = {
      rol: "RECEPCION" as const,
      roles: ["RECEPCION" as const],
      permisos: ["INSUMO_GESTIONAR"],
      activo: true,
    };
    assert.deepEqual(
      seccionesPermitidas(usuario).map((s) => s.id),
      ["insumos", "categorias-insumo", "fabricantes-repuesto"],
    );
    assert.equal(ENTIDAD_DE_SECCION["categorias-insumo"], "CATEGORIA_INSUMO");
    assert.equal(ENTIDAD_DE_SECCION["fabricantes-repuesto"], "FABRICANTE_REPUESTO");
  });
});
