/**
 * Presentación del ingreso inicial: antes del comprobante de ingreso los
 * trabajos se ven «Pendiente de comprobante de ingreso» y, una vez
 * generado, «Autorizado». Las autorizaciones posteriores conservan su
 * etiqueta. Los estados internos no cambian: lo deriva el backend.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { TrabajoBandeja } from "../src/types/api.ts";
import { estadoDeTrabajo } from "../src/features/ordenes-reparacion/bandejas.ts";
import { etiquetaAutorizacion } from "../src/features/ordenes-reparacion/etiquetas.ts";

test("antes del comprobante de ingreso", () => {
  assert.equal(
    etiquetaAutorizacion({
      estado_autorizacion: "PENDIENTE",
      pendiente_comprobante_ingreso: true,
      autorizado_en_ingreso: false,
    }),
    "Pendiente de comprobante de ingreso",
  );
});

test("autorizado con el comprobante de ingreso", () => {
  assert.equal(
    etiquetaAutorizacion({
      estado_autorizacion: "AUTORIZADO",
      pendiente_comprobante_ingreso: false,
      autorizado_en_ingreso: true,
    }),
    "Autorizado",
  );
});

test("las autorizaciones posteriores no cambian", () => {
  assert.equal(
    etiquetaAutorizacion({
      estado_autorizacion: "PENDIENTE",
      pendiente_comprobante_ingreso: false,
      autorizado_en_ingreso: false,
    }),
    "Esperando al cliente",
  );
  assert.equal(
    etiquetaAutorizacion({
      estado_autorizacion: "AUTORIZADO",
      pendiente_comprobante_ingreso: false,
      autorizado_en_ingreso: false,
    }),
    "Autorizado por el cliente",
  );
  // Una respuesta de un backend anterior, sin los campos nuevos.
  assert.equal(
    etiquetaAutorizacion({ estado_autorizacion: "RECHAZADO" }),
    "Rechazado por el cliente",
  );
});

test("en las bandejas", () => {
  const trabajo: TrabajoBandeja = {
    detalle_id: "DET-001",
    nombre: "Cambio de batería",
    estado: "DEFINIDO",
    trabajable: false,
    pendiente_autorizacion: true,
    condicion: "SIN_BLOQUEO",
    en_curso: false,
    faltantes: [],
  };
  assert.equal(estadoDeTrabajo(trabajo), "esperando autorización");
  assert.equal(
    estadoDeTrabajo({ ...trabajo, pendiente_comprobante_ingreso: true }),
    "pendiente de comprobante de ingreso",
  );
});
