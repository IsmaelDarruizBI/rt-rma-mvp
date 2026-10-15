/**
 * Búsqueda, filtros y orden del listado de Órdenes (funciones puras).
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import type { OrdenResumen } from "../src/types/api.ts";
import {
  FILTROS_INICIALES,
  type FiltrosListado,
  aplicarListado,
  coincide,
  filtrarOrdenes,
  filtrosActivos,
  filtrosValidos,
  normalizar,
  ordenarOrdenes,
  pendienteDelSector,
} from "../src/features/ordenes-reparacion/listado.ts";

function resumen(datos: Partial<OrdenResumen> & { id: string }): OrdenResumen {
  return {
    origen: "CLIENTE_EXTERNO",
    orden_origen_id: null,
    estado_workflow: "REQUERIMIENTO",
    current_process: "PROC-REP-110",
    prioridad: 0,
    prioridad_texto: null,
    posicion_por_prioridad: 0,
    cliente_nombre: "Ana Pérez",
    cliente_telefono: "341-555 0101",
    equipo: "Samsung Galaxy A54",
    equipo_marca: "Samsung",
    equipo_modelo: "Galaxy A54",
    imei: "356938035643809",
    numero_serie: "R58T12AB",
    referencia_rt: null,
    total: "0.00",
    saldo: "0.00",
    estado_pago: "PENDIENTE",
    cobrable: true,
    cerrada: false,
    tecnico_id: null,
    situacion: {
      codigo: "PENDIENTE_DEFINICION",
      titulo: "Pendiente de definición",
      responsable: "Recepción",
      roles: ["RECEPCION"],
      titular_id: null,
      desde: null,
    },
    created_at: "2026-10-01T10:00:00Z",
    updated_at: "2026-10-01T10:00:00Z",
    ...datos,
  };
}

const filtros = (cambios: Partial<FiltrosListado>): FiltrosListado => ({
  ...FILTROS_INICIALES,
  ...cambios,
});

const ids = (ordenes: OrdenResumen[]) => ordenes.map((orden) => orden.id);

describe("búsqueda", () => {
  const ana = resumen({ id: "OR-000001" });
  const rt = resumen({
    id: "OR-000002",
    origen: "RT_INTERNO",
    cliente_nombre: "Equipo RT",
    cliente_telefono: null,
    equipo: "Motorola Moto G84",
    equipo_marca: "Motorola",
    equipo_modelo: "Moto G84",
    imei: null,
    numero_serie: "ZY22H",
    referencia_rt: "RT-ST-0042",
  });

  test("normaliza mayúsculas, acentos y espacios", () => {
    assert.equal(normalizar("  ÁNA   pÉrez "), "ana perez");
  });

  test("encuentra por cada campo, parcial y sin distinguir mayúsculas", () => {
    for (const busqueda of [
      "or-000001",
      "000001",
      "ana",
      "PEREZ",
      "3415550101",
      "555 0101",
      "samsung",
      "a54",
      "galaxy a54",
      "35693803",
      "r58t",
    ]) {
      assert.ok(coincide(ana, busqueda), busqueda);
    }
    assert.ok(coincide(rt, "rt-st-0042"));
    assert.ok(!coincide(rt, "samsung"));
    assert.ok(coincide(rt, "st 0042"));
    assert.ok(coincide(rt, "zy22"));
  });

  test("todas las palabras tienen que aparecer", () => {
    assert.ok(coincide(ana, "ana samsung"));
    assert.ok(!coincide(ana, "ana motorola"));
  });

  test("tolera espacios de más y búsqueda vacía", () => {
    assert.ok(coincide(ana, "   ana    perez  "));
    assert.ok(coincide(ana, "   "));
  });

  test("sin resultados", () => {
    assert.deepEqual(
      filtrarOrdenes([ana, rt], filtros({ texto: "iphone" }), null),
      [],
    );
  });
});

describe("filtros", () => {
  const abierta = resumen({ id: "OR-000001" });
  const enTaller = resumen({
    id: "OR-000002",
    estado_workflow: "EN_REPARACION",
    tecnico_id: "USR-TEC-01",
    situacion: {
      codigo: "EN_REPARACION",
      titulo: "En reparación",
      responsable: "Técnico",
      roles: ["TECNICO"],
      titular_id: "USR-TEC-01",
      desde: null,
    },
  });
  const rt = resumen({ id: "OR-000003", origen: "RT_INTERNO", cobrable: false });
  const cerrada = resumen({
    id: "OR-000004",
    estado_workflow: "ENTREGADA",
    cerrada: true,
    situacion: {
      codigo: "CERRADA",
      titulo: "Cerrada",
      responsable: null,
      roles: [],
      titular_id: null,
      desde: null,
    },
  });
  const todas = [abierta, enTaller, rt, cerrada];

  test("atajos: abiertas, cerradas y pendientes de mi sector", () => {
    assert.deepEqual(
      ids(filtrarOrdenes(todas, filtros({ rapido: "ABIERTAS" }), null)),
      ["OR-000001", "OR-000002", "OR-000003"],
    );
    assert.deepEqual(
      ids(filtrarOrdenes(todas, filtros({ rapido: "CERRADAS" }), null)),
      ["OR-000004"],
    );
    assert.deepEqual(
      ids(filtrarOrdenes(todas, filtros({ rapido: "MI_SECTOR" }), "TECNICO")),
      ["OR-000002"],
    );
    assert.deepEqual(
      ids(filtrarOrdenes(todas, filtros({ rapido: "MI_SECTOR" }), "RECEPCION")),
      ["OR-000001", "OR-000003"],
    );
    // Sin usuario elegido no hay sector.
    assert.deepEqual(
      filtrarOrdenes(todas, filtros({ rapido: "MI_SECTOR" }), null),
      [],
    );
  });

  test("una Orden cerrada nunca es pendiente de un sector", () => {
    const rara = { ...cerrada, situacion: { ...abierta.situacion! } };
    assert.equal(pendienteDelSector(rara, "RECEPCION"), false);
  });

  test("situación, estado, origen y técnico se combinan", () => {
    assert.deepEqual(
      ids(filtrarOrdenes(todas, filtros({ situacion: "EN_REPARACION" }), null)),
      ["OR-000002"],
    );
    assert.deepEqual(
      ids(filtrarOrdenes(todas, filtros({ sector: "TECNICO" }), null)),
      ["OR-000002"],
    );
    // El sector responsable no depende del usuario elegido.
    assert.deepEqual(
      ids(filtrarOrdenes(todas, filtros({ sector: "RECEPCION" }), "TECNICO")),
      ["OR-000001", "OR-000003"],
    );
    assert.deepEqual(
      ids(filtrarOrdenes(todas, filtros({ estado: "ENTREGADA" }), null)),
      ["OR-000004"],
    );
    assert.deepEqual(
      ids(filtrarOrdenes(todas, filtros({ origen: "RT_INTERNO" }), null)),
      ["OR-000003"],
    );
    assert.deepEqual(
      ids(filtrarOrdenes(todas, filtros({ tecnico: "USR-TEC-01" }), null)),
      ["OR-000002"],
    );
    assert.deepEqual(
      ids(
        filtrarOrdenes(
          todas,
          filtros({ rapido: "ABIERTAS", origen: "CLIENTE_EXTERNO", texto: "000002" }),
          null,
        ),
      ),
      ["OR-000002"],
    );
    assert.deepEqual(
      filtrarOrdenes(
        todas,
        filtros({ rapido: "CERRADAS", origen: "RT_INTERNO" }),
        null,
      ),
      [],
    );
  });

  test("cuenta solo los filtros del panel", () => {
    assert.equal(filtrosActivos(FILTROS_INICIALES), 0);
    assert.equal(
      filtrosActivos(filtros({ texto: "ana", rapido: "ABIERTAS", origen: "X" })),
      1,
    );
    assert.equal(
      filtrosActivos(filtros({ sector: "TECNICO", tecnico: "USR-TEC-01" })),
      2,
    );
  });

  test("lo guardado con otra forma vuelve al valor inicial", () => {
    assert.deepEqual(filtrosValidos(null), FILTROS_INICIALES);
    assert.deepEqual(filtrosValidos("basura"), FILTROS_INICIALES);
    assert.deepEqual(
      filtrosValidos({ texto: 5, rapido: "OTRO", orden: "AL_AZAR", origen: "RT_INTERNO", sector: "TECNICO" }),
      filtros({ origen: "RT_INTERNO", sector: "TECNICO" }),
    );
    const guardados = filtros({ texto: "ana", rapido: "CERRADAS", orden: "PRIORIDAD" });
    assert.deepEqual(filtrosValidos(JSON.parse(JSON.stringify(guardados))), guardados);
  });
});

describe("orden", () => {
  // `posicion_por_prioridad` es la que calcula el backend: 1 Urgente, 2,
  // 3, 4 y al final las Órdenes sin prioridad vigente, por ingreso.
  const vieja = resumen({
    id: "OR-000001",
    created_at: "2026-10-01T10:00:00Z",
    updated_at: "2026-10-05T10:00:00Z",
    prioridad: 2,
    prioridad_texto: "Prioridad 2 · Alta",
    posicion_por_prioridad: 1,
  });
  const media = resumen({
    id: "OR-000002",
    created_at: "2026-10-02T10:00:00Z",
    updated_at: "2026-10-02T10:00:00Z",
    prioridad: 1,
    prioridad_texto: "Prioridad 1 · Urgente",
    posicion_por_prioridad: 0,
  });
  const nueva = resumen({
    id: "OR-000003",
    created_at: "2026-10-03T10:00:00Z",
    updated_at: "2026-10-03T10:00:00Z",
    posicion_por_prioridad: 3,
  });
  // Mismo ingreso que «nueva»: desempata el número de Orden.
  const gemela = resumen({
    id: "OR-000004",
    created_at: "2026-10-03T10:00:00Z",
    updated_at: "2026-10-03T10:00:00Z",
    posicion_por_prioridad: 4,
  });
  const cerradaConPrioridad = resumen({
    id: "OR-000005",
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:00:00Z",
    prioridad: 1,
    cerrada: true,
    posicion_por_prioridad: 2,
  });
  const todas = [media, cerradaConPrioridad, nueva, vieja, gemela];

  test("ingreso más reciente primero (el predeterminado)", () => {
    assert.deepEqual(ids(ordenarOrdenes(todas, "INGRESO_RECIENTE")), [
      "OR-000004",
      "OR-000003",
      "OR-000002",
      "OR-000001",
      "OR-000005",
    ]);
  });

  test("ingreso más antiguo primero", () => {
    assert.deepEqual(ids(ordenarOrdenes(todas, "INGRESO_ANTIGUO")), [
      "OR-000005",
      "OR-000001",
      "OR-000002",
      "OR-000003",
      "OR-000004",
    ]);
  });

  test("prioridad: 1 antes que 2; cerradas y sin prioridad al final", () => {
    assert.deepEqual(ids(ordenarOrdenes(todas, "PRIORIDAD")), [
      "OR-000002",
      "OR-000001",
      "OR-000005",
      "OR-000003",
      "OR-000004",
    ]);
  });

  test("prioridad: se aplica el lugar del backend, sin reinterpretar", () => {
    // Aunque el número diga otra cosa, manda el criterio del backend.
    const primera = resumen({
      id: "OR-000010",
      prioridad: 4,
      posicion_por_prioridad: 0,
    });
    const segunda = resumen({
      id: "OR-000011",
      prioridad: 1,
      posicion_por_prioridad: 1,
    });
    assert.deepEqual(ids(ordenarOrdenes([segunda, primera], "PRIORIDAD")), [
      "OR-000010",
      "OR-000011",
    ]);
  });

  test("última actividad primero", () => {
    assert.deepEqual(ids(ordenarOrdenes(todas, "ACTIVIDAD")), [
      "OR-000001",
      "OR-000004",
      "OR-000003",
      "OR-000002",
      "OR-000005",
    ]);
  });

  test("es estable y no modifica la lista recibida", () => {
    const copia = [...todas];
    const primera = ids(ordenarOrdenes(todas, "PRIORIDAD"));
    assert.deepEqual(ids(ordenarOrdenes([...todas].reverse(), "PRIORIDAD")), primera);
    assert.deepEqual(todas, copia);
  });

  test("filtra y después ordena", () => {
    assert.deepEqual(
      ids(
        aplicarListado(
          todas,
          filtros({ rapido: "ABIERTAS", orden: "INGRESO_ANTIGUO" }),
          null,
        ),
      ),
      ["OR-000001", "OR-000002", "OR-000003", "OR-000004"],
    );
  });
});
