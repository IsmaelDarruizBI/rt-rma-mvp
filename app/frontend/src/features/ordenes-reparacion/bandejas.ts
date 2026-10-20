/**
 * Presentación de las bandejas de trabajo.
 *
 * Qué Órdenes van en cada bandeja, en qué orden, si están trabajables o
 * bloqueadas y qué puede resolver el usuario lo calcula el backend
 * (`app/application/bandejas.py`). Acá solo se arma el texto y se separa
 * lo pendiente de lo que es para seguir. Sin dependencias de React para
 * probarlo con `node --test`.
 */

import type { Bandeja, ItemBandeja, TrabajoBandeja } from "../../types/api";

/** Bandejas donde la fila es una toma activa. */
const DE_TOMAS = ["MIS_TOMADAS", "EN_TALLER"];

export interface BandejasSeparadas {
  /** Tareas con algo para hacer, en el orden del backend. */
  pendientes: Bandeja[];
  /** Tareas vacías: se nombran en una línea. */
  vacias: Bandeja[];
  /** Para seguir, plegadas. */
  seguimiento: Bandeja[];
}

export function separarBandejas(bandejas: Bandeja[]): BandejasSeparadas {
  return {
    pendientes: bandejas.filter((b) => b.tipo === "TAREAS" && b.cantidad > 0),
    vacias: bandejas.filter((b) => b.tipo === "TAREAS" && b.cantidad === 0),
    seguimiento: bandejas.filter((b) => b.tipo === "SEGUIMIENTO"),
  };
}

/** Total de pendientes del usuario (una Orden puede contar en dos). */
export function totalPendiente(bandejas: Bandeja[]): number {
  return separarBandejas(bandejas).pendientes.reduce(
    (total, bandeja) => total + bandeja.cantidad,
    0,
  );
}

/**
 * Qué hay que hacer, dicho para quien mira: lo suyo tal cual; lo de otro,
 * con quién lo resuelve.
 */
export function lineaDeTarea(
  item: ItemBandeja,
  codigo: string,
): string | null {
  if (!item.tarea) return null;
  const responsable = item.responsable ?? "otro sector";
  if (DE_TOMAS.includes(codigo)) {
    return item.puede_resolver
      ? `Próximo paso: ${item.tarea}`
      : `Esperando a ${responsable}: ${item.tarea}`;
  }
  return item.puede_resolver
    ? item.tarea
    : `Le toca a ${responsable}: ${item.tarea}`;
}

/** La fecha que mide la espera y cómo nombrarla. */
export function antiguedadDe(
  item: ItemBandeja,
  codigo: string,
): { texto: string; fecha: string } {
  if (DE_TOMAS.includes(codigo) && item.tomada_desde) {
    return { texto: "Tomada", fecha: item.tomada_desde };
  }
  if (item.desde) return { texto: "En esta situación", fecha: item.desde };
  return { texto: "Ingresó", fecha: item.orden.created_at };
}

/**
 * Los trabajos que importan en cada bandeja: en el taller, los que se
 * pueden hacer (o se están haciendo); en la cola, los trabajables.
 */
export function trabajosDe(
  item: ItemBandeja,
  codigo: string,
): TrabajoBandeja[] {
  if (codigo === "COLA") return item.trabajos.filter((t) => t.trabajable);
  if (DE_TOMAS.includes(codigo)) {
    return item.trabajos.filter((t) => !t.pendiente_autorizacion);
  }
  return item.trabajos;
}

/** Cómo está un trabajo, con los datos que manda el backend. */
export function estadoDeTrabajo(trabajo: TrabajoBandeja): string {
  if (trabajo.en_curso) return "en reparación";
  if (trabajo.pendiente_comprobante_ingreso) {
    return "pendiente de comprobante de ingreso";
  }
  if (trabajo.pendiente_autorizacion) return "esperando autorización";
  if (trabajo.condicion === "BLOQUEADO_POR_RECURSOS") return "sin repuestos";
  if (trabajo.condicion === "REQUIERE_DEFINICION") return "requiere revisión";
  if (trabajo.estado === "COMPLETO") return "realizado";
  return trabajo.trabajable ? "para hacer" : "pendiente";
}

/** La estación que propone el formulario de la cola: la primera compatible. */
export function estacionPropuesta(item: ItemBandeja): string | null {
  return item.estaciones[0]?.id ?? null;
}
