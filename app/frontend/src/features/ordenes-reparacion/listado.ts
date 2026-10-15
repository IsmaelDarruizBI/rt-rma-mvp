/**
 * Búsqueda, filtros y orden del listado de Órdenes.
 *
 * Funciones puras sobre los resúmenes que ya manda `GET /api/orders`: no
 * hay consultas por Orden ni reglas nuevas. La situación y el sector que
 * debe actuar los calcula el backend (`situacion`); acá solo se comparan.
 * Sin dependencias de React para poder probarlas con `node --test`.
 */

import type { OrdenResumen, RolUsuario } from "../../types/api";

/** Atajos de la barra del listado. */
export type FiltroRapido = "TODAS" | "ABIERTAS" | "MI_SECTOR" | "CERRADAS";

export type CriterioOrden =
  | "INGRESO_RECIENTE"
  | "INGRESO_ANTIGUO"
  | "PRIORIDAD"
  | "ACTIVIDAD";

export interface FiltrosListado {
  texto: string;
  rapido: FiltroRapido;
  /** "" = cualquiera. */
  situacion: string;
  /** Rol del sector que tiene que actuar. */
  sector: string;
  estado: string;
  origen: string;
  tecnico: string;
  orden: CriterioOrden;
}

export const FILTROS_INICIALES: FiltrosListado = {
  texto: "",
  rapido: "TODAS",
  situacion: "",
  sector: "",
  estado: "",
  origen: "",
  tecnico: "",
  orden: "INGRESO_RECIENTE",
};

const RAPIDOS: FiltroRapido[] = ["TODAS", "ABIERTAS", "MI_SECTOR", "CERRADAS"];
const CRITERIOS: CriterioOrden[] = [
  "INGRESO_RECIENTE",
  "INGRESO_ANTIGUO",
  "PRIORIDAD",
  "ACTIVIDAD",
];

/**
 * Filtros leídos de un almacenamiento (o de cualquier origen): lo que no
 * tiene la forma esperada vuelve al valor inicial.
 */
export function filtrosValidos(valor: unknown): FiltrosListado {
  if (typeof valor !== "object" || valor === null) return FILTROS_INICIALES;
  const datos = valor as Record<string, unknown>;
  const texto = (clave: keyof FiltrosListado) =>
    typeof datos[clave] === "string" ? (datos[clave] as string) : "";
  return {
    texto: texto("texto"),
    rapido: RAPIDOS.includes(datos.rapido as FiltroRapido)
      ? (datos.rapido as FiltroRapido)
      : FILTROS_INICIALES.rapido,
    situacion: texto("situacion"),
    sector: texto("sector"),
    estado: texto("estado"),
    origen: texto("origen"),
    tecnico: texto("tecnico"),
    orden: CRITERIOS.includes(datos.orden as CriterioOrden)
      ? (datos.orden as CriterioOrden)
      : FILTROS_INICIALES.orden,
  };
}

/** Minúsculas, sin acentos y con un solo espacio entre palabras. */
export function normalizar(texto: string): string {
  return texto
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

/** Sin espacios, guiones, puntos ni barras: «341-555 0101» = «3415550101». */
function compacto(texto: string): string {
  return normalizar(texto).replace(/[\s\-./]/g, "");
}

/** Los campos por los que se puede encontrar una Orden. */
function camposDeBusqueda(orden: OrdenResumen): string[] {
  return [
    orden.id,
    orden.cliente_nombre,
    orden.cliente_telefono ?? "",
    orden.equipo_marca,
    orden.equipo_modelo,
    orden.equipo,
    orden.imei ?? "",
    orden.numero_serie ?? "",
    orden.referencia_rt ?? "",
  ];
}

/**
 * ¿La Orden coincide con lo buscado? Cada palabra tiene que aparecer en
 * algún campo (búsqueda parcial, sin mayúsculas ni acentos); también se
 * compara sin separadores, para teléfonos, IMEI o números de OR.
 */
export function coincide(orden: OrdenResumen, busqueda: string): boolean {
  const palabras = normalizar(busqueda).split(" ").filter(Boolean);
  if (palabras.length === 0) return true;
  const campos = camposDeBusqueda(orden);
  const normales = campos.map(normalizar).join(" | ");
  const compactos = campos.map(compacto).join(" | ");
  const juntas = compacto(busqueda);
  if (juntas.length > 0 && compactos.includes(juntas)) return true;
  return palabras.every(
    (palabra) =>
      normales.includes(palabra) || compactos.includes(compacto(palabra)),
  );
}

/** Pendiente de un sector: la situación nombra su rol entre los que actúan. */
export function pendienteDelSector(
  orden: OrdenResumen,
  rol: RolUsuario | null,
): boolean {
  return (
    rol !== null &&
    !orden.cerrada &&
    (orden.situacion?.roles ?? []).includes(rol)
  );
}

export function filtrarOrdenes(
  ordenes: OrdenResumen[],
  filtros: FiltrosListado,
  rol: RolUsuario | null,
): OrdenResumen[] {
  return ordenes.filter((orden) => {
    if (filtros.rapido === "ABIERTAS" && orden.cerrada) return false;
    if (filtros.rapido === "CERRADAS" && !orden.cerrada) return false;
    if (filtros.rapido === "MI_SECTOR" && !pendienteDelSector(orden, rol)) {
      return false;
    }
    if (filtros.situacion && orden.situacion?.codigo !== filtros.situacion) {
      return false;
    }
    if (
      filtros.sector &&
      !pendienteDelSector(orden, filtros.sector as RolUsuario)
    ) {
      return false;
    }
    if (filtros.estado && orden.estado_workflow !== filtros.estado) {
      return false;
    }
    if (filtros.origen && orden.origen !== filtros.origen) return false;
    if (filtros.tecnico && orden.tecnico_id !== filtros.tecnico) return false;
    return coincide(orden, filtros.texto);
  });
}

function comparar(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/**
 * Ordena sin mutar la lista. Con valores iguales decide la fecha de
 * ingreso (más reciente primero) y después el número de Orden, así que el
 * resultado es estable.
 *
 * Por prioridad se usa el lugar que publica el backend
 * (`posicion_por_prioridad`): 1 Urgente, 2, 3, 4 Normal y al final las
 * Órdenes sin prioridad vigente (sin asignar, cerradas o canceladas), con
 * el ingreso más antiguo primero ante la misma prioridad. Acá no se
 * interpreta ningún número de prioridad.
 */
export function ordenarOrdenes(
  ordenes: OrdenResumen[],
  criterio: CriterioOrden,
): OrdenResumen[] {
  const desempate = (a: OrdenResumen, b: OrdenResumen) =>
    comparar(b.created_at, a.created_at) || comparar(b.id, a.id);
  return [...ordenes].sort((a, b) => {
    switch (criterio) {
      case "INGRESO_ANTIGUO":
        return comparar(a.created_at, b.created_at) || comparar(a.id, b.id);
      case "PRIORIDAD":
        return (
          a.posicion_por_prioridad - b.posicion_por_prioridad ||
          desempate(a, b)
        );
      case "ACTIVIDAD":
        return comparar(b.updated_at, a.updated_at) || desempate(a, b);
      default:
        return desempate(a, b);
    }
  });
}

/** Búsqueda, filtros y orden, en ese orden. */
export function aplicarListado(
  ordenes: OrdenResumen[],
  filtros: FiltrosListado,
  rol: RolUsuario | null,
): OrdenResumen[] {
  return ordenarOrdenes(filtrarOrdenes(ordenes, filtros, rol), filtros.orden);
}

/** Cuántos filtros (además de la búsqueda y el atajo) están activos. */
export function filtrosActivos(filtros: FiltrosListado): number {
  return [
    filtros.situacion,
    filtros.sector,
    filtros.estado,
    filtros.origen,
    filtros.tecnico,
  ].filter(Boolean).length;
}
