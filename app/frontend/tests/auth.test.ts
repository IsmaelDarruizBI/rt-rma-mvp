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
  MENSAJE_CREDENCIALES,
  mensajeDeIngreso,
} from "../src/auth/sesion.ts";
import { identidadDeUsuario, normalizarUsuario } from "../src/auth/usuario.ts";

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
      {
        modo: "supabase",
        url: URL_PROYECTO,
        clave: PUBLICABLE,
        dominio: "usuarios.rma.invalid",
      },
    );
  });

  test("el dominio de las identidades internas es configurable y se valida", () => {
    const base = {
      DEV: false,
      VITE_SUPABASE_URL: URL_PROYECTO,
      VITE_SUPABASE_PUBLISHABLE_KEY: PUBLICABLE,
    };
    const propio = configuracionAuth({ ...base, VITE_AUTH_DOMINIO_USUARIOS: "Cuentas.RMA.invalid" });
    assert.equal(propio.modo === "supabase" && propio.dominio, "cuentas.rma.invalid");
    for (const malo of ["sin-punto", "a@b.invalid", "con espacio.invalid"]) {
      assert.equal(configuracionAuth({ ...base, VITE_AUTH_DOMINIO_USUARIOS: malo }).modo, "invalida", malo);
    }
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

/** Un Supabase Auth simulado: las cuentas son identidades internas. */
class AuthSimulado implements ClienteAuth {
  sesion: { access_token: string } | null = null;
  renovaciones = 0;
  vencido = false;
  cierres: string[] = [];
  falla: "red" | "limite" | null = null;
  intentos: string[] = [];
  /** identidad -> contraseña; "bloqueada" simula una cuenta deshabilitada. */
  cuentas = new Map([
    ["recepcion@usuarios.rma.invalid", "correcta"],
    ["baja@usuarios.rma.invalid", "bloqueada"],
  ]);

  async signInWithPassword({ email, password }: { email: string; password: string }) {
    this.intentos.push(email);
    if (this.falla === "red") throw new TypeError("Failed to fetch");
    if (this.falla === "limite") {
      return {
        data: { session: null },
        error: { message: "Too many requests", status: 429, code: "over_request_rate_limit" },
      };
    }
    const clave = this.cuentas.get(email);
    if (clave === "bloqueada" && password === "correcta") {
      return {
        data: { session: null },
        error: { message: "User is banned", status: 400, code: "user_banned" },
      };
    }
    if (clave !== password) {
      // Supabase no distingue usuario inexistente de contraseña incorrecta.
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
      this.sesion = { access_token: "token-" + (this.renovaciones + 1) };
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

describe("usuario -> identidad interna", () => {
  test("se normaliza y se valida el formato", () => {
    assert.equal(normalizarUsuario("  JPerez "), "jperez");
    assert.equal(identidadDeUsuario("recepcion.1"), "recepcion.1@usuarios.rma.invalid");
    assert.equal(identidadDeUsuario("ana_g", "cuentas.rma.invalid"), "ana_g@cuentas.rma.invalid");
    for (const malo of ["", "ab", "a@b", "con espacio", "-empieza", "x".repeat(33), "ñandu"]) {
      assert.equal(normalizarUsuario(malo), null, malo);
    }
  });
});

describe("GestorSesion", () => {
  test("login correcto e incorrecto con usuario y contraseña", async () => {
    const auth = new AuthSimulado();
    const gestor = new GestorSesion(auth);
    assert.deepEqual(await gestor.iniciar("", ""), {
      ok: false,
      mensaje: "Ingresá tu usuario y tu contraseña.",
    });
    assert.deepEqual(await gestor.iniciar("recepcion", "otra"), {
      ok: false,
      mensaje: MENSAJE_CREDENCIALES,
    });
    assert.equal(await gestor.token(), null);
    assert.deepEqual(await gestor.iniciar(" Recepcion ", "correcta"), { ok: true });
    assert.equal(await gestor.token(), "token-1");
    // Supabase recibe la identidad interna, nunca lo que escribió la persona.
    assert.deepEqual(auth.intentos, [
      "recepcion@usuarios.rma.invalid",
      "recepcion@usuarios.rma.invalid",
    ]);
  });

  test("sin enumerar: inexistente, formato imposible y bloqueada dan el mismo mensaje", async () => {
    const auth = new AuthSimulado();
    const gestor = new GestorSesion(auth, { maximoFallos: 99 });
    const inexistente = await gestor.iniciar("nadie", "correcta");
    const mala = await gestor.iniciar("recepcion", "otra");
    const imposible = await gestor.iniciar("a b@c", "correcta");
    const bloqueada = await gestor.iniciar("baja", "correcta");
    for (const r of [inexistente, mala, imposible, bloqueada]) {
      assert.deepEqual(r, { ok: false, mensaje: MENSAJE_CREDENCIALES });
    }
    // Un nombre que no puede existir ni siquiera llega a Supabase.
    assert.equal(auth.intentos.length, 3);
  });

  test("después de varios fallos seguidos hay que esperar", async () => {
    const auth = new AuthSimulado();
    let ahora = 1_000_000;
    const gestor = new GestorSesion(auth, {
      maximoFallos: 3,
      esperaMs: 30_000,
      reloj: () => ahora,
    });
    for (let n = 0; n < 3; n++) await gestor.iniciar("recepcion", "otra");
    const enEspera = await gestor.iniciar("recepcion", "correcta");
    assert.equal(enEspera.ok, false);
    assert.match((enEspera as { mensaje: string }).mensaje, /Esperá 30 s/);
    assert.equal(auth.intentos.length, 3, "durante la espera no se consulta a Supabase");
    ahora += 30_001;
    assert.deepEqual(await gestor.iniciar("recepcion", "correcta"), { ok: true });
    // El éxito reinicia el conteo: dos fallos más no bloquean.
    await gestor.iniciar("recepcion", "otra");
    await gestor.iniciar("recepcion", "otra");
    assert.equal(auth.intentos.length, 6);
  });

  test("el límite del servidor (429) se informa sin revelar la cuenta", async () => {
    const auth = new AuthSimulado();
    auth.falla = "limite";
    const resultado = await new GestorSesion(auth).iniciar("recepcion", "correcta");
    assert.match((resultado as { mensaje: string }).mensaje, /Demasiados intentos/);
  });

  test("el token vencido se renueva antes de usarlo", async () => {
    const auth = new AuthSimulado();
    const gestor = new GestorSesion(auth);
    await gestor.iniciar("recepcion", "correcta");
    auth.vencido = true;
    assert.equal(await gestor.token(), "token-2");
    assert.equal(auth.renovaciones, 1);
    assert.equal(await gestor.token(), "token-2");
  });

  test("cerrar sesión borra la sesión local, aun sin conexión", async () => {
    const auth = new AuthSimulado();
    const gestor = new GestorSesion(auth);
    await gestor.iniciar("recepcion", "correcta");
    auth.falla = "red";
    await gestor.cerrar();
    assert.deepEqual(auth.cierres, ["local"]);
    assert.equal(await gestor.token(), null);
  });

  test("sin conexión al iniciar, un mensaje claro", async () => {
    const auth = new AuthSimulado();
    auth.falla = "red";
    const resultado = await new GestorSesion(auth).iniciar("recepcion", "x");
    assert.equal(resultado.ok, false);
    assert.match((resultado as { mensaje: string }).mensaje, /No se pudo contactar/);
  });

  test("mensajes de los errores de Supabase Auth", () => {
    assert.match(mensajeDeIngreso({ message: "", status: 429 }), /Demasiados intentos/);
    for (const code of ["invalid_credentials", "email_not_confirmed", "user_banned"]) {
      assert.equal(mensajeDeIngreso({ message: "", code, status: 400 }), MENSAJE_CREDENCIALES);
    }
    assert.match(mensajeDeIngreso({ message: "", status: 503 }), /No se pudo contactar/);
  });
});
