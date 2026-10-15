/**
 * Presentación de las bandejas: las arma el backend; acá se prueba que se
 * muestren tal cual (contadores, separación, textos y estación propuesta).
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import type {
  Bandeja,
  ItemBandeja,
  OrdenResumen,
  TrabajoBandeja,
} from "../src/types/api.ts";
import {
  antiguedadDe,
  estacionPropuesta,
  estadoDeTrabajo,
  lineaDeTarea,
  separarBandejas,
  totalPendiente,
  trabajosDe,
} from "../src/features/ordenes-reparacion/bandejas.ts";

function trabajo(datos: Partial<TrabajoBandeja>): TrabajoBandeja {
  return {
    detalle_id: "DET-001",
    nombre: "Cambio de batería",
    estado: "DEFINIDO",
    trabajable: true,
    pendiente_autorizacion: false,
    condicion: "SIN_BLOQUEO",
    en_curso: false,
    faltantes: [],
    ...datos,
  };
}

function item(datos: Partial<ItemBandeja> = {}): ItemBandeja {
  return {
    orden: {
      id: "OR-000001",
      created_at: "2026-10-01T10:00:00Z",
    } as OrdenResumen,
    falla: "No carga.",
    tarea: "Confirmar la recepción física del equipo",
    responsable: "Recepción",
    puede_resolver: true,
    desde: null,
    condiciones: [],
    trabajos: [],
    estacion_id: null,
    tomada_desde: null,
    trabajo_en_curso: null,
    en_curso_desde: null,
    credito: "0",
    estaciones: [],
    puede_tomar: false,
    ...datos,
  };
}

function bandeja(
  codigo: string,
  tipo: Bandeja["tipo"],
  ordenes: ItemBandeja[],
): Bandeja {
  return {
    codigo,
    titulo: codigo,
    descripcion: "",
    tipo,
    cantidad: ordenes.length,
    destino: null,
    ordenes,
    insumos: [],
  };
}

describe("bandejas", () => {
  const confirmar = bandeja("RECEPCION_FISICA", "TAREAS", [item(), item()]);
  const control = bandeja("CONTROL", "TAREAS", []);
  const otros = bandeja("EN_OTROS_SECTORES", "SEGUIMIENTO", [item()]);

  test("separa lo pendiente, lo vacío y el seguimiento", () => {
    const { pendientes, vacias, seguimiento } = separarBandejas([
      confirmar,
      control,
      otros,
    ]);
    assert.deepEqual(
      [pendientes, vacias, seguimiento].map((g) => g.map((b) => b.codigo)),
      [["RECEPCION_FISICA"], ["CONTROL"], ["EN_OTROS_SECTORES"]],
    );
    // El contador es lo que lista cada bandeja.
    for (const b of [confirmar, control, otros]) {
      assert.equal(b.cantidad, b.ordenes.length + b.insumos.length);
    }
    // El seguimiento no suma pendientes.
    assert.equal(totalPendiente([confirmar, control, otros]), 2);
  });

  test("lo propio se dice tal cual; lo de otro, con quién lo resuelve", () => {
    assert.equal(
      lineaDeTarea(item(), "RECEPCION_FISICA"),
      "Confirmar la recepción física del equipo",
    );
    assert.equal(
      lineaDeTarea(
        item({ puede_resolver: false, responsable: "Técnico", tarea: "Tomar" }),
        "EN_OTROS_SECTORES",
      ),
      "Le toca a Técnico: Tomar",
    );
    assert.equal(
      lineaDeTarea(item({ tarea: "Iniciar la reparación" }), "MIS_TOMADAS"),
      "Próximo paso: Iniciar la reparación",
    );
    assert.equal(
      lineaDeTarea(
        item({
          puede_resolver: false,
          responsable: "Recepción",
          tarea: "Confirmar la recepción física del equipo",
        }),
        "MIS_TOMADAS",
      ),
      "Esperando a Recepción: Confirmar la recepción física del equipo",
    );
    assert.equal(lineaDeTarea(item({ tarea: null }), "SALDOS"), null);
  });

  test("la antigüedad usa la toma, la situación o el ingreso", () => {
    const tomada = item({ tomada_desde: "2026-10-02T10:00:00Z" });
    assert.deepEqual(antiguedadDe(tomada, "MIS_TOMADAS"), {
      texto: "Tomada",
      fecha: "2026-10-02T10:00:00Z",
    });
    assert.deepEqual(antiguedadDe(item({ desde: "2026-10-03T00:00:00Z" }), "CONTROL"), {
      texto: "En esta situación",
      fecha: "2026-10-03T00:00:00Z",
    });
    assert.deepEqual(antiguedadDe(item(), "AVISO"), {
      texto: "Ingresó",
      fecha: "2026-10-01T10:00:00Z",
    });
  });
});

describe("trabajos y cola", () => {
  const trabajos = [
    trabajo({ detalle_id: "DET-001", en_curso: true, estado: "EN_PROGRESO" }),
    trabajo({
      detalle_id: "DET-002",
      trabajable: false,
      pendiente_autorizacion: true,
    }),
    trabajo({
      detalle_id: "DET-003",
      trabajable: false,
      condicion: "BLOQUEADO_POR_RECURSOS",
      faltantes: ["Pantalla"],
    }),
  ];

  test("en el taller no se listan los pendientes de autorización", () => {
    assert.deepEqual(
      trabajosDe(item({ trabajos }), "MIS_TOMADAS").map((t) => t.detalle_id),
      ["DET-001", "DET-003"],
    );
    // En la cola, solo lo que se puede hacer.
    assert.deepEqual(
      trabajosDe(item({ trabajos }), "COLA").map((t) => t.detalle_id),
      ["DET-001"],
    );
  });

  test("el estado de cada trabajo sale de los datos del backend", () => {
    assert.deepEqual(trabajos.map(estadoDeTrabajo), [
      "en reparación",
      "esperando autorización",
      "sin repuestos",
    ]);
    assert.equal(estadoDeTrabajo(trabajo({})), "para hacer");
  });

  test("la cola propone la primera estación compatible", () => {
    assert.equal(
      estacionPropuesta(
        item({
          estaciones: [
            { id: "EST-002", nombre: "Mesa 2" },
            { id: "EST-001", nombre: "Mesa 1" },
          ],
        }),
      ),
      "EST-002",
    );
    assert.equal(estacionPropuesta(item()), null);
  });
});
