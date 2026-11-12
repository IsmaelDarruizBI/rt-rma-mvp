/**
 * Iteración 1 (V1.4): nombres de acciones nuevas o que cambian de sentido.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  NOMBRE_ACCION,
  nombreDeAccion,
} from "../src/features/ordenes-reparacion/etiquetas.ts";
import type { Accion } from "../src/types/api.ts";

function accion(codigo: string, etiqueta: string): Accion {
  return {
    codigo,
    etiqueta,
    roles: ["ADMINISTRADOR"],
    detalle_id: null,
    ejecucion_id: null,
    requiere_actor: true,
    usuario_id: null,
    pago_id: null,
    bloqueo: null,
    usuario_excluido_id: null,
  } as Accion;
}

test("la cortesía tiene nombre propio (DC11, DEC-IT1-02)", () => {
  assert.equal(NOMBRE_ACCION.OTORGAR_CORTESIA, "Otorgar una cortesía");
  assert.equal(
    nombreDeAccion(accion("OTORGAR_CORTESIA", "Otorgar una cortesia")),
    "Otorgar una cortesía",
  );
  assert.equal(
    nombreDeAccion(accion("APLICAR_DESCUENTO", "Aplicar un descuento")),
    "Aplicar un descuento",
  );
});

test("con la cortesía vigente, su acción la modifica o la quita", () => {
  assert.equal(
    nombreDeAccion(
      accion("OTORGAR_CORTESIA", "Modificar o quitar la cortesia"),
    ),
    "Modificar o quitar la cortesía",
  );
});

test("un ajuste comercial reintentado lleva su clave (no se duplica)", async () => {
  const { llevaClave } = await import("../src/api/idempotencia.ts");
  assert.equal(llevaClave("/api/orders/OR-000001/discount"), true);
});

test("con el desistimiento pendiente, interrumpir es la acción de la tarea", async () => {
  const { claveDeAccion, organizarBarra, pendientesDe } = await import(
    "../src/features/ordenes-reparacion/acciones.ts"
  );
  const interrumpir = { ...accion("INTERRUMPIR_EJECUCION", "Interrumpir"), roles: ["TECNICO"] } as Accion;
  const barra = organizarBarra(
    [{ clave: claveDeAccion(interrumpir), accion: interrumpir }],
    [claveDeAccion(interrumpir)],
  );
  assert.deepEqual(
    barra.visibles.map((x) => x.accion.codigo),
    ["INTERRUMPIR_EJECUCION"],
  );
  const orden = {
    cerrada: false,
    acciones_disponibles: [interrumpir],
    acciones_cancelacion: [],
    acciones_autorizacion: [],
    acciones_financieras: [],
    acciones_custodia: [],
    acciones_complementarias: [],
    situacion: {
      descripcion: "",
      tareas: [
        {
          titulo: "Interrumpir el trabajo",
          responsable: "Técnico",
          motivo: "",
          acciones: [interrumpir],
        },
      ],
      avisos: [],
    },
  } as unknown as Parameters<typeof pendientesDe>[0];
  const tecnico = { id: "u1", rol: "TECNICO", activo: true } as Parameters<typeof pendientesDe>[1];
  const [tarea] = pendientesDe(orden, tecnico);
  assert.deepEqual(
    tarea.acciones.map((a) => a.codigo),
    ["INTERRUMPIR_EJECUCION"],
  );
});
