/**
 * Login dummy del UAT (usuarioDemo.ts): credenciales, mapeo por rol a los
 * usuarios reales del catalogo y sesion recordada en localStorage.
 */
import assert from "node:assert/strict";
import { beforeEach, describe, test } from "node:test";

import {
  borrarUsuarioDemo,
  elegirUsuarioDemo,
  guardarUsuarioDemo,
  leerUsuarioDemo,
  validarCredenciales,
} from "../src/features/ordenes-reparacion/usuarioDemo.ts";

const CATALOGO = [
  { id: "RECEP-001", rol: "RECEPCION", activo: true },
  { id: "COORD-001", rol: "COORDINADOR_RMA", activo: true },
  { id: "TECH-001", rol: "TECNICO", activo: true },
  { id: "ADMIN-001", rol: "ADMINISTRADOR", activo: true },
];

describe("validarCredenciales", () => {
  test("cada usuario dummy entra con el usuario real de su rol", () => {
    const esperados: [string, string][] = [
      ["recepcion", "RECEP-001"],
      ["tecnico", "TECH-001"],
      ["coordinacion", "COORD-001"],
      ["administracion", "ADMIN-001"],
    ];
    for (const [usuario, id] of esperados) {
      assert.deepEqual(validarCredenciales(usuario, "123456", CATALOGO), {
        ok: true,
        usuarioId: id,
      });
    }
  });

  test("el usuario no distingue mayusculas ni espacios", () => {
    assert.deepEqual(validarCredenciales("  Tecnico ", "123456", CATALOGO), {
      ok: true,
      usuarioId: "TECH-001",
    });
  });

  test("credenciales incorrectas dan un mensaje claro", () => {
    for (const [usuario, contrasena] of [
      ["recepcion", "000000"],
      ["desconocido", "123456"],
      ["", ""],
      ["recepcion", " 123456"],
    ]) {
      const resultado = validarCredenciales(usuario, contrasena, CATALOGO);
      assert.equal(resultado.ok, false);
      assert.equal(
        !resultado.ok && resultado.mensaje,
        "Usuario o contraseña incorrectos.",
      );
    }
  });

  test("sin un usuario activo de ese rol no se ingresa", () => {
    const sinTecnico = CATALOGO.map((u) =>
      u.rol === "TECNICO" ? { ...u, activo: false } : u,
    );
    const resultado = validarCredenciales("tecnico", "123456", sinTecnico);
    assert.equal(resultado.ok, false);
  });
});

describe("sesion recordada", () => {
  const almacen = new Map<string, string>();
  beforeEach(() => {
    almacen.clear();
    (globalThis as { window?: unknown }).window = {
      localStorage: {
        getItem: (k: string) => almacen.get(k) ?? null,
        setItem: (k: string, v: string) => void almacen.set(k, v),
        removeItem: (k: string) => void almacen.delete(k),
      },
    };
  });

  test("la seleccion del selector anterior no abre sesion", () => {
    almacen.set("rt-rma.usuarioDemo", "RECEP-001");
    assert.equal(leerUsuarioDemo(), null);
    assert.equal(elegirUsuarioDemo(CATALOGO, leerUsuarioDemo()), "");
  });

  test("tras ingresar se conserva al recargar", () => {
    guardarUsuarioDemo("TECH-001");
    assert.equal(elegirUsuarioDemo(CATALOGO, leerUsuarioDemo()), "TECH-001");
    assert.equal(almacen.has("rt-rma.usuarioDemo"), false);
  });

  test("cerrar sesion vuelve al login", () => {
    guardarUsuarioDemo("ADMIN-001");
    borrarUsuarioDemo();
    assert.equal(leerUsuarioDemo(), null);
    assert.equal(elegirUsuarioDemo(CATALOGO, leerUsuarioDemo()), "");
  });
});
