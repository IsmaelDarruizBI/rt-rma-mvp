/**
 * Cancelación de la Orden (DC31): lo que se muestra antes de confirmarla.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { Orden } from "../src/types/api.ts";
import {
  avisoCancelacionOrden,
  motivosDeBloqueo,
  trabajosACancelar,
} from "../src/features/ordenes-reparacion/cancelacion.ts";
import { organizarBarra } from "../src/features/ordenes-reparacion/acciones.ts";

function orden(...estados: string[]): Pick<Orden, "reparaciones_detail"> {
  return {
    reparaciones_detail: estados.map((estado, i) => ({
      id: `DET-00${i + 1}`,
      estado,
      tipo_reparacion_nombre: `Trabajo ${i + 1}`,
    })),
  } as unknown as Pick<Orden, "reparaciones_detail">;
}

test("solo se cancelan los trabajos pendientes", () => {
  assert.deepEqual(
    trabajosACancelar(orden("DEFINIDO", "CANCELADO", "DEFINIDO")),
    ["Trabajo 1", "Trabajo 3"],
  );
  assert.deepEqual(trabajosACancelar(orden("CANCELADO")), []);
});

test("el aviso siempre dice que es definitiva", () => {
  assert.match(avisoCancelacionOrden(orden("DEFINIDO", "DEFINIDO")), /^Se cancelan 2 trabajos pendientes\./);
  assert.match(avisoCancelacionOrden(orden("DEFINIDO")), /^Se cancela 1 trabajo pendiente\./);
  const sinPendientes = avisoCancelacionOrden(orden("CANCELADO"));
  assert.match(sinPendientes, /^La Orden queda CANCELADA y cerrada/);
  assert.match(sinPendientes, /no admite ninguna acción/);
});

test("los motivos del bloqueo se muestran uno por línea", () => {
  assert.deepEqual(motivosDeBloqueo(null), []);
  assert.deepEqual(
    motivosDeBloqueo(
      "No se puede cancelar todavia: hay reservas de insumos sin conciliar; el equipo esta en el local: registra su devolucion antes de cancelar.",
    ),
    [
      "Hay reservas de insumos sin conciliar",
      "El equipo esta en el local: registra su devolucion antes de cancelar",
    ],
  );
});

test("devolver sin reparar: visible si es la tarea, en el menú si no", () => {
  const accion = { codigo: "REGISTRAR_DEVOLUCION" } as never;
  const habilitadas = [{ clave: "REGISTRAR_DEVOLUCION|||", accion }];
  assert.equal(organizarBarra(habilitadas, ["REGISTRAR_DEVOLUCION|||"]).visibles.length, 1);
  const barra = organizarBarra(habilitadas, []);
  assert.equal(barra.visibles.length, 0);
  assert.equal(barra.menu.length, 1);
});
