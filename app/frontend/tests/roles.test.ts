/**
 * Varios roles por usuario y permisos (DC27A, DC08): la pantalla suma los
 * roles y, si la API manda los permisos de hoy, se guía por ellos.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { puedeEjecutar } from "../src/features/ordenes-reparacion/permisos.ts";
import { pendienteDelSector } from "../src/features/ordenes-reparacion/listado.ts";
import { puede, rolesDe, tieneAlguno, tieneRol } from "../src/lib/roles.ts";
import type { OrdenResumen, Usuario } from "../src/types/api.ts";

const doble: Usuario = {
  id: "TECH-009",
  nombre: "Doble",
  rol: "TECNICO",
  roles: ["TECNICO", "RECEPCION"],
  activo: true,
  permisos: ["EJECUCION", "ORDEN_CREAR"],
};
const anterior: Usuario = {
  id: "RECEP-001",
  nombre: "Recep",
  rol: "RECEPCION",
  activo: true,
};

test("un usuario anterior tiene su único rol", () => {
  assert.deepEqual(rolesDe(anterior), ["RECEPCION"]);
  assert.equal(tieneRol(anterior, "TECNICO"), false);
});

test("con varios roles se suman", () => {
  assert.equal(tieneRol(doble, "RECEPCION"), true);
  assert.equal(tieneAlguno(doble, ["ADMINISTRADOR", "TECNICO"]), true);
  assert.equal(tieneAlguno(doble, ["ADMINISTRADOR"]), false);
});

test("los permisos de la API mandan sobre los roles predeterminados", () => {
  assert.equal(puede(doble, "ORDEN_CREAR"), true);
  // Configurado sin su rol: aunque el predeterminado lo incluya.
  assert.equal(puede(doble, "STOCK_GESTIONAR", ["TECNICO"]), false);
  // Sin la lista (API anterior): los predeterminados.
  assert.equal(puede(anterior, "CLIENTE_BUSCAR", ["RECEPCION"]), true);
  assert.equal(puede({ ...anterior, activo: false }, "X", ["RECEPCION"]), false);
});

test("una acción de cualquiera de sus roles se ofrece", () => {
  const accion = {
    codigo: "APROBAR_CONTROL",
    roles: ["RECEPCION" as const],
    requiere_actor: true,
    usuario_id: null,
  };
  assert.equal(puedeEjecutar(accion, doble), true);
  assert.equal(puedeEjecutar(accion, { ...doble, roles: ["TECNICO"] }), false);
});

test("mi sector incluye lo pendiente de cualquiera de mis roles", () => {
  const orden = {
    cerrada: false,
    situacion: { roles: ["RECEPCION"] },
  } as unknown as OrdenResumen;
  assert.equal(pendienteDelSector(orden, ["TECNICO", "RECEPCION"]), true);
  assert.equal(pendienteDelSector(orden, "TECNICO"), false);
});
