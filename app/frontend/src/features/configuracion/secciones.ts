/**
 * Configuración por funcionalidad (Configuración v2, CFG-05), sin React.
 *
 * Cada subsección se ve con SU permiso, no con un rol: Recepción o
 * Coordinación RMA pueden administrar insumos, motivos o tipos si
 * Administración se los delega desde Permisos (CFG-03). Lo sensible
 * (usuarios, permisos, recargos y la auditoría completa) sigue siendo de
 * Administración. La API valida todo de nuevo: esto solo decide qué ofrecer.
 */

import { puede, type ConRoles } from "../../lib/roles.ts";

export type SeccionConfiguracion =
  | "tipos-reparacion"
  | "mesas"
  | "motivos"
  | "checklist"
  | "insumos"
  | "proveedores"
  | "plantillas"
  | "usuarios"
  | "permisos"
  | "recargos"
  | "auditoria";

export interface DefinicionSeccion {
  id: SeccionConfiguracion;
  grupo: string;
  titulo: string;
  /** Alcanza con alguno. */
  permisos: readonly string[];
}

/** Con una API anterior a CFG-03 (sin estos códigos) decidía el rol. */
const SOLO_ADMINISTRACION = ["ADMINISTRADOR"] as const;

export const SECCIONES_CONFIGURACION: readonly DefinicionSeccion[] = [
  { id: "tipos-reparacion", grupo: "Taller", titulo: "Tipos de reparación", permisos: ["TIPO_REPARACION_GESTIONAR"] },
  { id: "mesas", grupo: "Taller", titulo: "Mesas de trabajo", permisos: ["MESA_TIPOS_GESTIONAR"] },
  { id: "motivos", grupo: "Taller", titulo: "Motivos", permisos: ["MOTIVO_GESTIONAR"] },
  { id: "checklist", grupo: "Taller", titulo: "Checklist", permisos: ["CHECKLIST_GESTIONAR"] },
  { id: "insumos", grupo: "Inventario y compras", titulo: "Insumos", permisos: ["INSUMO_GESTIONAR"] },
  { id: "proveedores", grupo: "Inventario y compras", titulo: "Proveedores", permisos: ["PROVEEDOR_GESTIONAR"] },
  { id: "plantillas", grupo: "Comunicación", titulo: "Plantillas de WhatsApp", permisos: ["PLANTILLA_GESTIONAR"] },
  { id: "usuarios", grupo: "Sistema", titulo: "Usuarios y roles", permisos: ["ROLES_ADMINISTRAR"] },
  { id: "permisos", grupo: "Sistema", titulo: "Permisos", permisos: ["ROLES_ADMINISTRAR"] },
  { id: "recargos", grupo: "Sistema", titulo: "Recargos por medio de pago", permisos: ["CONFIGURACION_ADMINISTRAR"] },
  { id: "auditoria", grupo: "Sistema", titulo: "Auditoría", permisos: ["CONFIGURACION_ADMINISTRAR"] },
];

export function esSeccionConfiguracion(valor: string): valor is SeccionConfiguracion {
  return SECCIONES_CONFIGURACION.some((s) => s.id === valor);
}

export function definicionDe(seccion: SeccionConfiguracion): DefinicionSeccion {
  return SECCIONES_CONFIGURACION.find((s) => s.id === seccion)!;
}

/** ¿El usuario tiene alguno de estos permisos? */
export function puedeAlguno(usuario: ConRoles | null, permisos: readonly string[]): boolean {
  return permisos.some((permiso) => puede(usuario, permiso, SOLO_ADMINISTRACION));
}

export function puedeVerSeccion(usuario: ConRoles | null, seccion: SeccionConfiguracion): boolean {
  return puedeAlguno(usuario, definicionDe(seccion).permisos);
}

/** Las subsecciones que el usuario ve, en el orden del índice. */
export function seccionesPermitidas(usuario: ConRoles | null): DefinicionSeccion[] {
  return SECCIONES_CONFIGURACION.filter((s) => puedeAlguno(usuario, s.permisos));
}

/** Configuración aparece en el menú si el usuario ve alguna subsección. */
export function puedeConfigurar(usuario: ConRoles | null): boolean {
  return seccionesPermitidas(usuario).length > 0;
}

/** Los grupos del índice, cada uno con sus subsecciones permitidas. */
export function gruposDe(
  secciones: readonly DefinicionSeccion[],
): { grupo: string; secciones: DefinicionSeccion[] }[] {
  const grupos: { grupo: string; secciones: DefinicionSeccion[] }[] = [];
  for (const seccion of secciones) {
    const existente = grupos.find((g) => g.grupo === seccion.grupo);
    if (existente) existente.secciones.push(seccion);
    else grupos.push({ grupo: seccion.grupo, secciones: [seccion] });
  }
  return grupos;
}

/**
 * La subsección a mostrar: la pedida si el usuario la ve; si no pidió
 * ninguna, la primera que ve. `null` si no ve ninguna. Una pedida sin
 * permiso se devuelve igual: la pantalla explica por qué no la muestra.
 */
export function seccionAMostrar(
  usuario: ConRoles | null,
  pedida: SeccionConfiguracion | undefined,
): SeccionConfiguracion | null {
  if (pedida) return pedida;
  return seccionesPermitidas(usuario)[0]?.id ?? null;
}

/** Entidad de la auditoría de cada subsección (su propio historial). */
export const ENTIDAD_DE_SECCION: Partial<Record<SeccionConfiguracion, string>> = {
  "tipos-reparacion": "TIPO_REPARACION",
  mesas: "MESA_TRABAJO",
  motivos: "MOTIVO",
  checklist: "CHECKLIST",
  insumos: "INSUMO",
  proveedores: "PROVEEDOR",
  plantillas: "PLANTILLA",
};
