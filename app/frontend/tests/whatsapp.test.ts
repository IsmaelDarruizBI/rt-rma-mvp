/**
 * Compartir el comprobante de autorización por WhatsApp: teléfono para
 * wa.me, mensaje y enlace.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type {
  ContenidoAutorizacion,
  ContenidoIngreso,
} from "../src/types/api.ts";
import {
  enlaceWhatsapp,
  mensajeComprobante,
  telefonoParaWhatsapp,
} from "../src/features/ordenes-reparacion/whatsapp.ts";

test("celulares argentinos con 0, 15, +54 o 9", () => {
  for (const escrito of [
    "0341 15 555-1234",
    "341 155551234",
    "3415551234",
    "+54 9 341 555-1234",
    "+54 341 555 1234",
    "0054 9 341 5551234",
    "549 341 5551234",
  ]) {
    assert.equal(telefonoParaWhatsapp(escrito), "5493415551234", escrito);
  }
  assert.equal(telefonoParaWhatsapp("011 15 1234-5678"), "5491112345678");
  assert.equal(telefonoParaWhatsapp("(2214) 15-123456"), "5492214123456");
});

test("otro país con + se usa tal cual", () => {
  assert.equal(telefonoParaWhatsapp("+598 99 123 456"), "59899123456");
  assert.equal(telefonoParaWhatsapp("+1 (305) 555-0100"), "13055550100");
});

test("sin un número válido no se inventa uno", () => {
  for (const escrito of [null, undefined, "", "341-1", "000 000 0000", "12"]) {
    assert.equal(telefonoParaWhatsapp(escrito), null, String(escrito));
  }
});

test("el enlace lleva el mensaje codificado y el teléfono si lo hay", () => {
  assert.equal(
    enlaceWhatsapp("5493415551234", "Hola & chau"),
    "https://wa.me/5493415551234?text=Hola%20%26%20chau",
  );
  assert.equal(enlaceWhatsapp(null, "Hola"), "https://wa.me/?text=Hola");
});

const CONTENIDO: ContenidoAutorizacion = {
  tipo: "COMPROBANTE_AUTORIZACION",
  empresa: {
    nombre: "Rosario Tecno",
    razon_social: null,
    cuit: null,
    direccion: null,
    telefono: null,
    email: null,
    condiciones_garantia: null,
  },
  orden_id: "OR-000007",
  origen: "CLIENTE_EXTERNO",
  fecha_ingreso: "2026-10-15T12:00:00Z",
  cliente: { id: "CLI-1", nombre: "Ana Pérez", telefono: "341 5551234", email: null },
  referencia_rt: null,
  equipo: {
    id: "EQ-1",
    marca: "Apple",
    modelo: "iPhone 14",
    falla_reportada: "No carga.",
    imei: null,
    numero_serie: null,
  },
  orden_origen_id: null,
  detalles_reclamados: [],
  trabajos: [
    {
      detalle_id: "DET-001",
      tipo_reparacion_id: "TR-001",
      nombre: "Cambio de batería",
      precio: "85000",
      detalle_origen_id: null,
      version_definicion: 1,
      autorizado_en: "2026-10-15T12:30:00Z",
      canal: "WHATSAPP",
      registrado_por: null,
    },
  ],
  total_autorizado: "85000",
  leyenda: "No es un comprobante de pago.",
};

test("el mensaje nombra la orden, lo autorizado y que no es un pago", () => {
  const mensaje = mensajeComprobante(CONTENIDO);

  assert.match(mensaje, /^Hola Ana! /);
  assert.match(mensaje, /orden OR-000007 \(Apple iPhone 14\)/);
  assert.match(mensaje, /• Cambio de batería: \$\s?85\.000/);
  assert.match(mensaje, /Total autorizado: \$\s?85\.000/);
  assert.match(mensaje, /No es un comprobante de pago\./);
  assert.doesNotMatch(mensaje, /DET-|enviado|recibido/);
});

const INGRESO: ContenidoIngreso = {
  ...CONTENIDO,
  tipo: "COMPROBANTE_INGRESO",
  estado_fisico: "Sin golpes.",
  accesorios: ["Cargador"],
  observaciones: null,
  notas: [],
  checkin: true,
  registrado_por: null,
  recepcion_fisica: "EN_CUSTODIA",
  confirmada_por: null,
  confirmada_en: null,
  subtotal: "85000",
  descuento: { descripcion: "10 %", motivo: "Promo", importe: "8500" },
  total: "76500",
};

test("el comprobante de ingreso: con descuento, sin decir que se recibió", () => {
  const mensaje = mensajeComprobante(INGRESO);

  assert.match(mensaje, /comprobante de ingreso y autorización de la orden OR-000007/);
  assert.match(mensaje, /Subtotal: \$\s?85\.000/);
  assert.match(mensaje, /Descuento \(10 %\): -\$\s?8\.500/);
  assert.match(mensaje, /Total autorizado: \$\s?76\.500/);
  assert.match(mensaje, /No es un comprobante de pago\./);
  assert.doesNotMatch(mensaje, /DET-|enviado|recibido|firm/);
});
