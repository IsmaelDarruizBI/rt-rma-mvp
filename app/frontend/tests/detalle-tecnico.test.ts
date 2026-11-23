/**
 * BF-07 (D-01): quién ve la información técnica en el detalle de la Orden.
 * Permiso configurable DETALLE_TECNICO_CONSULTAR; sin la lista de permisos
 * de la sesión rigen sus predeterminados (los mismos que en el backend).
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { RolUsuario } from "../src/types/api.ts";
import {
  PERMISO_DETALLE_TECNICO,
  veDetalleTecnico,
} from "../src/features/ordenes-reparacion/detalleTecnico.ts";

const usuario = (
  rol: RolUsuario,
  { roles, permisos, activo = true }: {
    roles?: RolUsuario[];
    permisos?: string[];
    activo?: boolean;
  } = {},
) => ({ rol, roles, permisos, activo });

test("predeterminados: Recepción no ve lo técnico; Taller, Coordinación y Administración sí", () => {
  assert.equal(veDetalleTecnico(usuario("RECEPCION")), false);
  assert.equal(veDetalleTecnico(usuario("TECNICO")), true);
  assert.equal(veDetalleTecnico(usuario("COORDINADOR_RMA")), true);
  assert.equal(veDetalleTecnico(usuario("ADMINISTRADOR")), true);
});

test("con varios roles rige la unión", () => {
  assert.equal(
    veDetalleTecnico(usuario("RECEPCION", { roles: ["RECEPCION", "TECNICO"] })),
    true,
  );
});

test("con la lista de permisos de la sesión decide la configuración", () => {
  // Administración se lo habilitó a Recepción.
  assert.equal(
    veDetalleTecnico(
      usuario("RECEPCION", { permisos: [PERMISO_DETALLE_TECNICO] }),
    ),
    true,
  );
  // Se lo quitó a Técnico: ya no lo ve aunque su rol lo tenga por defecto.
  assert.equal(
    veDetalleTecnico(usuario("TECNICO", { permisos: ["ORDENES_CONSULTAR"] })),
    false,
  );
});

test("sin sesión o con el usuario inactivo no ve nada técnico", () => {
  assert.equal(veDetalleTecnico(null), false);
  assert.equal(veDetalleTecnico(usuario("TECNICO", { activo: false })), false);
});
