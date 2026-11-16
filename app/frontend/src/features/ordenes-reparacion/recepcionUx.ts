/**
 * Lógica de presentación de la iteración de UX de Recepción
 * (docs/ux-recepcion.md). Sin dependencias del DOM: se prueba con
 * `npm test`. No decide reglas: arma lo que se muestra o se envía con los
 * datos que ya entrega el backend.
 */

import type {
  Cliente,
  ContenidoEntrega,
  DatosRecepcion,
  Detalle,
  Orden,
  TipoReparacion,
} from "../../types/api";
import { normalizarDni } from "./clientes.ts";

// --- UX-03: observaciones del equipo -----------------------------------

/**
 * DEC-UX-03: el texto único «Observaciones del equipo» (lo que declara el
 * cliente, el problema, el estado estético y otras observaciones) se
 * registra como observación visible, con la marca `observaciones_unificadas`,
 * y como falla declarada (el problema que trae el cliente). NO se copia al
 * estado físico: no es una constatación aparte de Recepción. Con la marca,
 * el backend acepta ese texto como descripción del estado del equipo. Las
 * notas internas van aparte y nunca salen en documentos.
 */
export function datosObservacionesUnificadas(
  observaciones: string,
  notasInternas: string,
): {
  falla_reportada: string;
  recepcion: {
    estado_fisico: null;
    accesorios: string[];
    observaciones: string | null;
    notas_internas: string | null;
    observaciones_unificadas: true;
  };
} {
  const texto = observaciones.trim();
  return {
    falla_reportada: texto,
    recepcion: {
      estado_fisico: null,
      accesorios: [],
      observaciones: texto || null,
      notas_internas: notasInternas.trim() || null,
      observaciones_unificadas: true,
    },
  };
}

/** El ingreso se registró con el texto único (marca explícita). */
export function usaTextoUnico(
  datos: Pick<DatosRecepcion, "observaciones_unificadas"> | null | undefined,
): boolean {
  return datos?.observaciones_unificadas === true;
}

/**
 * Lo que se muestra de la recepción de una Orden: con la marca, el texto
 * único una vez; en lo registrado antes, cada dato con su nombre.
 */
export function observacionesParaMostrar(
  orden: Pick<Orden, "equipo" | "recepcion">,
): { etiqueta: string; texto: string }[] {
  const falla = (orden.equipo.falla_reportada ?? "").trim();
  const datos = orden.recepcion?.datos;
  const observaciones = (datos?.observaciones ?? "").trim();
  const estado = (datos?.estado_fisico ?? "").trim();
  if (usaTextoUnico(datos)) {
    return [
      { etiqueta: "Observaciones del equipo", texto: observaciones || falla },
      { etiqueta: "Estado físico", texto: estado },
    ].filter((dato) => dato.texto !== "");
  }
  return [
    { etiqueta: "Falla declarada", texto: falla },
    { etiqueta: "Estado físico", texto: estado },
    { etiqueta: "Observaciones", texto: observaciones },
  ].filter((dato) => dato.texto !== "");
}

/** El ingreso ya describe cómo se recibió el equipo (como el backend). */
export function estadoFisicoRegistrado(
  datos: DatosRecepcion | null | undefined,
): boolean {
  if (!datos) return false;
  if ((datos.estado_fisico ?? "").trim()) return true;
  return usaTextoUnico(datos) && (datos.observaciones ?? "").trim() !== "";
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

/**
 * DEC-UX-14: la parte del recargo de un pago que se devuelve con `monto`
 * (como el backend): proporcional al centavo, mitad hacia arriba; si con
 * esta devolución se completa el pago, todo el recargo que queda.
 */
export function recargoADevolver(datos: {
  montoPago: string;
  recargoPago: string;
  devueltoAntes: string;
  recargoDevueltoAntes: string;
  monto: string;
}): number {
  const c = (valor: string) => Math.round(Number(valor || "0") * 100);
  const montoPago = c(datos.montoPago);
  const recargoPago = c(datos.recargoPago);
  const queda = recargoPago - c(datos.recargoDevueltoAntes);
  const monto = c(datos.monto);
  if (queda <= 0 || recargoPago <= 0 || montoPago <= 0 || monto <= 0) return 0;
  if (c(datos.devueltoAntes) + monto >= montoPago) return queda / 100;
  const proporcional = Math.floor((monto * recargoPago * 2 + montoPago) / (2 * montoPago));
  return Math.min(proporcional, queda) / 100;
}

/**
 * DEC-UX-13/14: los importes que el comprobante de cobro presenta al
 * cliente: cada trabajo con su parte del recargo y los totales con el
 * recargo incorporado, sin una línea aparte. El saldo no cambia. En un
 * comprobante anterior (sin recargos) son los importes de siempre.
 */
export function importesPresentados(contenido: ContenidoEntrega): {
  trabajos: Record<string, number>;
  subtotal: number | null;
  total: number | null;
  pagado: number | null;
  devuelto: number | null;
} {
  const n = (valor: string | null | undefined) => Number(valor ?? "0");
  const suma = (a: number, b: number) => Math.round((a + b) * 100) / 100;
  const incorporado = n(contenido.recargo_incorporado);
  return {
    trabajos: Object.fromEntries(
      contenido.trabajos_realizados.map((t) => [
        t.detalle_id,
        suma(n(t.precio), n(t.recargo)),
      ]),
    ),
    subtotal:
      contenido.subtotal == null ? null : suma(n(contenido.subtotal), incorporado),
    total: contenido.total == null ? null : suma(n(contenido.total), incorporado),
    pagado:
      contenido.pagado == null
        ? null
        : suma(n(contenido.pagado), n(contenido.recargo_cobrado)),
    devuelto:
      contenido.devuelto == null
        ? null
        : suma(n(contenido.devuelto), n(contenido.recargo_devuelto)),
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
