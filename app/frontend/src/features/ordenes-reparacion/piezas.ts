/**
 * Requisitos de insumo y pieza elegida de un trabajo (DEC-AJ-14, D-14.4),
 * sin React.
 *
 * - El Tipo de reparación declara requisitos (una categoría o subcategoría
 *   y una cantidad) además de sus insumos previstos concretos. Por cada
 *   requisito, el trabajo guarda la pieza concreta (un SKU) elegida antes de
 *   reservar.
 * - La elige el sistema si hay una sola compatible; si no, quien tiene
 *   PIEZA_ELEGIR (por defecto Técnico, Coordinación RMA y Administración).
 * - Antes de reservar, «Sustituir» cambia la elección (con motivo). Con la
 *   pieza reservada (trabajo en curso), libera y reserva en una sola
 *   operación. Una pieza consumida no se sustituye.
 * - Sin modelo técnico, una pieza sin compatibilidad verificada exige motivo.
 *
 * La API valida todo de nuevo: esto solo decide qué mostrar y qué enviar.
 */

import { puede, type ConRoles } from "../../lib/roles.ts";
import type {
  EstadoDetalle,
  InsumoPrevisto,
  OpcionPieza,
  RequisitoInsumoDetalle,
} from "../../types/api";

export const PERMISO_PIEZA_ELEGIR = "PIEZA_ELEGIR";

/** Predeterminados del permiso (los mismos del backend). */
export const ELIGEN_PIEZA: readonly string[] = [
  "TECNICO",
  "COORDINADOR_RMA",
  "ADMINISTRADOR",
];

/** Largo máximo del motivo (el de la API). */
export const MOTIVO_PIEZA_MAXIMO = 500;

export function puedeElegirPieza(actor: ConRoles | null): boolean {
  return puede(actor, PERMISO_PIEZA_ELEGIR, ELIGEN_PIEZA);
}

/** Lo que el Detalle trae del Tipo (sin requisitos en un backend anterior). */
interface ConRequisitos {
  insumos_previstos: InsumoPrevisto[];
  requisitos_insumo?: RequisitoInsumoDetalle[];
}

export function requisitosDe(detalle: ConRequisitos): RequisitoInsumoDetalle[] {
  return detalle.requisitos_insumo ?? [];
}

/** Los insumos previstos concretos del Tipo (sin las piezas elegidas). */
export function previstosConcretos(detalle: ConRequisitos): InsumoPrevisto[] {
  return detalle.insumos_previstos.filter((previsto) => !previsto.pieza);
}

/** Requisitos vigentes todavía sin pieza: no se puede iniciar el trabajo. */
export function requisitosPendientes(detalle: ConRequisitos): RequisitoInsumoDetalle[] {
  return requisitosDe(detalle).filter(
    (requisito) => requisito.estado === "PENDIENTE" && requisito.requisito_vigente,
  );
}

/** «1», «0.5» (sin ceros de más); el texto tal cual si no es un número. */
export function textoCantidad(cantidad: string): string {
  const numero = Number(cantidad);
  return Number.isFinite(numero) ? String(numero) : cantidad;
}

export type TonoMarca = "alerta" | "ok" | "suave" | "acento" | "error";

export interface MarcaRequisito {
  texto: string;
  tono: TonoMarca;
}

/** Las marcas de un requisito, en el orden en que se muestran. */
export function marcasDeRequisito(requisito: RequisitoInsumoDetalle): MarcaRequisito[] {
  if (requisito.estado === "PENDIENTE") {
    return [{ texto: "Pendiente de elegir", tono: "alerta" }];
  }
  const marcas: MarcaRequisito[] = [];
  if (requisito.causa === "AUTOMATICA") {
    marcas.push({ texto: "Elegida automáticamente", tono: "suave" });
  }
  if (requisito.compatibilidad_no_verificada) {
    marcas.push({ texto: "Compatibilidad no verificada", tono: "alerta" });
  }
  if (!requisito.compatible_con_modelo) {
    marcas.push({ texto: "No compatible con el modelo actual", tono: "error" });
  }
  if (requisito.reservada) marcas.push({ texto: "Reservada", tono: "acento" });
  if (requisito.consumida) marcas.push({ texto: "Consumida", tono: "ok" });
  if (!requisito.requisito_vigente) {
    marcas.push({ texto: "El tipo ya no lo pide", tono: "suave" });
  }
  return marcas;
}

/** «INS-012 · Batería iPhone 14», o «—» si todavía no hay pieza. */
export function etiquetaPiezaElegida(
  requisito: RequisitoInsumoDetalle,
  nombrar?: (insumo: { id: string; codigo: string; nombre: string }) => string,
): string {
  if (!requisito.insumo_id) return "—";
  const insumo = {
    id: requisito.insumo_id,
    codigo: requisito.insumo_codigo ?? requisito.insumo_id,
    nombre: requisito.insumo_nombre ?? "",
  };
  if (nombrar) return nombrar(insumo);
  return [insumo.codigo, insumo.nombre].filter(Boolean).join(" · ");
}

export type AccionPieza = "ELEGIR" | "SUSTITUIR";

/**
 * Qué se ofrece para el requisito: «Elegir pieza» (pendiente, antes de
 * iniciar), «Sustituir» (elegida, antes de consumirla) o nada.
 *
 * - Solo con el trabajo DEFINIDO o EN_PROGRESO y con PIEZA_ELEGIR.
 * - En curso solo se sustituye: la primera elección es antes de iniciar.
 * - Una pieza consumida no se sustituye.
 * - Un requisito que el Tipo ya no pide no se elige por primera vez.
 */
export function accionDePieza(
  estadoDetalle: EstadoDetalle,
  requisito: RequisitoInsumoDetalle,
  puedeElegir: boolean,
): AccionPieza | null {
  if (!puedeElegir || requisito.consumida) return null;
  if (estadoDetalle !== "DEFINIDO" && estadoDetalle !== "EN_PROGRESO") return null;
  if (requisito.estado === "ELEGIDA") return "SUSTITUIR";
  if (estadoDetalle === "DEFINIDO" && requisito.requisito_vigente) return "ELEGIR";
  return null;
}

/** Sustituir y elegir una pieza sin compatibilidad verificada piden motivo. */
export function exigeMotivo(
  requisito: Pick<RequisitoInsumoDetalle, "estado">,
  opcion?: Pick<OpcionPieza, "compatibilidad_no_verificada"> | null,
): boolean {
  return requisito.estado === "ELEGIDA" || Boolean(opcion?.compatibilidad_no_verificada);
}

/** ¿El disponible alcanza para la cantidad del requisito? */
export function alcanza(opcion: Pick<OpcionPieza, "disponible">, cantidad: string): boolean {
  return Number(opcion.disponible) >= Number(cantidad);
}

/** «disponible 3», «sin disponible». */
export function textoDisponible(opcion: Pick<OpcionPieza, "disponible">): string {
  const numero = Number(opcion.disponible);
  return numero > 0 ? `disponible ${textoCantidad(opcion.disponible)}` : "sin disponible";
}

export interface PedidoPieza {
  requisito_id: string;
  insumo_id: string;
  motivo: string | null;
}

/**
 * Lo que se envía al elegir o sustituir, o por qué todavía no se puede.
 * Sin pieza elegida en el formulario: ni pedido ni error (falta elegir).
 */
export function pedidoDePieza(
  requisito: RequisitoInsumoDetalle,
  opciones: readonly OpcionPieza[],
  insumoId: string,
  motivo: string,
): { pedido: PedidoPieza | null; error: string | null } {
  if (!insumoId) return { pedido: null, error: null };
  const opcion = opciones.find((candidata) => candidata.id === insumoId);
  if (!opcion) {
    return { pedido: null, error: "Esa pieza no está entre las que se pueden elegir." };
  }
  if (requisito.estado === "ELEGIDA" && requisito.insumo_id === insumoId) {
    return { pedido: null, error: "Es la pieza elegida ahora: elegí otra para sustituirla." };
  }
  const limpio = motivo.trim();
  if (limpio.length > MOTIVO_PIEZA_MAXIMO) {
    return {
      pedido: null,
      error: `El motivo admite hasta ${MOTIVO_PIEZA_MAXIMO} caracteres.`,
    };
  }
  if (!limpio && exigeMotivo(requisito, opcion)) {
    return {
      pedido: null,
      error:
        requisito.estado === "ELEGIDA"
          ? "Sustituir la pieza exige el motivo."
          : "La compatibilidad de esta pieza con el equipo no está verificada: indicá el motivo.",
    };
  }
  return {
    pedido: { requisito_id: requisito.requisito_id, insumo_id: insumoId, motivo: limpio || null },
    error: null,
  };
}

/** Código del 409 al iniciar un trabajo con un requisito sin pieza. */
export const CODIGO_PIEZA_SIN_ELEGIR = "PIEZA_SIN_ELEGIR";

export const AYUDA_PIEZA_SIN_ELEGIR =
  "Elegila con «Elegir pieza» en el trabajo (sección «Trabajos») y volvé a iniciarlo.";

/** El mensaje del error con la indicación de dónde se elige la pieza. */
export function mensajeConAyudaPieza(codigo: string, mensaje: string): string {
  return codigo === CODIGO_PIEZA_SIN_ELEGIR ? `${mensaje} ${AYUDA_PIEZA_SIN_ELEGIR}` : mensaje;
}
