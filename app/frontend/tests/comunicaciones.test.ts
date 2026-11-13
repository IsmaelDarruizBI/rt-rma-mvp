/**
 * Comunicaciones (DEC-MI-08): el estado nunca dice «entregado» ni «leído».
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { ComunicacionCliente } from "../src/types/api.ts";
import {
  estadoDeComunicacion,
  textoConsentimiento,
} from "../src/features/ordenes-reparacion/comunicaciones.ts";

const base: ComunicacionCliente = {
  id: "COM-001",
  plantilla_codigo: "INGRESO",
  finalidad: "OPERATIVA",
  canal: "WHATSAPP",
  destinatario: "3415550000",
  mensaje: "Hola",
  usuario_id: "RECEP-001",
  fecha: "2026-11-13T12:00:00Z",
  confirmacion: null,
};

test("abrir WhatsApp no es enviar; la confirmación es del usuario", () => {
  const estados = [
    estadoDeComunicacion(base),
    estadoDeComunicacion({
      ...base,
      confirmacion: {
        enviado: true,
        usuario_id: "RECEP-001",
        fecha: base.fecha,
        nota: null,
      },
    }),
    estadoDeComunicacion({
      ...base,
      confirmacion: {
        enviado: false,
        usuario_id: "RECEP-001",
        fecha: base.fecha,
        nota: null,
      },
    }),
  ];
  assert.match(estados[0], /falta confirmar/);
  assert.match(estados[1], /confirmado por el usuario/);
  assert.match(estados[2], /No se envió/);
  for (const estado of estados) {
    assert.doesNotMatch(estado, /entregad|leíd|leid/i);
  }
});

test("consentimiento sin registro, otorgado o revocado", () => {
  assert.equal(textoConsentimiento(null), "Sin registro");
  assert.equal(textoConsentimiento(true), "Otorgado");
  assert.equal(textoConsentimiento(false), "Rechazado o revocado");
});
