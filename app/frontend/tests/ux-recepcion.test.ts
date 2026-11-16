/**
 * Iteración de UX de Recepción (docs/ux-recepcion.md): lógica pura de
 * presentación. No agrega reglas: arma lo que se envía o se muestra.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import type {
  ContenidoEntrega,
  Detalle,
  Orden,
  TipoReparacion,
} from "../src/types/api.ts";
import {
  avisoDni,
  datosObservacionesUnificadas,
  estadoFisicoRegistrado,
  importesPresentados,
  observacionesParaMostrar,
  recargoADevolver,
  recargoDe,
  resultadoDeTrabajo,
  resultadoTecnico,
  subtituloOrden,
  tiposParaTrabajoInicial,
} from "../src/features/ordenes-reparacion/recepcionUx.ts";

describe("UX-03 observaciones del equipo (marca explícita)", () => {
  test("el texto único va a la observación visible y a la falla, nunca al estado físico", () => {
    const datos = datosObservacionesUnificadas("  No carga. Rayón.  ", " ok ");
    assert.equal(datos.falla_reportada, "No carga. Rayón.");
    assert.deepEqual(datos.recepcion, {
      estado_fisico: null,
      accesorios: [],
      observaciones: "No carga. Rayón.",
      notas_internas: "ok",
      observaciones_unificadas: true,
    });
  });

  test("las notas internas siguen aparte; vacías no se envían", () => {
    assert.equal(datosObservacionesUnificadas("x", "  ").recepcion.notas_internas, null);
  });

  const orden = (
    falla: string,
    estado: string | null,
    obs: string | null,
    unificadas?: boolean,
  ) =>
    ({
      equipo: { falla_reportada: falla },
      recepcion: {
        datos: {
          estado_fisico: estado,
          observaciones: obs,
          observaciones_unificadas: unificadas,
        },
      },
    }) as unknown as Orden;

  test("con la marca: un solo dato", () => {
    assert.deepEqual(observacionesParaMostrar(orden("No carga.", null, "No carga.", true)), [
      { etiqueta: "Observaciones del equipo", texto: "No carga." },
    ]);
  });

  test("sin la marca (registro anterior): cada dato con su nombre, aunque coincidan", () => {
    assert.deepEqual(observacionesParaMostrar(orden("No carga.", "Rayado", "No carga.")), [
      { etiqueta: "Falla declarada", texto: "No carga." },
      { etiqueta: "Estado físico", texto: "Rayado" },
      { etiqueta: "Observaciones", texto: "No carga." },
    ]);
  });

  test("el requisito de estado físico, como el backend", () => {
    const datos = (estado: string | null, obs: string | null, marca?: boolean) =>
      ({ estado_fisico: estado, observaciones: obs, observaciones_unificadas: marca }) as never;
    assert.equal(estadoFisicoRegistrado(datos("Golpe", null)), true);
    assert.equal(estadoFisicoRegistrado(datos(null, "No carga.", true)), true);
    assert.equal(estadoFisicoRegistrado(datos(null, "No carga.")), false);
    assert.equal(estadoFisicoRegistrado(datos(null, "  ", true)), false);
    assert.equal(estadoFisicoRegistrado(null), false);
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

describe("DEC-UX-14 recargo a devolver", () => {
  const base = { montoPago: "100000", recargoPago: "2000" };
  test("proporcional, y todo lo que queda al completar el pago", () => {
    assert.equal(recargoADevolver({ ...base, devueltoAntes: "0", recargoDevueltoAntes: "0", monto: "50000" }), 1000);
    assert.equal(recargoADevolver({ ...base, devueltoAntes: "50000", recargoDevueltoAntes: "1000", monto: "50000" }), 1000);
    assert.equal(recargoADevolver({ ...base, devueltoAntes: "0", recargoDevueltoAntes: "0", monto: "33333.33" }), 666.67);
    assert.equal(
      recargoADevolver({ ...base, devueltoAntes: "33333.33", recargoDevueltoAntes: "666.67", monto: "66666.67" }),
      1333.33,
    );
  });
  test("sin recargo o sin importe, cero", () => {
    assert.equal(recargoADevolver({ montoPago: "100", recargoPago: "0", devueltoAntes: "0", recargoDevueltoAntes: "0", monto: "50" }), 0);
    assert.equal(recargoADevolver({ ...base, devueltoAntes: "0", recargoDevueltoAntes: "0", monto: "" }), 0);
  });
});

describe("DEC-UX-13 importes presentados en el comprobante de cobro", () => {
  test("cada trabajo con su recargo y los totales incorporados, sin línea aparte", () => {
    const contenido = {
      trabajos_realizados: [
        { detalle_id: "DET-001", precio: "100000", recargo: "2000" },
        { detalle_id: "DET-002", precio: "50000", recargo: "1000" },
      ],
      subtotal: null,
      total: "150000",
      pagado: "150000",
      devuelto: "0",
      recargo_incorporado: "3000",
      recargo_cobrado: "3000",
      recargo_devuelto: "0",
    } as unknown as ContenidoEntrega;
    assert.deepEqual(importesPresentados(contenido), {
      trabajos: { "DET-001": 102000, "DET-002": 51000 },
      subtotal: null,
      total: 153000,
      pagado: 153000,
      devuelto: 0,
    });
  });
  test("un comprobante anterior, sin recargos, queda igual", () => {
    const contenido = {
      trabajos_realizados: [{ detalle_id: "DET-001", precio: "70000" }],
      subtotal: "80000",
      total: "70000",
      pagado: "70000",
      devuelto: "0",
    } as unknown as ContenidoEntrega;
    const presentados = importesPresentados(contenido);
    assert.equal(presentados.trabajos["DET-001"], 70000);
    assert.equal(presentados.subtotal, 80000);
    assert.equal(presentados.total, 70000);
  });
});
