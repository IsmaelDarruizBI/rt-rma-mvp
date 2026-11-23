/**
 * Bloque 4 de ajustes funcionales: comprobantes (DEC-AJ-09, BF-19).
 *
 * - Los datos de la empresa en la hoja: los que copió el documento, con el
 *   horario y el pie si los tiene (los anteriores no los tienen).
 * - «Datos de la empresa»: un campo vacío queda sin informar y se detecta
 *   si algo cambió.
 * - «Términos y condiciones»: el borrador parte de la versión vigente,
 *   numera los apartados en orden, no publica un texto igual al vigente y
 *   dice qué falta.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  borradorDe,
  contenidoDelBorrador,
  datosDeEmpresa,
  empresaCambio,
  faltantesDelBorrador,
  formularioDeEmpresa,
  igualAVigente,
} from "../src/features/configuracion/reglasComprobantes.ts";
import {
  pieDeComprobante,
  renglonesDeEmpresa,
} from "../src/features/ordenes-reparacion/empresaEnComprobante.ts";
import type { EmpresaEnDocumento, TextoLegal } from "../src/types/api";

const ANTERIOR: EmpresaEnDocumento = {
  nombre: "Rosario Tecno",
  razon_social: null,
  cuit: null,
  direccion: "Córdoba 1234",
  telefono: "341-555-0100",
  email: null,
  condiciones_garantia: null,
};

const EMPRESA: EmpresaEnDocumento = {
  ...ANTERIOR,
  razon_social: "Rosario Tecno SRL",
  cuit: "30-12345678-9",
  email: "rma@rosariotecno.test",
  horario: "Lunes a viernes de 9 a 18",
  pie_comprobante: "Gracias por elegirnos.\n\n  Seguinos en redes. ",
};

test("la hoja muestra los datos de la empresa que copió el documento", () => {
  assert.deepEqual(renglonesDeEmpresa(EMPRESA), [
    "Rosario Tecno SRL",
    "CUIT 30-12345678-9",
    "Córdoba 1234",
    "341-555-0100 · rma@rosariotecno.test",
    "Horario: Lunes a viernes de 9 a 18",
  ]);
  assert.deepEqual(pieDeComprobante(EMPRESA), [
    "Gracias por elegirnos.",
    "Seguinos en redes.",
  ]);
  // Un comprobante anterior no tiene horario ni pie.
  assert.deepEqual(renglonesDeEmpresa(ANTERIOR), ["Córdoba 1234", "341-555-0100"]);
  assert.deepEqual(pieDeComprobante(ANTERIOR), []);
});

test("datos de la empresa: vacío es sin informar y se detecta el cambio", () => {
  const formulario = formularioDeEmpresa(ANTERIOR);
  assert.equal(formulario.horario, "");
  assert.equal(empresaCambio(ANTERIOR, formulario), false);
  const editado = { ...formulario, horario: " 9 a 18 ", telefono: "  " };
  assert.equal(empresaCambio(ANTERIOR, editado), true);
  assert.deepEqual(datosDeEmpresa(editado), {
    nombre: "Rosario Tecno",
    razon_social: null,
    cuit: null,
    direccion: "Córdoba 1234",
    telefono: null,
    email: null,
    horario: "9 a 18",
    pie_comprobante: null,
  });
});

const VIGENTE: TextoLegal = {
  tipo: "TERMINOS_CONDICIONES_ENTREGA",
  version: 2,
  titulo: "TÉRMINOS Y CONDICIONES",
  contenido: {
    encabezado: {
      marca: "ROSARIO | TECNO",
      titulo: "TÉRMINOS Y CONDICIONES",
      subtitulo: "SERVICIO TÉCNICO",
    },
    apartados: [
      { numero: 1, lineas: ["La garantía es la indicada para cada trabajo."], destacado: false },
      { numero: 2, lineas: ["No cubre:", "Golpes.", "Humedad."], destacado: false },
      { numero: 3, lineas: ["Plazos estimativos."], destacado: true },
    ],
    pie: ["FIRMA DEL CLIENTE", "ACLARACIÓN", "FECHA"],
  },
  vigente_desde: "2026-11-23T03:00:00Z",
  publicado_por: null,
};

test("términos: el borrador de la vigente no se publica sin cambios", () => {
  const borrador = borradorDe(VIGENTE);
  assert.equal(borrador.apartados[1].texto, "No cubre:\nGolpes.\nHumedad.");
  assert.deepEqual(contenidoDelBorrador(borrador), {
    titulo: VIGENTE.titulo,
    contenido: VIGENTE.contenido,
  });
  assert.equal(igualAVigente(borrador, VIGENTE), true);
  assert.deepEqual(faltantesDelBorrador(borrador), []);
});

test("términos: una versión nueva numera los apartados en orden", () => {
  const borrador = borradorDe(VIGENTE);
  borrador.apartados = [
    borrador.apartados[2],
    { texto: "  Nuevo apartado.\n\n  Segundo renglón. ", destacado: false },
    borrador.apartados[0],
  ];
  const { contenido } = contenidoDelBorrador(borrador);
  assert.deepEqual(
    contenido.apartados.map((a) => [a.numero, a.lineas, a.destacado]),
    [
      [1, ["Plazos estimativos."], true],
      [2, ["Nuevo apartado.", "Segundo renglón."], false],
      [3, ["La garantía es la indicada para cada trabajo."], false],
    ],
  );
  assert.equal(igualAVigente(borrador, VIGENTE), false);
});

test("términos: dice qué falta para publicar", () => {
  const borrador = { ...borradorDe(VIGENTE), titulo: " " };
  borrador.apartados = [...borrador.apartados, { texto: " \n ", destacado: false }];
  assert.deepEqual(faltantesDelBorrador(borrador), ["el título", "el texto del apartado 4"]);
  assert.deepEqual(faltantesDelBorrador({ ...borrador, titulo: "T", apartados: [] }), [
    "al menos un apartado",
  ]);
});
