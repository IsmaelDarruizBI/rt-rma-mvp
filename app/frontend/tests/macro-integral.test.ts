/**
 * Macroiteración integral: reglas de pantalla de Compras y recepciones
 * parciales (DEC-MI-09), inventario por lotes (DEC-MI-10), checklist con
 * tipos del catálogo de Ventas (DC12), roles y permisos (DC27A/B) y
 * Configuración. La API valida todo de nuevo: estas reglas evitan ofrecer
 * lo que el servidor rechazaría y arman lo que se envía.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import type { CatalogoChecklist, PreguntaChecklist } from "../src/api/checklist.ts";
import type { CostoCompra, OrdenCompra } from "../src/api/compras.ts";
import {
  GESTORES,
  avanceDeOrden,
  costoDistinto,
  erroresDeRecepcion,
  lineasIniciales,
  lineasParaRecibir,
  ultimosCostos,
} from "../src/features/compras/recepcion.ts";
import {
  ROLES,
  alternarRol,
  motivoParaNoGuardarRoles,
  puedeGuardarPermiso,
} from "../src/features/configuracion/roles.ts";
import {
  muestraLotes,
  opcionesDeLote,
  origenDelLote,
  saldosConciliados,
  type SaldosDeInsumo,
} from "../src/features/inventario/saldos.ts";
import {
  motivoSinChecklist,
  moverPregunta,
  preguntasDelTipo,
  puedeRegistrarChecklist,
  respuestasParaEnviar,
  textoOrigen,
  tipoPropuesto,
} from "../src/features/ordenes-reparacion/checklist.ts";
import { puede } from "../src/lib/roles.ts";
import type { Usuario } from "../src/types/api.ts";

const usuario = (id: string, rol: Usuario["rol"], extra: Partial<Usuario> = {}): Usuario => ({
  id,
  nombre: id,
  rol,
  activo: true,
  ...extra,
});

// --- Compras y recepciones parciales -----------------------------------------

const orden: OrdenCompra = {
  id: "OC-000001",
  proveedor_id: "PRV-0001",
  items: [
    { insumo_id: "INS-001", cantidad: "3", costo_unitario: "1500" },
    { insumo_id: "INS-002", cantidad: "2", costo_unitario: "100" },
  ],
  solicitudes: [],
  creada_por: "RECEP-001",
  creada_en: "2026-11-14T12:00:00Z",
  confirmada_por: "RECEP-001",
  confirmada_en: "2026-11-14T12:05:00Z",
  cancelada_por: null,
  motivo_cancelacion: null,
  recepciones: [],
  observaciones: null,
  estado: "PARCIAL",
  renglones: [
    { insumo_id: "INS-001", pedido: "3", recibido: "2", pendiente: "1" },
    { insumo_id: "INS-002", pedido: "2", recibido: "2", pendiente: "0" },
  ],
};

describe("Compras", () => {
  test("gestionan Recepción, Coordinación y Administración, o quien tenga el permiso", () => {
    assert.equal(puede(usuario("RECEP-001", "RECEPCION"), "COMPRAS_GESTIONAR", GESTORES), true);
    assert.equal(puede(usuario("TECH-001", "TECNICO"), "COMPRAS_GESTIONAR", GESTORES), false);
    // Con los permisos de hoy (configurables) manda la API.
    const tecnicoHabilitado = usuario("TECH-002", "TECNICO", { permisos: ["COMPRAS_GESTIONAR"] });
    assert.equal(puede(tecnicoHabilitado, "COMPRAS_GESTIONAR", GESTORES), true);
    const recepcionSinPermiso = usuario("RECEP-002", "RECEPCION", { permisos: ["ORDEN_CREAR"] });
    assert.equal(puede(recepcionSinPermiso, "COMPRAS_GESTIONAR", GESTORES), false);
    assert.equal(puede(null, "COMPRAS_GESTIONAR", GESTORES), false);
  });

  test("el último costo es el más reciente de cada insumo", () => {
    const costo = (insumo_id: string, costo_unitario: string, fecha: string): CostoCompra => ({
      insumo_id,
      orden_compra_id: "OC-1",
      recepcion_id: "REC-01",
      proveedor_id: "PRV-0001",
      cantidad: "1",
      costo_unitario,
      fecha,
    });
    assert.deepEqual(
      ultimosCostos([
        costo("INS-001", "1600", "2026-11-14"),
        costo("INS-001", "1500", "2026-11-01"),
        costo("INS-002", "90", "2026-11-02"),
      ]),
      { "INS-001": "1600", "INS-002": "90" },
    );
  });

  test("la recepción parcial ofrece solo lo pendiente y nunca más", () => {
    const lineas = lineasIniciales(orden);
    assert.deepEqual(
      lineas.map((l) => [l.insumo_id, l.costo]),
      [["INS-001", "1500"]],
    );
    assert.match(erroresDeRecepcion(orden, lineas)[0], /al menos un insumo/);
    const demasiado = [{ ...lineas[0], cantidad: "2" }];
    assert.match(erroresDeRecepcion(orden, demasiado).join(" "), /quedan 1 pendientes/);
    const justa = [{ ...lineas[0], cantidad: "1", costo: "1600", lote: " L-QA " }];
    assert.deepEqual(erroresDeRecepcion(orden, justa), []);
    assert.equal(costoDistinto(orden, justa[0]), true);
    assert.deepEqual(lineasParaRecibir(justa), [
      {
        insumo_id: "INS-001",
        cantidad: "1",
        costo_unitario: "1600",
        lote: "L-QA",
        series: [],
        diferencia: null,
      },
    ]);
  });

  test("series: una por unidad y sin repetir", () => {
    const base = { ...lineasIniciales(orden)[0], cantidad: "1" };
    assert.match(
      erroresDeRecepcion(orden, [{ ...base, series: "S1, S2" }]).join(" "),
      /un número de serie por unidad/,
    );
    const dos = { ...orden, renglones: [{ ...orden.renglones[0], pendiente: "2" }] };
    assert.match(
      erroresDeRecepcion(dos, [{ ...base, cantidad: "2", series: "S1\nS1" }]).join(" "),
      /repetidos/,
    );
    assert.deepEqual(lineasParaRecibir([{ ...base, series: "S1" }])[0].series, ["S1"]);
  });

  test("avance de la OC: pedido, recibido y pendiente", () => {
    assert.deepEqual(avanceDeOrden(orden), { pedido: 5, recibido: 4, pendiente: 1 });
  });
});

// --- Inventario por lotes ----------------------------------------------------

const saldos: SaldosDeInsumo = {
  insumo_id: "INS-001",
  control: "LOTE",
  stock_fisico: "5",
  sin_lote_identificado: "3",
  lotes: [
    {
      lote: {
        id: "LOT-1",
        insumo_id: "INS-001",
        numero: "L-QA",
        serie: false,
        origen: "COMPRA",
        referencia: "OC-000001/REC-01",
        usuario_id: "RECEP-001",
        fecha: "2026-11-14T12:00:00Z",
      },
      saldo: "2",
    },
    {
      lote: {
        id: "LOT-2",
        insumo_id: "INS-001",
        numero: "L-VACIO",
        serie: false,
        origen: "INGRESO_MANUAL",
        referencia: null,
        usuario_id: "ADMIN-001",
        fecha: "2026-11-10T12:00:00Z",
      },
      saldo: "0",
    },
  ],
};

describe("Inventario por lotes", () => {
  test("el selector ofrece el stock sin lote y los lotes con saldo", () => {
    assert.deepEqual(
      opcionesDeLote(saldos).map((o) => o.valor),
      ["", "LOT-1"],
    );
    assert.match(opcionesDeLote(saldos)[0].texto, /sin lote identificado \(3\)/);
    // Un lote ya elegido sin saldo no desaparece.
    assert.deepEqual(
      opcionesDeLote(saldos, "LOT-2").map((o) => o.valor),
      ["", "LOT-1", "LOT-2"],
    );
  });

  test("los saldos concilian con el físico y se describe el origen", () => {
    assert.equal(saldosConciliados(saldos), true);
    assert.equal(saldosConciliados({ ...saldos, stock_fisico: "6" }), false);
    assert.equal(origenDelLote(saldos.lotes[0]), "compra OC-000001/REC-01");
    assert.equal(origenDelLote(saldos.lotes[1]), "ingreso manual");
  });

  test("un insumo sin lote y sin historia no muestra el detalle", () => {
    assert.equal(muestraLotes({ ...saldos, control: "SIN_LOTE", lotes: [] }), false);
    assert.equal(muestraLotes({ ...saldos, control: "SIN_LOTE" }), true);
    assert.equal(muestraLotes(saldos), true);
  });
});

// --- Checklist (DC12) --------------------------------------------------------

const pregunta = (id: string, orden: number, extra: Partial<PreguntaChecklist> = {}): PreguntaChecklist => ({
  id,
  tipo_equipo_id: "apple_usados",
  texto: id,
  opciones: ["Sí", "No"],
  activa: true,
  orden,
  ...extra,
});

describe("Checklist con tipos del catálogo de Ventas", () => {
  test("sin columna de Ventas definida no se ofrece el checklist", () => {
    const sinDefinir: Pick<CatalogoChecklist, "tipos" | "origen"> = {
      tipos: [],
      origen: {
        campo: null,
        definido: false,
        origen: null,
        sincronizable: false,
        ultima_sincronizacion: null,
        aviso: "Falta definir qué dato del catálogo de Ventas es el tipo de equipo",
      },
    };
    assert.match(motivoSinChecklist(sinDefinir) ?? "", /falta definir/);
    assert.match(textoOrigen(sinDefinir.origen), /Falta definir/);
    assert.match(motivoSinChecklist(null) ?? "", /No se pudo leer/);
    const definido = {
      ...sinDefinir,
      origen: { ...sinDefinir.origen!, campo: "tp_gp", definido: true, aviso: null },
    };
    assert.match(motivoSinChecklist(definido) ?? "", /Administración los actualiza/);
    assert.equal(
      motivoSinChecklist({ ...definido, tipos: [{ id: "apple_usados", nombre: "apple_usados", activo: true }] }),
      null,
    );
  });

  test("preguntas vigentes del tipo, en orden; solo viaja lo registrado", () => {
    const catalogo = {
      preguntas: [
        pregunta("CHK-0002", 2),
        pregunta("CHK-0001", 1),
        pregunta("CHK-0003", 3, { activa: false }),
        pregunta("CHK-0004", 1, { tipo_equipo_id: "otro" }),
      ],
    };
    assert.deepEqual(
      preguntasDelTipo(catalogo, "apple_usados").map((p) => p.id),
      ["CHK-0001", "CHK-0002"],
    );
    assert.deepEqual(
      respuestasParaEnviar({ "CHK-0001": "R:Sí", "CHK-0002": "NO_REALIZADA", "CHK-0005": "" }),
      [
        { pregunta_id: "CHK-0001", respuesta: "Sí", no_realizada: false },
        { pregunta_id: "CHK-0002", respuesta: null, no_realizada: true },
      ],
    );
  });

  test("corregir exige motivo y propone el tipo de la Orden si sigue vigente", () => {
    assert.equal(puedeRegistrarChecklist("", false, ""), false);
    assert.equal(puedeRegistrarChecklist("apple_usados", false, ""), true);
    assert.equal(puedeRegistrarChecklist("apple_usados", true, "  "), false);
    assert.equal(puedeRegistrarChecklist("apple_usados", true, "Se probó"), true);
    const tipos = [
      { id: "apple_usados", nombre: "apple_usados", activo: true },
      { id: "baja", nombre: "baja", activo: false },
    ];
    assert.equal(tipoPropuesto(tipos, { id: "apple_usados" }), "apple_usados");
    assert.equal(tipoPropuesto(tipos, { id: "baja" }), "");
    assert.equal(tipoPropuesto(tipos, null), "");
  });

  test("mover una pregunta renumera sin empates y guarda solo lo que cambia", () => {
    const lista = [pregunta("A", 0), pregunta("B", 0), pregunta("C", 0)];
    const cambios = moverPregunta(lista, "C", -1);
    assert.deepEqual(
      cambios.map((p) => [p.id, p.orden]),
      [["A", 1], ["C", 2], ["B", 3]],
    );
    assert.deepEqual(moverPregunta(lista, "A", -1), []);
    const ordenada = [pregunta("A", 1), pregunta("B", 2), pregunta("C", 3)];
    assert.deepEqual(
      moverPregunta(ordenada, "A", 1).map((p) => [p.id, p.orden]),
      [["B", 1], ["A", 2]],
    );
  });
});

// --- Roles, permisos y Configuración -----------------------------------------

describe("Roles y permisos", () => {
  const admin = usuario("ADMIN-001", "ADMINISTRADOR");
  const otroAdmin = usuario("ADMIN-002", "ADMINISTRADOR");
  const recepcion = usuario("RECEP-001", "RECEPCION");

  test("nunca queda el sistema sin un Administrador activo", () => {
    assert.match(
      motivoParaNoGuardarRoles([admin, recepcion], "ADMIN-001", ["RECEPCION"]) ?? "",
      /sin un Administrador/,
    );
    assert.equal(
      motivoParaNoGuardarRoles([admin, otroAdmin, recepcion], "ADMIN-001", ["RECEPCION"]),
      null,
    );
    // Un administrador inactivo no cuenta.
    assert.match(
      motivoParaNoGuardarRoles(
        [admin, { ...otroAdmin, activo: false }],
        "ADMIN-001",
        ["COORDINADOR_RMA"],
      ) ?? "",
      /sin un Administrador/,
    );
    assert.match(motivoParaNoGuardarRoles([admin], "RECEP-001", []) ?? "", /al menos un rol/);
  });

  test("marcar y desmarcar roles no repite", () => {
    assert.deepEqual(alternarRol(["RECEPCION"], "TECNICO", true), ["RECEPCION", "TECNICO"]);
    assert.deepEqual(alternarRol(["RECEPCION"], "RECEPCION", true), ["RECEPCION"]);
    assert.deepEqual(alternarRol(["RECEPCION", "TECNICO"], "RECEPCION", false), ["TECNICO"]);
    assert.equal(ROLES.length, 4);
  });

  test("un permiso fijo, sin cambios o sin roles no se guarda", () => {
    const consulta = { configurable: true, vigentes: ROLES };
    assert.equal(puedeGuardarPermiso(consulta, ROLES), false);
    assert.equal(puedeGuardarPermiso(consulta, ["ADMINISTRADOR"]), true);
    assert.equal(puedeGuardarPermiso(consulta, []), false);
    assert.equal(puedeGuardarPermiso({ configurable: false, vigentes: ["ADMINISTRADOR"] }, ROLES), false);
  });

  test("las consultas configurables (DC27B) siguen los permisos de la API", () => {
    const tecnicoSinConsulta = usuario("TECH-001", "TECNICO", { permisos: ["EJECUCION"] });
    assert.equal(puede(tecnicoSinConsulta, "INVENTARIO_CONSULTAR", ROLES), false);
    assert.equal(puede(usuario("TECH-002", "TECNICO"), "INVENTARIO_CONSULTAR", ROLES), true);
  });
});
