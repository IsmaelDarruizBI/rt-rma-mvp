/**
 * Iteración de UX de Recepción (docs/ux-recepcion.md): lógica pura de
 * presentación. No agrega reglas: arma lo que se envía o se muestra.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import type { Detalle, Orden, TipoReparacion } from "../src/types/api.ts";
import {
  avisoDni,
  datosObservacionesUnificadas,
  observacionesParaMostrar,
  recargoDe,
  resultadoDeTrabajo,
  resultadoTecnico,
  subtituloOrden,
  tiposParaTrabajoInicial,
} from "../src/features/ordenes-reparacion/recepcionUx.ts";

describe("UX-03 observaciones del equipo", () => {
  test("el texto único va a falla, estado físico y observación visible", () => {
    const datos = datosObservacionesUnificadas("  No carga. Rayón.  ", " ok ");
    assert.equal(datos.falla_reportada, "No carga. Rayón.");
    assert.deepEqual(datos.recepcion, {
      estado_fisico: "No carga. Rayón.",
      accesorios: [],
      observaciones: "No carga. Rayón.",
      notas_internas: "ok",
    });
  });

  test("las notas internas siguen aparte; vacías no se envían", () => {
    assert.equal(datosObservacionesUnificadas("x", "  ").recepcion.notas_internas, null);
  });

  const orden = (falla: string, estado: string | null, obs: string | null) =>
    ({
      equipo: { falla_reportada: falla },
      recepcion: { datos: { estado_fisico: estado, observaciones: obs } },
    }) as unknown as Orden;

  test("Orden nueva: un solo dato", () => {
    assert.deepEqual(observacionesParaMostrar(orden("No carga.", "No carga.", "No carga.")), [
      { etiqueta: "Observaciones del equipo", texto: "No carga." },
    ]);
  });

  test("Orden anterior: cada dato con su nombre", () => {
    assert.deepEqual(observacionesParaMostrar(orden("No carga.", "Rayado", null)), [
      { etiqueta: "Falla declarada", texto: "No carga." },
      { etiqueta: "Estado físico", texto: "Rayado" },
    ]);
  });
});

describe("UX-04 trabajo inicial", () => {
  const tipo = (id: string, activo = true) =>
    ({ id, nombre: id, precio: "1", activo }) as TipoReparacion;
  test("solo los activos y nunca «Otros»", () => {
    assert.deepEqual(
      tiposParaTrabajoInicial([tipo("A"), tipo("B", false), tipo("TR-OTROS")], "TR-OTROS").map(
        (t) => t.id,
      ),
      ["A"],
    );
  });
});

describe("UX-06 DNI antes del comprobante", () => {
  test("sin DNI avisa; válido no; inválido avisa", () => {
    assert.match(avisoDni({ dni: null }) ?? "", /sin DNI/);
    assert.equal(avisoDni({ dni: "30111222" }), null);
    assert.match(avisoDni({ dni: "12" }) ?? "", /no es válido/);
    assert.equal(avisoDni(null), null);
  });
});

describe("UX-08 recargo", () => {
  test("igual que el backend: centavos, mitad hacia arriba", () => {
    assert.deepEqual(recargoDe("10000", "2"), { recargo: 200, total: 10200 });
    assert.deepEqual(recargoDe("333.33", "2"), { recargo: 6.67, total: 340 });
    assert.deepEqual(recargoDe("0.25", "2"), { recargo: 0.01, total: 0.26 });
    assert.deepEqual(recargoDe("1000", "2.5"), { recargo: 25, total: 1025 });
    assert.deepEqual(recargoDe("1000", "0"), { recargo: 0, total: 1000 });
    assert.equal(recargoDe("", "2"), null);
    assert.equal(recargoDe("-5", "2"), null);
  });
});

describe("UX-10 resultado técnico", () => {
  const detalle = (estado: string, control = "PENDIENTE", extra = {}) =>
    ({
      estado,
      control_estado: control,
      pendiente_de_retrabajo: false,
      cancelacion: null,
      ...extra,
    }) as unknown as Detalle;
  const orden = (estado_workflow: string, detalles: Detalle[], sin = false) =>
    ({
      estado_workflow,
      finalizada_sin_reparacion: sin,
      reparaciones_detail: detalles,
    }) as unknown as Orden;

  test("reparado con todo aprobado y la reparación lista", () => {
    const d = [detalle("COMPLETO", "APROBADO"), detalle("CANCELADO")];
    assert.equal(resultadoTecnico(orden("REPARACION_LISTA", d)), "REPARADO");
    assert.equal(resultadoTecnico(orden("ENTREGADA", d)), "REPARADO");
  });
  test("sin reparación, cancelada, en curso y sin trabajos", () => {
    assert.equal(resultadoTecnico(orden("REPARACION_LISTA", [], true)), "SIN_REPARACION");
    assert.equal(resultadoTecnico(orden("CANCELADA", [detalle("CANCELADO")])), "CANCELADA");
    assert.equal(resultadoTecnico(orden("EN_REPARACION", [detalle("EN_PROGRESO")])), "EN_CURSO");
    assert.equal(resultadoTecnico(orden("REQUERIMIENTO", [])), "SIN_TRABAJOS");
  });
  test("cada trabajo, con lo que ya registra el backend", () => {
    assert.equal(resultadoDeTrabajo(detalle("COMPLETO", "APROBADO")), "Reparado (control aprobado)");
    assert.equal(
      resultadoDeTrabajo(detalle("CANCELADO", "PENDIENTE", { cancelacion: { origen: "RECHAZO_CLIENTE" } })),
      "Rechazado por el cliente",
    );
    assert.equal(
      resultadoDeTrabajo(detalle("EN_PROGRESO", "PENDIENTE", { pendiente_de_retrabajo: true })),
      "Control rechazado: retrabajo",
    );
  });
});

describe("UX-12 cabecera", () => {
  test("solo nombre y teléfono", () => {
    assert.equal(
      subtituloOrden({
        origen: "CLIENTE_EXTERNO",
        cliente: { nombre_apellido: "Ana Gómez", telefono: "341-555" },
      } as unknown as Orden),
      "Ana Gómez · 341-555",
    );
    assert.equal(
      subtituloOrden({ origen: "RT_INTERNO", cliente: null } as unknown as Orden),
      "Equipo RT interno",
    );
  });
});
