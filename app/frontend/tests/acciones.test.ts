/**
 * Barra de acciones y «Pendientes» de la Orden: solo reordenan lo que el
 * backend publica y lo que `puedeEjecutar` habilita; no agregan acciones.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import type { Accion, Orden, Usuario } from "../src/types/api.ts";
import {
  claveDeAccion,
  clavesDeTareas,
  organizarBarra,
  pendientesDe,
} from "../src/features/ordenes-reparacion/acciones.ts";

function accion(codigo: string, extra: Partial<Accion> = {}): Accion {
  return {
    codigo,
    etiqueta: codigo,
    roles: ["TECNICO"],
    detalle_id: null,
    ejecucion_id: null,
    requiere_actor: true,
    usuario_id: null,
    pago_id: null,
    bloqueo: null,
    ...extra,
  } as Accion;
}

function orden(datos: {
  disponibles?: Accion[];
  tareas?: { titulo: string; responsable: string; acciones: Accion[] }[];
  avisos?: { codigo: string; titulo: string; responsable: string | null; acciones: Accion[] }[];
  cerrada?: boolean;
}): Orden {
  return {
    cerrada: datos.cerrada ?? false,
    acciones_disponibles: datos.disponibles ?? [],
    acciones_cancelacion: [],
    acciones_autorizacion: [],
    acciones_financieras: [],
    acciones_custodia: [],
    acciones_complementarias: [],
    situacion: {
      descripcion: "",
      tareas: (datos.tareas ?? []).map((t) => ({ motivo: "", ...t })),
      avisos: datos.avisos ?? [],
    },
  } as unknown as Orden;
}

const tecnico = { id: "u1", rol: "TECNICO", activo: true } as Usuario;
const recepcion = { id: "u2", rol: "RECEPCION", activo: true } as Usuario;

const habilitada = (a: Accion) => ({ clave: claveDeAccion(a), accion: a });

describe("organizarBarra", () => {
  test("lo que resuelve una tarea va primero; el resto respeta el máximo", () => {
    const a = accion("A");
    const b = accion("B");
    const c = accion("C");
    const d = accion("D");
    const tarea = accion("TAREA");
    const barra = organizarBarra(
      [a, b, c, d, tarea].map(habilitada),
      [claveDeAccion(tarea)],
    );
    assert.deepEqual(
      barra.visibles.map((x) => x.accion.codigo),
      ["TAREA", "A", "B"],
    );
    assert.deepEqual(
      barra.menu.map((x) => x.accion.codigo),
      ["C", "D"],
    );
  });

  test("las especiales van al menú salvo que resuelvan la tarea", () => {
    const cancelar = accion("CANCELAR_ORDEN");
    const esperar = accion("ESPERAR_RECURSOS");
    const comun = accion("DIAGNOSTICAR");
    const barra = organizarBarra(
      [cancelar, comun, esperar].map(habilitada),
      [claveDeAccion(esperar)],
    );
    assert.deepEqual(
      barra.visibles.map((x) => x.accion.codigo),
      ["ESPERAR_RECURSOS", "DIAGNOSTICAR"],
    );
    assert.deepEqual(
      barra.menu.map((x) => x.accion.codigo),
      ["CANCELAR_ORDEN"],
    );
  });

  test("interrumpir nunca es el botón de la tarea", () => {
    const interrumpir = accion("INTERRUMPIR_EJECUCION");
    const completar = accion("COMPLETAR_EJECUCION");
    const barra = organizarBarra(
      [interrumpir, completar].map(habilitada),
      [claveDeAccion(completar), claveDeAccion(interrumpir)],
    );
    assert.deepEqual(
      barra.visibles.map((x) => x.accion.codigo),
      ["COMPLETAR_EJECUCION"],
    );
    assert.deepEqual(
      barra.menu.map((x) => x.accion.codigo),
      ["INTERRUMPIR_EJECUCION"],
    );
  });

  test("no inventa acciones: todo lo habilitado aparece una sola vez", () => {
    const todas = ["A", "B", "C", "D", "E", "CANCELAR_ORDEN"].map((c) =>
      habilitada(accion(c)),
    );
    const barra = organizarBarra(todas, []);
    const salida = [...barra.visibles, ...barra.menu].map((x) => x.clave);
    assert.deepEqual([...salida].sort(), todas.map((x) => x.clave).sort());
  });
});

describe("clavesDeTareas y pendientesDe", () => {
  const diagnosticar = accion("DIAGNOSTICAR", { usuario_id: "u1" });
  const ordenConTarea = orden({
    tareas: [{ titulo: "Diagnosticar", responsable: "Taller", acciones: [diagnosticar] }],
    avisos: [
      {
        codigo: "SALDO",
        titulo: "Saldo pendiente",
        responsable: "Recepción",
        acciones: [accion("REGISTRAR_PAGO", { roles: ["RECEPCION"] })],
      },
    ],
  });

  test("el titular ve la tarea como propia y con su acción", () => {
    assert.deepEqual(clavesDeTareas(ordenConTarea, tecnico), [claveDeAccion(diagnosticar)]);
    const [tarea, aviso] = pendientesDe(ordenConTarea, tecnico);
    assert.equal(tarea.titulo, "Diagnosticar");
    assert.equal(tarea.titularId, "u1");
    assert.equal(tarea.responsable, null);
    assert.deepEqual(tarea.acciones.map((a) => a.codigo), ["DIAGNOSTICAR"]);
    assert.equal(aviso.aviso, true);
    assert.deepEqual(aviso.acciones, []);
  });

  test("una tarea con varias salidas ofrece todas las que el usuario puede", () => {
    const agregar = accion("AGREGAR_DETALLE", { roles: ["RECEPCION"] });
    const generar = accion("GENERAR_COMPROBANTE_INGRESO", { roles: ["RECEPCION"] });
    const o = orden({
      tareas: [{ titulo: "Generar el comprobante", responsable: "Recepción", acciones: [agregar, generar] }],
    });
    assert.deepEqual(
      pendientesDe(o, recepcion)[0].acciones.map((a) => a.codigo),
      ["AGREGAR_DETALLE", "GENERAR_COMPROBANTE_INGRESO"],
    );
    assert.deepEqual(pendientesDe(o, tecnico)[0].acciones, []);
  });

  test("otro rol ve quién la tiene, sin acción para resolverla", () => {
    assert.deepEqual(clavesDeTareas(ordenConTarea, recepcion), []);
    const [tarea, aviso] = pendientesDe(ordenConTarea, recepcion);
    assert.deepEqual(tarea.acciones, []);
    assert.equal(tarea.titularId, "u1");
    assert.deepEqual(aviso.acciones.map((a) => a.codigo), ["REGISTRAR_PAGO"]);
  });

  test("el paso recomendado solo aparece si la Orden sigue abierta", () => {
    const emitir = accion("EMITIR_COMPROBANTE_AUTORIZACION", { roles: ["RECEPCION"] });
    const abierta = orden({ disponibles: [emitir] });
    assert.equal(pendientesDe(abierta, recepcion)[0]?.acciones[0]?.codigo, emitir.codigo);
    assert.deepEqual(clavesDeTareas(abierta, recepcion), [claveDeAccion(emitir)]);
    const cerrada = orden({ disponibles: [emitir], cerrada: true });
    assert.deepEqual(pendientesDe(cerrada, recepcion), []);
  });
});
