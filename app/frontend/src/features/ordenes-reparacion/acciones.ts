/**
 * Reglas puras de presentación de las acciones de una Orden.
 *
 * Qué acciones puede ejecutar el usuario lo decide `puedeEjecutar` (la
 * misma regla de siempre); acá solo se ordena lo que ya está habilitado:
 * qué va en la barra superior, qué va al menú «Más acciones» y qué queda
 * pendiente. Ninguna regla de negocio nueva: tareas, avisos y acciones
 * los manda el backend en la Orden.
 *
 * Sin React ni DOM: se prueba con node --test.
 */

import type { Accion, Orden, Usuario } from "../../types/api";
import { puedeEjecutar } from "./permisos.ts";

/**
 * Acciones excepcionales: van al menú «Más acciones», aparte del flujo
 * normal. Si una resuelve la tarea actual (interrumpir junto a completar,
 * forzar sin stock al esperar repuestos) va con su tarea.
 */
export const CODIGOS_ESPECIALES = new Set([
  "INTERRUMPIR_EJECUCION",
  "REQUIERE_REDEFINICION",
  "OVERRIDE_RECURSOS",
  "LIBERAR_ORDEN",
  "LIBERAR_ORDEN_AJENA",
  "CANCELAR_DETALLE",
  "CANCELAR_ORDEN",
  "DESISTIR_DETALLE",
  "DESISTIR_TODO",
  "REGISTRAR_EQUIPO_NO_RECIBIDO",
  // DC31: devolver sin reparar es la tarea de una Orden sin trabajos
  // vigentes; en cualquier otro caso, una situacion especial.
  "REGISTRAR_DEVOLUCION",
  "ANULAR_PAGO",
  "INICIAR_GARANTIA_RMA",
  "ESPERAR_RECURSOS",
]);

/** Opción secundaria de una tarea (interrumpir junto a completar). */
export const CODIGOS_SECUNDARIOS = new Set(["INTERRUMPIR_EJECUCION"]);

/**
 * Pasos recomendados que no son una tarea del backend: si el usuario puede
 * hacerlos, se muestran como un pendiente propio. Generar el comprobante de
 * autorización sigue a registrar la autorización del cliente.
 */
export const PASOS_RECOMENDADOS: Record<
  string,
  { titulo: string; motivo: string }
> = {
  EMITIR_COMPROBANTE_AUTORIZACION: {
    titulo: "Generar el comprobante de autorización",
    motivo:
      "Para enviarle al cliente los trabajos que autorizó (no es un " +
      "comprobante de pago).",
  },
};

export function claveDeAccion(accion: Accion): string {
  return [
    accion.codigo,
    accion.detalle_id ?? "",
    accion.ejecucion_id ?? "",
    accion.pago_id ?? "",
  ].join("|");
}

/** Todas las acciones que la Orden publica, de todos sus grupos. */
export function accionesDeLaOrden(orden: Orden): Accion[] {
  return [
    ...orden.acciones_disponibles,
    ...orden.acciones_cancelacion,
    ...orden.acciones_autorizacion,
    ...orden.acciones_financieras,
    ...orden.acciones_custodia,
    ...(orden.acciones_complementarias ?? []),
  ];
}

/** Claves de las acciones que resuelven una tarea, en el orden de las tareas. */
export function clavesDeTareas(orden: Orden, actor: Usuario | null): string[] {
  const claves: string[] = [];
  if (!orden.cerrada) {
    for (const accion of accionesDeLaOrden(orden)) {
      if (accion.codigo in PASOS_RECOMENDADOS && puedeEjecutar(accion, actor)) {
        claves.push(claveDeAccion(accion));
      }
    }
  }
  for (const tarea of orden.situacion?.tareas ?? []) {
    for (const accion of tarea.acciones) {
      if (puedeEjecutar(accion, actor)) claves.push(claveDeAccion(accion));
    }
  }
  return [...new Set(claves)];
}

/** Una acción ya habilitada (su formulario existe y el usuario puede). */
export interface AccionHabilitada {
  clave: string;
  accion: Accion;
}

export interface BarraDeAcciones {
  /** Botones visibles: primero los que resuelven tareas. */
  visibles: AccionHabilitada[];
  /** El resto, en «Más acciones»: primero las comunes, después las especiales. */
  menu: AccionHabilitada[];
}

/**
 * Ordena las acciones habilitadas para la barra superior. Las que
 * resuelven una tarea van primero (la primera es la principal); las
 * excepcionales nunca ocupan un botón visible salvo que resuelvan la
 * tarea actual. Con más de `maximo` botones, el resto va al menú.
 */
export function organizarBarra(
  habilitadas: AccionHabilitada[],
  clavesTareas: string[],
  maximo = 3,
): BarraDeAcciones {
  const posicion = new Map(clavesTareas.map((clave, i) => [clave, i]));
  // Una opción secundaria (interrumpir) resuelve la tarea si es la única:
  // con el desistimiento pendiente no se ofrece completar (DC07).
  const hayPrincipal = habilitadas.some(
    (item) =>
      posicion.has(item.clave) && !CODIGOS_SECUNDARIOS.has(item.accion.codigo),
  );
  const deTareas = habilitadas
    .filter(
      (item) =>
        posicion.has(item.clave) &&
        (!hayPrincipal || !CODIGOS_SECUNDARIOS.has(item.accion.codigo)),
    )
    .sort((a, b) => posicion.get(a.clave)! - posicion.get(b.clave)!);
  const resto = habilitadas.filter((item) => !deTareas.includes(item));
  const comunes = resto.filter(
    (item) => !CODIGOS_ESPECIALES.has(item.accion.codigo),
  );
  const especiales = resto.filter((item) =>
    CODIGOS_ESPECIALES.has(item.accion.codigo),
  );
  const candidatas = [...deTareas, ...comunes];
  return {
    visibles: candidatas.slice(0, maximo),
    menu: [...candidatas.slice(maximo), ...especiales],
  };
}

/** Un pendiente de la Orden, tal como lo informa el backend. */
export interface Pendiente {
  clave: string;
  titulo: string;
  /** Quién lo resuelve (sector), si no es un titular. */
  responsable: string | null;
  /** El técnico titular que debe resolverlo, si lo hay. */
  titularId: string | null;
  /** Las acciones que el usuario actual puede ejecutar para resolverlo. */
  acciones: Accion[];
  /** Un aviso secundario (no es la tarea principal). */
  aviso: boolean;
}

/**
 * Los pendientes de la Orden: el paso recomendado, las tareas y los avisos
 * de `orden.situacion`. Nada se deduce en el frontend.
 */
export function pendientesDe(orden: Orden, actor: Usuario | null): Pendiente[] {
  const pendientes: Pendiente[] = [];
  if (!orden.cerrada) {
    for (const accion of accionesDeLaOrden(orden)) {
      if (accion.codigo in PASOS_RECOMENDADOS && puedeEjecutar(accion, actor)) {
        pendientes.push({
          clave: `recomendado-${claveDeAccion(accion)}`,
          titulo: PASOS_RECOMENDADOS[accion.codigo].titulo,
          responsable: null,
          titularId: null,
          acciones: [accion],
          aviso: false,
        });
      }
    }
  }
  const situacion = orden.situacion;
  situacion?.tareas.forEach((tarea, indice) => {
    const titular = tarea.acciones.find((accion) => accion.usuario_id);
    const ejecutables = tarea.acciones.filter((accion) =>
      puedeEjecutar(accion, actor),
    );
    const principales = ejecutables.filter(
      (accion) => !CODIGOS_SECUNDARIOS.has(accion.codigo),
    );
    // Si la tarea solo tiene la opción secundaria (interrumpir por un
    // desistimiento, DC07), esa es la acción de la tarea.
    const propias = principales.length > 0 ? principales : ejecutables;
    pendientes.push({
      clave: `tarea-${indice}-${tarea.titulo}`,
      titulo: tarea.titulo,
      responsable: titular ? null : tarea.responsable,
      titularId: titular?.usuario_id ?? null,
      acciones: propias,
      aviso: false,
    });
  });
  situacion?.avisos.forEach((aviso) => {
    pendientes.push({
      clave: `aviso-${aviso.codigo}`,
      titulo: aviso.titulo,
      responsable: aviso.responsable,
      titularId: null,
      acciones: aviso.acciones.filter((accion) => puedeEjecutar(accion, actor)),
      aviso: true,
    });
  });
  return pendientes;
}
