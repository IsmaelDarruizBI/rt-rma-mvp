/**
 * Configuración v2 (CFG-03 a CFG-08): reglas de pantalla sin React.
 *
 * - Cada subsección se ve con su permiso (no con un rol) y tiene su ruta.
 * - Las altas actualizan el listado con lo que devuelve la API.
 * - Compras: cada acción con su permiso; el borrador propio se descarta
 *   con el permiso de crear OC (DF-5); una API anterior sigue igual.
 * - Permisos: la consulta requerida se habilita primero; quitarla con una
 *   acción que la necesita se impide.
 * - Solo las plantillas de ingreso y retiro; solo los plazos con y sin
 *   check-in.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  accionesDeCompras,
  puedeCancelarOrden,
} from "../src/features/compras/recepcion.ts";
import {
  conElemento,
  esPlantillaVisible,
  precioValido,
  textoGarantias,
} from "../src/features/configuracion/listados.ts";
import {
  accionesQueLoRequieren,
  consultasAHabilitar,
} from "../src/features/configuracion/roles.ts";
import {
  esSeccionConfiguracion,
  gruposDe,
  puedeConfigurar,
  puedeVerSeccion,
  seccionAMostrar,
  seccionesPermitidas,
} from "../src/features/configuracion/secciones.ts";
import { hashDe, parsearRuta } from "../src/features/ordenes-reparacion/rutas.ts";
import type { RolUsuario } from "../src/types/api";

const usuario = (roles: RolUsuario[], permisos?: string[]) => ({
  rol: roles[0],
  roles,
  permisos,
  activo: true,
});

describe("Configuración por permisos (CFG-05)", () => {
  it("Administración ve todas las subsecciones, agrupadas", () => {
    const admin = usuario(["ADMINISTRADOR"], [
      "TIPO_REPARACION_GESTIONAR",
      "MESA_TIPOS_GESTIONAR",
      "MOTIVO_GESTIONAR",
      "CHECKLIST_GESTIONAR",
      "INSUMO_GESTIONAR",
      "PROVEEDOR_GESTIONAR",
      "PLANTILLA_GESTIONAR",
      "ROLES_ADMINISTRAR",
      "CONFIGURACION_ADMINISTRAR",
    ]);
    // DEC-AJ-09: + «Datos de la empresa» y «Términos y condiciones».
    assert.equal(seccionesPermitidas(admin).length, 13);
    assert.deepEqual(
      gruposDe(seccionesPermitidas(admin)).map((g) => g.grupo),
      ["Taller", "Inventario y compras", "Comunicación", "Comprobantes", "Sistema"],
    );
    assert.equal(seccionAMostrar(admin, undefined), "tipos-reparacion");
  });

  it("Recepción con insumos delegados ve solo Insumos, sin lo sensible", () => {
    const recepcion = usuario(["RECEPCION"], ["INSUMO_GESTIONAR", "ORDENES_CONSULTAR"]);
    assert.deepEqual(
      seccionesPermitidas(recepcion).map((s) => s.id),
      ["insumos"],
    );
    assert.equal(puedeConfigurar(recepcion), true);
    assert.equal(seccionAMostrar(recepcion, undefined), "insumos");
    assert.equal(puedeVerSeccion(recepcion, "permisos"), false);
    // Una subsección pedida sin permiso se informa, no se cambia por otra.
    assert.equal(seccionAMostrar(recepcion, "permisos"), "permisos");
  });

  it("sin permisos de configuración no aparece", () => {
    const tecnico = usuario(["TECNICO"], ["ORDENES_CONSULTAR"]);
    assert.equal(puedeConfigurar(tecnico), false);
    assert.equal(seccionAMostrar(tecnico, undefined), null);
  });

  it("con una API anterior (sin permisos) decide el rol de Administración", () => {
    assert.equal(puedeConfigurar(usuario(["ADMINISTRADOR"])), true);
    assert.equal(puedeConfigurar(usuario(["RECEPCION"])), false);
  });

  it("cada subsección tiene su ruta; #/configuracion sigue valiendo", () => {
    assert.deepEqual(parsearRuta("#/configuracion"), { pantalla: "configuracion" });
    assert.deepEqual(parsearRuta("#/configuracion/insumos"), {
      pantalla: "configuracion",
      seccion: "insumos",
    });
    assert.equal(hashDe({ pantalla: "configuracion", seccion: "permisos" }), "#/configuracion/permisos");
    assert.equal(hashDe({ pantalla: "configuracion" }), "#/configuracion");
    // Una subsección desconocida no es una ruta: va al inicio.
    assert.deepEqual(parsearRuta("#/configuracion/otra"), { pantalla: "inicio" });
    assert.equal(esSeccionConfiguracion("parametros"), false);
  });
});

describe("Altas y listados (CFG-04, CFG-06, CFG-08)", () => {
  it("el elemento devuelto reemplaza o se agrega sin recargar", () => {
    const lista = [
      { id: "TR-001", nombre: "a" },
      { id: "TR-002", nombre: "b" },
    ];
    assert.deepEqual(
      conElemento(lista, { id: "TR-002", nombre: "B" }, (x) => x.id).map((x) => x.nombre),
      ["a", "B"],
    );
    assert.deepEqual(
      conElemento(lista, { id: "TR-003", nombre: "c" }, (x) => x.id).map((x) => x.id),
      ["TR-001", "TR-002", "TR-003"],
    );
  });

  it("precios con hasta dos decimales", () => {
    for (const valido of ["0", "10", "10.5", "10.50"]) assert.equal(precioValido(valido), true, valido);
    for (const invalido of ["", "-1", "10.505", "1,5", "abc"]) {
      assert.equal(precioValido(invalido), false, invalido);
    }
  });

  it("solo los plazos con y sin check-in", () => {
    assert.equal(
      textoGarantias({ garantia_con_checkin: 120, garantia_sin_checkin: 45 }),
      "120 con check-in · 45 sin check-in",
    );
  });

  it("solo Ingreso y Equipo listo para retirar (también con una API anterior)", () => {
    assert.equal(esPlantillaVisible({ codigo: "INGRESO", visible: true }), true);
    assert.equal(esPlantillaVisible({ codigo: "RECORDATORIO_RETIRO", visible: false }), false);
    assert.equal(esPlantillaVisible({ codigo: "LISTO_PARA_RETIRAR" }), true);
    assert.equal(esPlantillaVisible({ codigo: "GARANTIA" }), false);
  });
});

describe("Compras por acción (CFG-03, D5, DF-5)", () => {
  const borrador = { estado: "BORRADOR" as const, creada_por: "RECEP-001" };
  const confirmada = { estado: "CONFIRMADA" as const, creada_por: "RECEP-001" };

  it("cada botón con su permiso", () => {
    const acciones = accionesDeCompras(
      usuario(["RECEPCION"], ["COMPRAS_CONSULTAR", "OC_CREAR", "COMPRAS_GESTIONAR"]),
    );
    assert.deepEqual(acciones, {
      solicitar: false,
      crearOc: true,
      confirmar: false,
      cancelar: false,
      recibir: false,
    });
    // Su borrador sí; el ajeno y una OC confirmada, no.
    assert.equal(puedeCancelarOrden(acciones, borrador, "RECEP-001"), true);
    assert.equal(puedeCancelarOrden(acciones, borrador, "COORD-001"), false);
    assert.equal(puedeCancelarOrden(acciones, confirmada, "RECEP-001"), false);
  });

  it("con OC_CANCELAR, cualquiera sin recepciones", () => {
    const acciones = accionesDeCompras(usuario(["ADMINISTRADOR"], ["OC_CANCELAR"]));
    assert.equal(puedeCancelarOrden(acciones, confirmada, "ADMIN-001"), true);
    assert.equal(
      puedeCancelarOrden(acciones, { estado: "PARCIAL", creada_por: "x" }, "ADMIN-001"),
      false,
    );
  });

  it("con una API anterior, COMPRAS_GESTIONAR habilita todo como antes", () => {
    const acciones = accionesDeCompras(usuario(["RECEPCION"], ["COMPRAS_GESTIONAR"]));
    assert.ok(Object.values(acciones).every(Boolean));
    const sinCompras = accionesDeCompras(usuario(["TECNICO"], ["ORDENES_CONSULTAR"]));
    assert.ok(Object.values(sinCompras).every((x) => !x));
  });
});

describe("Dependencias entre permisos (CFG-03)", () => {
  const todos = [
    {
      codigo: "COMPRAS_CONSULTAR",
      descripcion: "Consultar compras",
      vigentes: ["ADMINISTRADOR", "RECEPCION"] as RolUsuario[],
    },
    {
      codigo: "OC_CREAR",
      descripcion: "Crear OC",
      vigentes: ["ADMINISTRADOR", "RECEPCION"] as RolUsuario[],
      requiere: ["COMPRAS_CONSULTAR"],
    },
  ];

  it("habilitar una acción habilita primero su consulta", () => {
    assert.deepEqual(
      consultasAHabilitar(todos[1], ["ADMINISTRADOR", "RECEPCION", "COORDINADOR_RMA"], todos),
      [
        {
          codigo: "COMPRAS_CONSULTAR",
          descripcion: "Consultar compras",
          roles: ["ADMINISTRADOR", "COORDINADOR_RMA", "RECEPCION"],
        },
      ],
    );
    assert.deepEqual(consultasAHabilitar(todos[1], ["ADMINISTRADOR"], todos), []);
  });

  it("quitar una consulta que una acción del rol necesita se impide", () => {
    assert.deepEqual(accionesQueLoRequieren(todos[0], ["ADMINISTRADOR"], todos), ["Crear OC"]);
    assert.deepEqual(accionesQueLoRequieren(todos[0], ["ADMINISTRADOR", "RECEPCION"], todos), []);
  });
});
