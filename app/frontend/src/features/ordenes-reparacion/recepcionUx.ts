/**
 * Lógica de presentación de la iteración de UX de Recepción
 * (docs/ux-recepcion.md). Sin dependencias del DOM: se prueba con
 * `npm test`. No decide reglas: arma lo que se muestra o se envía con los
 * datos que ya entrega el backend.
 */

import type {
  Cliente,
  Detalle,
  Orden,
  TipoReparacion,
} from "../../types/api";
import { normalizarDni } from "./clientes.ts";

// --- UX-03: observaciones del equipo -----------------------------------

/**
 * El texto único «Observaciones del equipo» (lo que declara el cliente, el
 * problema, el estado estético y otras observaciones) se registra en los
 * tres datos que ya existen: falla declarada, estado físico y observación
 * visible. Así siguen valiendo las exigencias del comprobante y de la
 * recepción. Las notas internas van aparte y nunca salen en documentos.
 */
export function datosObservacionesUnificadas(
  observaciones: string,
  notasInternas: string,
): {
  falla_reportada: string;
  recepcion: {
    estado_fisico: string | null;
    accesorios: string[];
    observaciones: string | null;
    notas_internas: string | null;
  };
} {
  const texto = observaciones.trim();
  return {
    falla_reportada: texto,
    recepcion: {
      estado_fisico: texto || null,
      accesorios: [],
      observaciones: texto || null,
      notas_internas: notasInternas.trim() || null,
    },
  };
}

/**
 * Lo que se muestra de la recepción de una Orden. Si falla declarada y
 * observaciones son el mismo texto (Órdenes nuevas), uno solo; en las
 * anteriores, cada dato con su nombre.
 */
export function observacionesParaMostrar(
  orden: Pick<Orden, "equipo" | "recepcion">,
): { etiqueta: string; texto: string }[] {
  const falla = (orden.equipo.falla_reportada ?? "").trim();
  const datos = orden.recepcion?.datos;
  const observaciones = (datos?.observaciones ?? "").trim();
  const estado = (datos?.estado_fisico ?? "").trim();
  if (falla && observaciones === falla) {
    const lista = [{ etiqueta: "Observaciones del equipo", texto: falla }];
    if (estado && estado !== falla) {
      lista.push({ etiqueta: "Estado físico", texto: estado });
    }
    return lista;
  }
  return [
    { etiqueta: "Falla declarada", texto: falla },
    { etiqueta: "Estado físico", texto: estado },
    { etiqueta: "Observaciones", texto: observaciones },
  ].filter((dato) => dato.texto !== "");
}

// --- UX-04: trabajo inicial ---------------------------------------------

/**
 * Tipos que se ofrecen como trabajo inicial en el alta: los activos.
 * «Otros» (descripción y precio a mano) se carga en la Orden, donde están
 * sus campos.
 */
export function tiposParaTrabajoInicial(
  tipos: TipoReparacion[],
  tipoOtros: string,
): TipoReparacion[] {
  return tipos.filter((tipo) => tipo.activo && tipo.id !== tipoOtros);
}

// --- UX-06: DNI antes del comprobante ----------------------------------

/**
 * Aviso antes de generar el comprobante de ingreso: el comprobante muestra
 * el DNI del cliente. No bloquea ni inventa: solo informa.
 */
export function avisoDni(
  cliente: Pick<Cliente, "dni"> | null | undefined,
): string | null {
  if (!cliente) return null;
  const dni = (cliente.dni ?? "").trim();
  if (!dni) {
    return "El cliente no tiene DNI cargado: el comprobante dirá «sin DNI».";
  }
  if (normalizarDni(dni) === null) {
    return `El DNI cargado (${dni}) no es válido: revisalo antes de imprimir.`;
  }
  return null;
}

// --- UX-08: recargo por medio de pago -----------------------------------

/**
 * Recargo de un cobro, como lo calcula el backend: porcentaje sobre el
 * importe, redondeado al centavo (mitad hacia arriba). En centavos enteros
 * para no arrastrar errores de coma flotante.
 */
export function recargoDe(
  monto: string,
  porcentaje: string | number,
): { recargo: number; total: number } | null {
  const importe = Number(monto);
  const pct = Number(porcentaje);
  if (!Number.isFinite(importe) || importe <= 0) return null;
  if (!Number.isFinite(pct) || pct <= 0) return { recargo: 0, total: importe };
  const centavos = Math.round(importe * 100);
  // Porcentaje en centésimos enteros (2.5 % = 250): cuentas exactas.
  const recargoCentavos = Math.floor(
    (centavos * Math.round(pct * 100) + 5000) / 10000,
  );
  return {
    recargo: recargoCentavos / 100,
    total: (centavos + recargoCentavos) / 100,
  };
}

// --- UX-10: resultado técnico -------------------------------------------

export type ResultadoTecnico =
  | "REPARADO"
  | "SIN_REPARACION"
  | "CANCELADA"
  | "EN_CURSO"
  | "SIN_TRABAJOS";

/** Resultado de cada trabajo, con lo que ya registra el backend. */
export function resultadoDeTrabajo(detalle: Detalle): string {
  if (detalle.estado === "CANCELADO") {
    return detalle.cancelacion?.origen === "RECHAZO_CLIENTE"
      ? "Rechazado por el cliente"
      : detalle.cancelacion?.origen === "DESISTIMIENTO_CLIENTE"
        ? "Cancelado: el cliente desistió"
        : "Cancelado";
  }
  if (detalle.estado === "COMPLETO") {
    return detalle.control_estado === "APROBADO"
      ? "Reparado (control aprobado)"
      : "Completo, falta el control técnico";
  }
  if (detalle.pendiente_de_retrabajo) return "Control rechazado: retrabajo";
  if (detalle.estado === "EN_PROGRESO") return "En reparación";
  return "Pendiente";
}

/**
 * Resultado de la Orden, derivado (sin estados nuevos): reparada cuando la
 * reparación está lista o entregada con trabajos aprobados; sin reparación
 * cuando la revisión lo concluyó (PROC-REP-069); cancelada; si no, en
 * curso.
 */
export function resultadoTecnico(
  orden: Pick<
    Orden,
    "estado_workflow" | "finalizada_sin_reparacion" | "reparaciones_detail"
  >,
): ResultadoTecnico {
  if (orden.finalizada_sin_reparacion) return "SIN_REPARACION";
  const vigentes = orden.reparaciones_detail.filter(
    (detalle) => detalle.estado !== "CANCELADO",
  );
  if (orden.estado_workflow === "CANCELADA") return "CANCELADA";
  if (orden.reparaciones_detail.length === 0) return "SIN_TRABAJOS";
  const aprobados =
    vigentes.length > 0 &&
    vigentes.every(
      (detalle) =>
        detalle.estado === "COMPLETO" && detalle.control_estado === "APROBADO",
    );
  if (
    aprobados &&
    (orden.estado_workflow === "REPARACION_LISTA" ||
      orden.estado_workflow === "ENTREGADA")
  ) {
    return "REPARADO";
  }
  return "EN_CURSO";
}

export const TEXTO_RESULTADO: Record<ResultadoTecnico, string> = {
  REPARADO: "Reparado",
  SIN_REPARACION: "Sin reparación",
  CANCELADA: "Cancelada",
  EN_CURSO: "En curso",
  SIN_TRABAJOS: "Sin trabajos cargados",
};

// --- UX-12: cabecera ----------------------------------------------------

/** Texto secundario de la barra de la Orden: solo nombre y teléfono. */
export function subtituloOrden(
  orden: Pick<Orden, "cliente" | "origen">,
): string {
  if (!orden.cliente) {
    return orden.origen === "RT_INTERNO" ? "Equipo RT interno" : "";
  }
  return [orden.cliente.nombre_apellido, orden.cliente.telefono]
    .filter(Boolean)
    .join(" · ");
}
