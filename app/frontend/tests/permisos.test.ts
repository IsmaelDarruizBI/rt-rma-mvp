/**
 * Quién puede ejecutar una acción. Los mismos casos que
 * `test_puede_ejecutar_como_valida_el_servidor` (backend): las dos reglas
 * tienen que coincidir.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { RolUsuario } from "../src/types/api.ts";
import { puedeEjecutar } from "../src/features/ordenes-reparacion/permisos.ts";

const usuario = (id: string, rol: RolUsuario, activo = true) => ({
  id,
  rol,
  activo,
});
const RECEPCION = usuario("RECEP-001", "RECEPCION");
const TECNICO = usuario("TECH-001", "TECNICO");
const OTRO_TECNICO = usuario("TECH-002", "TECNICO");
const ADMINISTRACION = usuario("ADMIN-001", "ADMINISTRADOR");
const INACTIVO = usuario("RECEP-009", "RECEPCION", false);

const accion = (
  roles: RolUsuario[],
  { requiere_actor = true, usuario_id = null as string | null } = {},
) => ({ roles, requiere_actor, usuario_id });

type Caso = [
  string,
  ReturnType<typeof accion>,
  ReturnType<typeof usuario>,
  boolean,
];

const CASOS: Caso[] = [
  ["sistema", accion([], { requiere_actor: false }), INACTIVO, true],
  ["rol autorizado", accion(["RECEPCION"]), RECEPCION, true],
  ["otro rol", accion(["RECEPCION"]), TECNICO, false],
  [
    "varios roles sin jerarquía",
    accion(["COORDINADOR_RMA", "RECEPCION"]),
    RECEPCION,
    true,
  ],
  ["sin rol definido", accion([]), ADMINISTRACION, true],
  [
    "titular de la toma",
    accion(["TECNICO"], { usuario_id: "TECH-001" }),
    TECNICO,
    true,
  ],
  [
    "otro técnico",
    accion(["TECNICO"], { usuario_id: "TECH-001" }),
    OTRO_TECNICO,
    false,
  ],
  ["usuario inactivo", accion(["RECEPCION"]), INACTIVO, false],
  ["inactivo sin rol definido", accion([]), INACTIVO, false],
];

test("la misma regla que el servidor", () => {
  for (const [nombre, laAccion, elUsuario, esperado] of CASOS) {
    assert.equal(puedeEjecutar(laAccion, elUsuario), esperado, nombre);
  }
  assert.equal(puedeEjecutar(accion(["RECEPCION"]), null), false);
});
