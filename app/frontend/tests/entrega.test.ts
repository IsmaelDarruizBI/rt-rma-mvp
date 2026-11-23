/**
 * Entrega del equipo (ajustes funcionales, bloque 2).
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  checkinPendiente,
  descripcionQuienRetira,
  faltantesDelRetiro,
  textoRetiro,
  tituloComprobanteEntrega,
} from "../src/features/ordenes-reparacion/entrega.ts";

const dia = (iso: string) => iso.slice(0, 10);

test("DEC-AJ-03: lista para retirar sin aviso, que es opcional", () => {
  assert.equal(
    textoRetiro("2026-11-01T10:00:00Z", null, dia),
    "Lista para retirar desde 2026-11-01 · sin aviso al cliente (es opcional).",
  );
});

test("DEC-AJ-03: la fecha del aviso se muestra aparte", () => {
  assert.equal(
    textoRetiro("2026-11-01T10:00:00Z", "2026-11-03T12:00:00Z", dia),
    "Lista para retirar desde 2026-11-01 · aviso al cliente: 2026-11-03.",
  );
});

test("DEC-AJ-04: un solo comprobante de entrega y garantía", () => {
  assert.equal(
    tituloComprobanteEntrega({
      tipo_entrega: "REPARACION_TERMINADA",
      entrega_y_garantia: true,
    }),
    "Comprobante de entrega y garantía",
  );
  // Los emitidos antes conservan su título.
  assert.equal(
    tituloComprobanteEntrega({ tipo_entrega: "REPARACION_TERMINADA" }),
    "Comprobante de entrega",
  );
  assert.equal(
    tituloComprobanteEntrega({
      tipo_entrega: "DEVOLUCION_SIN_REPARACION",
      entrega_y_garantia: false,
    }),
    "Comprobante de devolución sin reparación",
  );
});

test("DEC-AJ-04: el formulario de entrega pide el check-in solo si falta", () => {
  const accion = (codigo: string) =>
    ({ codigo }) as Parameters<typeof checkinPendiente>[0]["acciones_disponibles"][number];
  const recepcion = (checkin: boolean | null) =>
    ({ datos: { checkin } }) as Parameters<typeof checkinPendiente>[0]["recepcion"];
  assert.equal(
    checkinPendiente({
      acciones_disponibles: [accion("ENTREGAR"), accion("REGISTRAR_CHECKIN")],
      recepcion: recepcion(null),
    }),
    true,
  );
  assert.equal(
    checkinPendiente({
      acciones_disponibles: [accion("ENTREGAR"), accion("REGISTRAR_CHECKIN")],
      recepcion: recepcion(true),
    }),
    false,
  );
  // Sin check-in en el Origen (garantía RMA, sin reparación): no se pide.
  assert.equal(
    checkinPendiente({
      acciones_disponibles: [accion("ENTREGAR")],
      recepcion: recepcion(null),
    }),
    false,
  );
});

test("DEC-AJ-09: si retira el titular no se pide nada más", () => {
  assert.deepEqual(
    faltantesDelRetiro({ otraPersona: false, nombre: "", apellido: "", telefono: "" }),
    [],
  );
});

test("DEC-AJ-09: otra persona exige nombre, apellido y teléfono", () => {
  assert.deepEqual(
    faltantesDelRetiro({ otraPersona: true, nombre: " ", apellido: "", telefono: "" }),
    ["nombre", "apellido", "teléfono"],
  );
  assert.deepEqual(
    faltantesDelRetiro({
      otraPersona: true,
      nombre: "Ana",
      apellido: "López",
      telefono: "341-555",
    }),
    [],
  );
});

test("DEC-AJ-09: el comprobante dice quién retiró", () => {
  assert.equal(
    descripcionQuienRetira({
      recibido_por: "Ana López",
      retira_otra_persona: true,
      telefono_receptor: "341-555",
    }),
    "Ana López (otra persona · tel. 341-555)",
  );
  assert.equal(
    descripcionQuienRetira({ recibido_por: "María Gómez", retira_otra_persona: false }),
    "María Gómez (titular)",
  );
  // Una entrega anterior conserva lo que se cargó.
  assert.equal(
    descripcionQuienRetira({
      recibido_por: "María Gómez",
      identificacion_receptor: "DNI 28111222",
      retira_otra_persona: null,
    }),
    "María Gómez · DNI 28111222",
  );
  assert.equal(descripcionQuienRetira({ recibido_por: null }), "—");
});
