/**
 * El cliente de Supabase Auth: solo la sesión (email y contraseña,
 * renovación del token y cierre). El frontend no lee tablas: todo dato
 * pasa por la API de FastAPI con el token de la sesión.
 */

import { AuthClient } from "@supabase/auth-js";

import type { ClienteAuth } from "./sesion";

// Un solo cliente por proyecto: dos instancias sobre la misma sesión
// guardada podrían renovarla a la vez.
const clientes = new Map<string, ClienteAuth>();

export function crearClienteAuth(url: string, clavePublicable: string): ClienteAuth {
  const clave = `${url}|${clavePublicable}`;
  const existente = clientes.get(clave);
  if (existente) return existente;
  const cliente = new AuthClient({
    url: `${url}/auth/v1`,
    headers: { apikey: clavePublicable },
    storageKey: "rt-rma.sesion",
    persistSession: true,
    autoRefreshToken: true,
    // Sin enlaces mágicos ni OAuth: no hay sesión que leer de la URL.
    detectSessionInUrl: false,
  });
  clientes.set(clave, cliente);
  return cliente;
}
