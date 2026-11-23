/**
 * DEC-AJ-10: formulario único del Ajuste Comercial, historial con
 * reversión y corrección, aviso de recálculo y comprobantes por trabajo.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  avisoRecalculo,
  baseDelDestino,
  esRevertible,
  etiquetaClase,
  historialDeAjustes,
  importeDeAjuste,
  lineasDeAjustes,
  operacionDe,
  textoAjusteDocumento,
  ultimoNoRevertido,
  vistaPrevia,
} from "../src/features/ordenes-reparacion/ajusteComercial.ts";
import { mensajeComprobante } from "../src/features/ordenes-reparacion/whatsapp.ts";
import type {
  ContenidoAutorizacion,
  Orden,
  RegistroDescuento,
} from "../src/types/api";

function registro(
  datos: Partial<RegistroDescuento> & { id: string; fecha: string },
): RegistroDescuento {
  return {
    tipo: "PORCENTAJE",
    valor: "10",
    motivo: "Acuerdo",
    usuario_id: "RECEP-001",
    clase: "DESCUENTO",
    detalle_id: null,
    ...datos,
  };
}

function orden(datos: Partial<Orden["resumen"]> = {}): Pick<
  Orden,
  "reparaciones_detail" | "resumen"
> {
  return {
    reparaciones_detail: [
      { id: "DET-001", precio: "80000", estado: "DEFINIDO" },
      { id: "DET-002", precio: "50000", estado: "DEFINIDO" },
    ] as unknown as Orden["reparaciones_detail"],
    resumen: {
      subtotal: "130000",
      descuento: null,
      ajustes_detalle: [],
      ...datos,
    } as unknown as Orden["resumen"],
  };
}

test("la clase se nombra en castellano", () => {
  assert.equal(etiquetaClase("CORTESIA"), "Cortesía");
  assert.equal(etiquetaClase("DESCUENTO"), "Descuento");
  assert.equal(etiquetaClase(undefined), "Descuento");
});

test("las cuentas son las del backend: porcentaje, importe y tope", () => {
  assert.equal(importeDeAjuste(50000, "PORCENTAJE", "10"), 5000);
  assert.equal(importeDeAjuste(333.33, "PORCENTAJE", "10"), 33.33);
  assert.equal(importeDeAjuste(1000, "IMPORTE", "5000"), 1000);
  assert.equal(importeDeAjuste(0, "IMPORTE", "5"), 0);
  assert.equal(importeDeAjuste(1000, null, null), 0);
});

test("la base de la Orden descuenta los ajustes de los trabajos", () => {
  const conAjuste = orden({
    ajustes_detalle: [
      { detalle_id: "DET-002", importe: "5000", tipo: "PORCENTAJE", valor: "10" },
    ] as unknown as Orden["resumen"]["ajustes_detalle"],
  });
  assert.equal(baseDelDestino(conAjuste, null), 125000);
  assert.equal(baseDelDestino(conAjuste, "DET-002"), 50000);
  assert.equal(baseDelDestino(conAjuste, "DET-009"), 0);
});

test("vista previa: precio original, ajuste y final, con la validación", () => {
  assert.deepEqual(vistaPrevia(50000, "PORCENTAJE", "10"), {
    valido: true,
    error: null,
    original: 50000,
    ajuste: 5000,
    final: 45000,
  });
  assert.equal(vistaPrevia(50000, "IMPORTE", "2500,5").final, 47499.5);
  assert.match(vistaPrevia(50000, "PORCENTAJE", "101").error ?? "", /100 %/);
  assert.match(vistaPrevia(50000, "IMPORTE", "50001").error ?? "", /superar/);
  assert.equal(vistaPrevia(50000, "IMPORTE", "0").valido, false);
  assert.equal(vistaPrevia(50000, "IMPORTE", "1.234").valido, false);
});

test("solo el vigente de su destino se revierte o corrige", () => {
  const registros = [
    registro({ id: "AJ-1", fecha: "2026-11-24T10:00:00Z" }),
    registro({ id: "AJ-2", fecha: "2026-11-24T11:00:00Z", detalle_id: "DET-002" }),
    registro({ id: "AJ-3", fecha: "2026-11-24T12:00:00Z", tipo: "IMPORTE", valor: "5000" }),
  ];
  assert.equal(esRevertible(registros, registros[0]), false);
  assert.equal(esRevertible(registros, registros[1]), true);
  assert.equal(esRevertible(registros, registros[2]), true);
  // Revertido el tercero, vuelve a ser vigente el primero.
  registros[2].reversion = {
    usuario_id: "ADMIN-001",
    fecha: "2026-11-24T13:00:00Z",
    motivo: "Error",
  };
  assert.equal(esRevertible(registros, registros[2]), false);
  assert.equal(ultimoNoRevertido(registros, null)?.id, "AJ-1");
  assert.equal(esRevertible(registros, registros[0]), true);
  // Un retiro no es un ajuste: no se revierte.
  const quitar = registro({ id: "AJ-4", fecha: "2026-11-24T14:00:00Z", tipo: null, valor: null });
  assert.equal(esRevertible([...registros, quitar], quitar), false);
});

test("la operación de cada registro: alta, cambio, retiro y corrección", () => {
  const registros = [
    registro({ id: "AJ-1", fecha: "2026-11-24T10:00:00Z" }),
    registro({ id: "AJ-2", fecha: "2026-11-24T11:00:00Z", valor: "20" }),
    registro({ id: "AJ-3", fecha: "2026-11-24T12:00:00Z", tipo: null, valor: null }),
    registro({ id: "AJ-4", fecha: "2026-11-24T13:00:00Z" }),
    registro({ id: "AJ-5", fecha: "2026-11-24T14:00:00Z", corrige_a: "AJ-4", clase: "CORTESIA" }),
  ];
  assert.deepEqual(
    registros.map((_, indice) => operacionDe(registros, indice)),
    ["ALTA", "CAMBIO", "QUITAR", "ALTA", "CORRECCION"],
  );
});

test("el historial suma reversiones y recálculos, sin repetir la corrección", () => {
  const registros = [
    registro({
      id: "AJ-1",
      fecha: "2026-11-24T10:00:00Z",
      precio_original: "130000",
      importe_aplicado: "13000",
      precio_final: "117000",
      reversion: { usuario_id: "ADMIN-001", fecha: "2026-11-24T12:00:00Z", motivo: "Mal cargado" },
    }),
    registro({
      id: "AJ-2",
      fecha: "2026-11-24T11:00:00Z",
      detalle_id: "DET-002",
      clase: "CORTESIA",
      reversion: { usuario_id: "ADMIN-001", fecha: "2026-11-24T13:00:00Z", motivo: "Era otro" },
    }),
    registro({
      id: "AJ-3",
      fecha: "2026-11-24T13:00:00Z",
      detalle_id: "DET-002",
      corrige_a: "AJ-2",
      tipo: "IMPORTE",
      valor: "2500",
      usuario_id: "ADMIN-001",
    }),
  ];
  const entradas = historialDeAjustes({
    descuentos: registros,
    recalculos_ajuste: [
      {
        ajuste_id: "AJ-3",
        causa: "CANCELACION",
        detalle_id: "DET-002",
        precio_anterior: "50000",
        precio_nuevo: "0",
        importe_anterior: "2500",
        importe_nuevo: "0",
        usuario_id: "RECEP-001",
        fecha: "2026-11-24T14:00:00Z",
      },
    ],
  });
  assert.deepEqual(
    entradas.map((e) => e.operacion),
    ["ALTA", "ALTA", "REVERSION", "CORRECCION", "RECALCULO"],
  );
  assert.equal(entradas[0].evidencia, "precio 130000 · ajuste 13000 · final 117000");
  assert.equal(entradas[0].revertido, true);
  assert.match(entradas[1].descripcion, /^Cortesía 10 % · DET-002/);
  assert.equal(entradas[2].motivo, "Mal cargado");
  assert.match(entradas[3].descripcion, /corrige AJ-2/);
  assert.equal(entradas[3].revertible?.id, "AJ-3");
  assert.match(entradas[4].descripcion, /cancelación/);
  assert.match(entradas[4].evidencia ?? "", /2500 → 0/);
});

test("avisa antes de redefinir o cancelar un trabajo con ajustes", () => {
  const conAjustes = orden({
    descuento: {
      tipo: "PORCENTAJE",
      valor: "10",
      clase: "DESCUENTO",
      importe: "12500",
    } as unknown as Orden["resumen"]["descuento"],
    ajustes_detalle: [
      {
        detalle_id: "DET-002",
        tipo: "PORCENTAJE",
        valor: "10",
        clase: "CORTESIA",
        importe: "5000",
      },
    ] as unknown as Orden["resumen"]["ajustes_detalle"],
  });
  assert.equal(
    avisoRecalculo(conAjustes, "DET-002", 0),
    "Se recalcula el ajuste comercial vigente (queda registrado): " +
      "Cortesía del trabajo: 5000 → 0; Descuento de la Orden: 12500 → 8000.",
  );
  // Un importe fijo de la Orden por debajo de la base nueva no cambia.
  const fijo = orden({
    descuento: { tipo: "IMPORTE", valor: "1000", importe: "1000" } as unknown as Orden["resumen"]["descuento"],
  });
  assert.equal(avisoRecalculo(fijo, "DET-001", 60000), null);
  assert.equal(avisoRecalculo(orden(), "DET-001", 0), null);
});

test("el comprobante nuevo detalla el ajuste por trabajo y el de la Orden", () => {
  const contenido = {
    tipo: "COMPROBANTE_AUTORIZACION",
    orden_id: "OR-000001",
    cliente: { nombre_apellido: "Ana" },
    equipo: { marca: "Apple", modelo: "iPhone 14", variante: null },
    empresa: { nombre: "Rosario Tecno" },
    trabajos: [
      { nombre: "Cambio de bateria", precio: "80000", ajuste: null, precio_final: "80000" },
      {
        nombre: "Cambio de pantalla",
        precio: "50000",
        ajuste: { clase: "CORTESIA", descripcion: "10 %", importe: "5000" },
        precio_final: "45000",
      },
    ],
    subtotal_autorizado: "130000",
    descuento: { descripcion: "10 % (DET-002); $ 5000.00 sobre la Orden", motivo: "x", importe: "10000" },
    ajuste_orden: { clase: "DESCUENTO", descripcion: "$ 5000.00", importe: "5000" },
    ajustes_por_trabajo: true,
    total_autorizado: "120000",
  } as unknown as ContenidoAutorizacion;
  assert.equal(
    textoAjusteDocumento({ clase: "CORTESIA", descripcion: "10 %", importe: "5000" }),
    "Cortesía 10 %",
  );
  assert.deepEqual(lineasDeAjustes(contenido, contenido.trabajos), [
    { etiqueta: "Ajustes de los trabajos", importe: 5000 },
    { etiqueta: "Descuento $ 5000.00 sobre la Orden", importe: 5000 },
  ]);
  const mensaje = mensajeComprobante(contenido);
  assert.match(mensaje, /Cambio de pantalla: .* - Cortesía 10 % = /);
  assert.match(mensaje, /Descuento sobre la orden \(\$ 5000\.00\)/);
  // El motivo del ajuste no se comparte con el cliente.
  assert.doesNotMatch(mensaje, /motivo/i);
});
