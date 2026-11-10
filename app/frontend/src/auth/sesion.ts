/**
 * La sesión de Supabase Auth, sin React ni red propia: inicia y cierra la
 * sesión y entrega el token vigente para cada pedido a la API.
 *
 * El cliente de Supabase (`@supabase/auth-js`) guarda la sesión en el
 * navegador y renueva el token antes de que venza; `getSession()` siempre
 * devuelve el vigente (y lo renueva si ya venció). Esta clase solo traduce
 * sus resultados y errores a lo que muestra la pantalla de acceso.
 */

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

export class GestorSesion {
  private readonly cliente: ClienteAuth;

  constructor(cliente: ClienteAuth) {
    this.cliente = cliente;
  }

  async iniciar(email: string, contrasena: string): Promise<ResultadoIngreso> {
    const correo = email.trim();
    if (!correo || !contrasena) {
      return { ok: false, mensaje: "Ingresá tu email y tu contraseña." };
    }
    let respuesta;
    try {
      respuesta = await this.cliente.signInWithPassword({
        email: correo,
        password: contrasena,
      });
    } catch {
      return { ok: false, mensaje: MENSAJE_SIN_CONEXION };
    }
    if (respuesta.error || !respuesta.data.session) {
      return { ok: false, mensaje: mensajeDeIngreso(respuesta.error) };
    }
    return { ok: true };
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

export function mensajeDeIngreso(
  error: { message: string; status?: number; code?: string } | null,
): string {
  if (!error) return "No se pudo iniciar sesión.";
  if (error.code === "invalid_credentials" || error.status === 400) {
    return "Email o contraseña incorrectos.";
  }
  if (error.code === "email_not_confirmed") {
    return "La cuenta todavía no está confirmada.";
  }
  if (error.code === "user_banned") {
    return "La cuenta está deshabilitada.";
  }
  if (error.status === 429 || error.code === "over_request_rate_limit") {
    return "Demasiados intentos. Esperá un momento y volvé a probar.";
  }
  if (!error.status || error.status >= 500) return MENSAJE_SIN_CONEXION;
  return "No se pudo iniciar sesión.";
}

/** El evento que avisa que la API rechazó la sesión (401). */
export const EVENTO_SESION_VENCIDA = "rt-sesion-vencida";
