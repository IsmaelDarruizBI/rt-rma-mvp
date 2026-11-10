/**
 * La sesión de Supabase Auth, sin React ni red propia: inicia y cierra la
 * sesión y entrega el token vigente para cada pedido a la API.
 *
 * El cliente de Supabase (`@supabase/auth-js`) guarda la sesión en el
 * navegador y renueva el token antes de que venza; `getSession()` siempre
 * devuelve el vigente (y lo renueva si ya venció). Esta clase solo traduce
 * sus resultados y errores a lo que muestra la pantalla de acceso.
 */

import { DOMINIO_USUARIOS_POR_DEFECTO, identidadDeUsuario } from "./usuario.ts";

/** Lo que se usa del cliente de Supabase Auth. */
export interface ClienteAuth {
  signInWithPassword(credenciales: {
    email: string;
    password: string;
  }): Promise<{
    data: { session: { access_token: string } | null };
    error: { message: string; status?: number; code?: string } | null;
  }>;
  signOut(opciones?: { scope?: "global" | "local" | "others" }): Promise<{
    error: { message: string } | null;
  }>;
  getSession(): Promise<{
    data: { session: { access_token: string } | null };
    error: { message: string } | null;
  }>;
}

export type ResultadoIngreso = { ok: true } | { ok: false; mensaje: string };

export interface OpcionesSesion {
  /** Dominio de las identidades internas (`<usuario>@<dominio>`). */
  dominio?: string;
  /** Fallos seguidos que activan la espera (en este navegador). */
  maximoFallos?: number;
  /** Cuánto se espera, en milisegundos, después de esos fallos. */
  esperaMs?: number;
  reloj?: () => number;
}

/**
 * La sesión de un empleado: usuario y contraseña. El usuario se traduce a su
 * identidad interna (`usuario.ts`) y Supabase Auth verifica la contraseña.
 *
 * Contra la enumeración, un usuario inexistente, una contraseña incorrecta,
 * una cuenta sin confirmar o bloqueada dan el MISMO mensaje. Contra el abuso
 * de intentos, Supabase limita el endpoint por IP; además, después de
 * `maximoFallos` fallos seguidos este navegador espera `esperaMs` antes de
 * volver a intentar (no reemplaza al límite del servidor).
 */
export class GestorSesion {
  private readonly cliente: ClienteAuth;
  private readonly dominio: string;
  private readonly maximoFallos: number;
  private readonly esperaMs: number;
  private readonly reloj: () => number;
  private fallos = 0;
  private bloqueadoHasta = 0;

  constructor(cliente: ClienteAuth, opciones: OpcionesSesion = {}) {
    this.cliente = cliente;
    this.dominio = opciones.dominio ?? DOMINIO_USUARIOS_POR_DEFECTO;
    this.maximoFallos = opciones.maximoFallos ?? 5;
    this.esperaMs = opciones.esperaMs ?? 30_000;
    this.reloj = opciones.reloj ?? (() => Date.now());
  }

  async iniciar(usuario: string, contrasena: string): Promise<ResultadoIngreso> {
    if (!usuario.trim() || !contrasena) {
      return { ok: false, mensaje: "Ingresá tu usuario y tu contraseña." };
    }
    const ahora = this.reloj();
    if (ahora < this.bloqueadoHasta) {
      const segundos = Math.ceil((this.bloqueadoHasta - ahora) / 1000);
      return { ok: false, mensaje: `Demasiados intentos. Esperá ${segundos} s y volvé a probar.` };
    }
    const identidad = identidadDeUsuario(usuario, this.dominio);
    if (identidad === null) {
      // Un nombre que no puede existir: el mismo mensaje y el mismo conteo.
      return this.fallo(MENSAJE_CREDENCIALES);
    }
    let respuesta;
    try {
      respuesta = await this.cliente.signInWithPassword({
        email: identidad,
        password: contrasena,
      });
    } catch {
      return { ok: false, mensaje: MENSAJE_SIN_CONEXION };
    }
    if (respuesta.error || !respuesta.data.session) {
      const mensaje = mensajeDeIngreso(respuesta.error);
      return mensaje === MENSAJE_CREDENCIALES
        ? this.fallo(mensaje)
        : { ok: false, mensaje };
    }
    this.fallos = 0;
    this.bloqueadoHasta = 0;
    return { ok: true };
  }

  private fallo(mensaje: string): ResultadoIngreso {
    this.fallos += 1;
    if (this.fallos >= this.maximoFallos) {
      this.bloqueadoHasta = this.reloj() + this.esperaMs;
    }
    return { ok: false, mensaje };
  }

  /** El token vigente (renovado si hacía falta), o `null` sin sesión. */
  async token(): Promise<string | null> {
    try {
      const { data, error } = await this.cliente.getSession();
      if (error) return null;
      return data.session?.access_token ?? null;
    } catch {
      return null;
    }
  }

  /**
   * Cierra la sesión en este navegador. Aunque Supabase no responda, la
   * sesión local se borra: nadie queda adentro por un error de red.
   */
  async cerrar(): Promise<void> {
    try {
      await this.cliente.signOut({ scope: "local" });
    } catch {
      // Sin conexión: el cliente igual descarta la sesión local.
    }
  }
}

const MENSAJE_SIN_CONEXION =
  "No se pudo contactar al servicio de acceso. Revisá la conexión.";

/** Credenciales rechazadas, sin decir por qué (no se enumeran cuentas). */
export const MENSAJE_CREDENCIALES =
  "Usuario o contraseña incorrectos, o la cuenta no está habilitada.";

export function mensajeDeIngreso(
  error: { message: string; status?: number; code?: string } | null,
): string {
  if (!error) return "No se pudo iniciar sesión.";
  if (
    error.code === "invalid_credentials" ||
    error.code === "email_not_confirmed" ||
    error.code === "user_banned" ||
    error.status === 400
  ) {
    return MENSAJE_CREDENCIALES;
  }
  if (error.status === 429 || error.code === "over_request_rate_limit") {
    return "Demasiados intentos. Esperá un momento y volvé a probar.";
  }
  if (!error.status || error.status >= 500) return MENSAJE_SIN_CONEXION;
  return "No se pudo iniciar sesión.";
}

/** El evento que avisa que la API rechazó la sesión (401). */
export const EVENTO_SESION_VENCIDA = "rt-sesion-vencida";
