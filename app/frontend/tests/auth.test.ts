/**
 * Acceso: qué modo usa cada build y la sesión de Supabase Auth (inicio,
 * renovación del token y cierre), con un cliente simulado.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { configuracionAuth } from "../src/auth/config.ts";
import {
  type ClienteAuth,
  GestorSesion,
  mensajeDeIngreso,
} from "../src/auth/sesion.ts";

const URL_PROYECTO = "https://proyecto.supabase.co";
const PUBLICABLE = "sb_publishable_prueba";

describe("configuracionAuth", () => {
  test("en desarrollo, sin nada configurado, es el acceso de prueba", () => {
    assert.deepEqual(configuracionAuth({ DEV: true }), { modo: "demo" });
  });

  test("un build de producción nunca cae al acceso de prueba", () => {
    assert.equal(configuracionAuth({ DEV: false }).modo, "invalida");
    assert.equal(
      configuracionAuth({ DEV: false, VITE_AUTH_MODO: "demo" }).modo,
      "invalida",
    );
  });

  test("supabase con URL y clave publicable", () => {
    assert.deepEqual(
      configuracionAuth({
        DEV: false,
        VITE_AUTH_MODO: "supabase",
        VITE_SUPABASE_URL: `${URL_PROYECTO}/`,
        VITE_SUPABASE_PUBLISHABLE_KEY: PUBLICABLE,
      }),
      { modo: "supabase", url: URL_PROYECTO, clave: PUBLICABLE },
    );
  });

  test("rechaza la falta de datos, http y las claves secretas", () => {
    const base = { DEV: false, VITE_SUPABASE_URL: URL_PROYECTO };
    assert.equal(configuracionAuth(base).modo, "invalida");
    assert.equal(
      configuracionAuth({
        ...base,
        VITE_SUPABASE_URL: "http://proyecto.supabase.co",
        VITE_SUPABASE_PUBLISHABLE_KEY: PUBLICABLE,
      }).modo,
      "invalida",
    );
    assert.equal(
      configuracionAuth({ ...base, VITE_SUPABASE_PUBLISHABLE_KEY: "sb_secret_x" })
        .modo,
      "invalida",
    );
    const servicio = [
      "eyJhbGciOiJIUzI1NiJ9",
      btoa(JSON.stringify({ role: "service_role" })).replace(/=+$/, ""),
      "firma",
    ].join(".");
    assert.equal(
      configuracionAuth({ ...base, VITE_SUPABASE_PUBLISHABLE_KEY: servicio })
        .modo,
      "invalida",
    );
  });
});

/** Un Supabase Auth simulado: una cuenta, tokens que se renuevan. */
class AuthSimulado implements ClienteAuth {
  sesion: { access_token: string } | null = null;
  renovaciones = 0;
  vencido = false;
  cierres: string[] = [];
  falla: "red" | null = null;

  async signInWithPassword({ email, password }: { email: string; password: string }) {
    if (this.falla === "red") throw new TypeError("Failed to fetch");
    if (email !== "recepcion@rt.test" || password !== "correcta") {
      return {
        data: { session: null },
        error: { message: "Invalid login credentials", status: 400, code: "invalid_credentials" },
      };
    }
    this.sesion = { access_token: "token-1" };
    return { data: { session: this.sesion }, error: null };
  }

  async getSession() {
    // Como el cliente real: si el token venció, lo renueva antes de darlo.
    if (this.sesion && this.vencido) {
      this.renovaciones += 1;
      this.sesion = { access_token: `token-${this.renovaciones + 1}` };
      this.vencido = false;
    }
    return { data: { session: this.sesion }, error: null };
  }

  async signOut(opciones?: { scope?: "global" | "local" | "others" }) {
    this.cierres.push(opciones?.scope ?? "global");
    this.sesion = null;
    if (this.falla === "red") throw new TypeError("Failed to fetch");
    return { error: null };
  }
}

describe("GestorSesion", () => {
  test("inicio de sesión correcto e incorrecto", async () => {
    const auth = new AuthSimulado();
    const gestor = new GestorSesion(auth);
    assert.deepEqual(await gestor.iniciar("", ""), {
      ok: false,
      mensaje: "Ingresá tu email y tu contraseña.",
    });
    assert.deepEqual(await gestor.iniciar("recepcion@rt.test", "otra"), {
      ok: false,
      mensaje: "Email o contraseña incorrectos.",
    });
    assert.equal(await gestor.token(), null);
    assert.deepEqual(await gestor.iniciar(" recepcion@rt.test ", "correcta"), {
      ok: true,
    });
    assert.equal(await gestor.token(), "token-1");
  });

  test("el token vencido se renueva antes de usarlo", async () => {
    const auth = new AuthSimulado();
    const gestor = new GestorSesion(auth);
    await gestor.iniciar("recepcion@rt.test", "correcta");
    auth.vencido = true;
    assert.equal(await gestor.token(), "token-2");
    assert.equal(auth.renovaciones, 1);
    assert.equal(await gestor.token(), "token-2");
  });

  test("cerrar sesión borra la sesión local, aun sin conexión", async () => {
    const auth = new AuthSimulado();
    const gestor = new GestorSesion(auth);
    await gestor.iniciar("recepcion@rt.test", "correcta");
    auth.falla = "red";
    await gestor.cerrar();
    assert.deepEqual(auth.cierres, ["local"]);
    assert.equal(await gestor.token(), null);
  });

  test("sin conexión al iniciar, un mensaje claro", async () => {
    const auth = new AuthSimulado();
    auth.falla = "red";
    const resultado = await new GestorSesion(auth).iniciar("a@b.c", "x");
    assert.equal(resultado.ok, false);
    assert.match(
      (resultado as { mensaje: string }).mensaje,
      /No se pudo contactar/,
    );
  });

  test("mensajes de los errores de Supabase Auth", () => {
    assert.match(mensajeDeIngreso({ message: "", status: 429 }), /Demasiados intentos/);
    assert.match(mensajeDeIngreso({ message: "", code: "user_banned", status: 403 }), /deshabilitada/);
    assert.match(mensajeDeIngreso({ message: "", status: 503 }), /No se pudo contactar/);
  });
});
