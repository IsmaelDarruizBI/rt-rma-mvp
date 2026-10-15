/**
 * Etiquetas de negocio: los valores técnicos que manda la API, dichos como
 * los diría un empleado. Solo presentación: ningún valor de la API cambia,
 * y los códigos siguen visibles en «Historial y datos técnicos».
 */

import type { Accion, Orden, RolUsuario } from "../../types/api";

export const ESTADO_WORKFLOW: Record<string, string> = {
  REQUERIMIENTO: "Ingresada",
  EN_REVISION: "En revisión técnica",
  HABILITADA: "Habilitada",
  EN_COLA: "En cola",
  EN_REPARACION: "En reparación",
  REPARACION_LISTA: "Reparación lista",
  ENTREGADA: "Entregada",
  CANCELADA: "Cancelada",
};

export const ORIGEN: Record<string, string> = {
  CLIENTE_EXTERNO: "Cliente externo",
  RT_INTERNO: "Equipo interno RT",
  RMA_GARANTIA_REPARACION: "Garantía RMA",
};

export const ROL: Record<RolUsuario, string> = {
  RECEPCION: "Recepción",
  TECNICO: "Técnico",
  COORDINADOR_RMA: "Coordinación RMA",
  ADMINISTRADOR: "Administración",
};

/** Estado de un trabajo (Detalle). */
export const ESTADO_TRABAJO: Record<string, string> = {
  DEFINIDO: "Pendiente",
  EN_PROGRESO: "En reparación",
  COMPLETO: "Realizado",
  CANCELADO: "Cancelado",
};

/** Bloqueo de un trabajo; SIN_BLOQUEO no se muestra. */
export const CONDICION_TRABAJO: Record<string, string> = {
  BLOQUEADO_POR_RECURSOS: "Sin repuestos",
  REQUIERE_DEFINICION: "Requiere revisión técnica",
};

export const CONTROL: Record<string, string> = {
  PENDIENTE: "Control pendiente",
  APROBADO: "Control aprobado",
  RECHAZADO: "Control rechazado",
};

export const AUTORIZACION: Record<string, string> = {
  NO_REQUERIDA: "No requiere autorización",
  PENDIENTE: "Esperando al cliente",
  AUTORIZADO: "Autorizado por el cliente",
  RECHAZADO: "Rechazado por el cliente",
  SIN_DECISION: "Sin decisión registrada",
};

export const CUSTODIA: Record<string, string> = {
  PENDIENTE_CONFIRMACION: "Recepción sin confirmar",
  SIN_REGISTRO: "Sin registro de recepción",
  EN_CUSTODIA: "En el local",
  ENTREGADO: "Entregado",
  DEVUELTO: "Devuelto",
  NO_RECIBIDO: "No recibido",
};

export const EJECUCION: Record<string, string> = {
  EN_PROGRESO: "en curso",
  COMPLETADO: "completada",
  INTERRUMPIDO: "interrumpida",
};

export const CANAL: Record<string, string> = {
  PRESENCIAL: "en persona",
  TELEFONO: "por teléfono",
  WHATSAPP: "por WhatsApp",
  EMAIL: "por email",
  OTRO: "por otro medio",
};

export const ESTADO_PAGO: Record<string, string> = {
  PENDIENTE: "Pendiente",
  PARCIAL: "Pago parcial",
  PAGADO: "Pagado",
  SALDO_A_FAVOR: "Saldo a favor del cliente",
};

/** Situación operativa (código de `situacion`), para filtrar. */
export const SITUACION: Record<string, string> = {
  PENDIENTE_RECEPCION: "Pendiente de recepción",
  PENDIENTE_DEFINICION: "Pendiente de definición",
  ESPERANDO_AUTORIZACION: "Esperando autorización",
  ESPERANDO_RECURSOS: "Esperando repuestos",
  PENDIENTE_PRIORIDAD: "Pendiente de prioridad",
  EN_COLA: "En cola",
  TOMADA: "Tomada por el técnico",
  EN_REPARACION: "En reparación",
  REQUIERE_REVISION_TECNICA: "Requiere revisión técnica",
  CONTROL_TECNICO: "Control de la reparación",
  PENDIENTE_NOTIFICACION: "Pendiente de aviso",
  PENDIENTE_COBRO: "Pendiente de cobro",
  LISTA_PARA_ENTREGAR: "Lista para entregar",
  CANCELADA_PENDIENTE_DEVOLUCION: "Cancelada, pendiente de devolución",
  CERRADA: "Cerrada",
  SIN_TAREAS: "Sin tareas pendientes",
};

/** Resultado del resolver de la Orden (aparece en mensajes del backend). */
export const SITUACION_RESOLVER: Record<string, string> = {
  SIN_DETALLES: "Sin trabajos",
  TODO_CANCELADO: "Todo cancelado",
  COMPLETA: "Trabajos terminados",
  EN_EJECUCION: "En reparación",
  ABIERTA_TRABAJABLE: "Con trabajos para hacer",
  REQUIERE_REVISION: "Requiere revisión técnica",
  PENDIENTE_AUTORIZACION: "Esperando autorización",
  PENDIENTE_RECURSOS: "Esperando repuestos",
};

/** Nombre de cada acción, con acentos y sin códigos de proceso. */
export const NOMBRE_ACCION: Record<string, string> = {
  AGREGAR_DETALLE: "Agregar un trabajo",
  FINALIZAR_DEFINICION: "Finalizar la definición",
  ENVIAR_A_REVISION: "Enviar a revisión técnica (sin diagnóstico)",
  REALIZAR_REVISION: "Realizar la revisión técnica",
  AGREGAR_DETALLE_DESDE_REVISION: "Agregar un trabajo según la revisión",
  FINALIZAR_SIN_REPARACION: "Finalizar sin reparación",
  ENCOLAR: "Priorizar e ingresar a la cola",
  TOMAR: "Tomar la Orden",
  INICIAR_DETALLE: "Iniciar el trabajo",
  COMPLETAR_EJECUCION: "Registrar la reparación realizada",
  INTERRUMPIR_EJECUCION: "Interrumpir la reparación",
  REQUIERE_REDEFINICION: "El trabajo requiere redefinición",
  REVISAR_DETALLE: "Revisar el trabajo",
  REDEFINIR_DETALLE: "Redefinir el trabajo",
  APROBAR_CONTROL: "Aprobar el control",
  RECHAZAR_CONTROL: "Rechazar el control (retrabajo)",
  LIBERAR_ORDEN: "Liberar la Orden",
  NOTIFICAR: "Avisar al cliente",
  REGISTRAR_PAGO: "Registrar un pago",
  ENTREGAR: "Entregar el equipo",
  INFORMAR_RT: "Informar el resultado a Gestión RT",
  DEVOLVER_RT: "Devolver el equipo a Gestión RT",
  INICIAR_GARANTIA_RMA: "Iniciar garantía RMA",
  ESPERAR_RECURSOS: "Dejar esperando repuestos",
  REVALIDAR_RECURSOS: "Revalidar la disponibilidad de repuestos",
  OVERRIDE_RECURSOS: "Forzar el trabajo sin stock",
  REGISTRAR_DEVOLUCION: "Registrar la devolución del equipo",
  CANCELAR_DETALLE: "Cancelar el trabajo",
  CANCELAR_ORDEN: "Cancelar la Orden",
  REGISTRAR_DECISION_CLIENTE: "Registrar la decisión del cliente",
  DESISTIR_DETALLE: "El cliente desiste de un trabajo",
  DESISTIR_TODO: "El cliente desiste de todo",
  ANULAR_PAGO: "Anular un pago",
  REGISTRAR_DEVOLUCION_DINERO: "Devolver dinero al cliente",
  REGISTRAR_DATOS_RECEPCION: "Corregir los datos del ingreso",
  CONFIRMAR_RECEPCION: "Confirmar la recepción física",
  REGISTRAR_EQUIPO_NO_RECIBIDO: "Registrar que el equipo no se recibió",
  AGREGAR_OBSERVACION_RECEPCION: "Agregar una observación",
  EMITIR_COMPROBANTE_RECEPCION: "Emitir otra versión del comprobante",
};

/** El valor legible, o el original si no hay etiqueta. */
export function etiqueta(mapa: Record<string, string>, valor: string): string {
  return mapa[valor] ?? valor;
}

/** Nombre del trabajo (Tipo de Reparación) de un Detalle de la Orden. */
export function nombreTrabajo(orden: Orden, detalleId: string | null): string {
  if (!detalleId) return "";
  const detalle = orden.reparaciones_detail.find((d) => d.id === detalleId);
  return detalle?.tipo_reparacion_nombre ?? detalleId;
}

/** «Iniciar el trabajo · Cambio de batería»: el nombre de la acción. */
export function nombreAccion(orden: Orden, accion: Accion): string {
  const nombre = NOMBRE_ACCION[accion.codigo] ?? accion.etiqueta;
  const trabajo = nombreTrabajo(orden, accion.detalle_id);
  return trabajo && accion.codigo !== "COMPLETAR_EJECUCION"
    ? `${nombre} · ${trabajo}`
    : nombre;
}

/** «Recepción o Coordinación RMA», a partir de los roles de una acción. */
export function nombreRoles(roles: RolUsuario[]): string {
  const nombres = roles.map((rol) => ROL[rol] ?? rol);
  if (nombres.length <= 1) return nombres.join("");
  return `${nombres.slice(0, -1).join(", ")} o ${nombres[nombres.length - 1]}`;
}

/** «hace 5 min», «hace 3 h», «hace 2 días». */
export function hace(iso: string, ahora: Date = new Date()): string {
  const minutos = Math.max(
    0,
    Math.round((ahora.getTime() - new Date(iso).getTime()) / 60000),
  );
  if (minutos < 1) return "recién";
  if (minutos < 60) return `hace ${minutos} min`;
  const horas = Math.round(minutos / 60);
  if (horas < 24) return `hace ${horas} h`;
  const dias = Math.round(horas / 24);
  return `hace ${dias} día${dias === 1 ? "" : "s"}`;
}

const TODAS_LAS_ETIQUETAS: Record<string, string> = {
  ...ESTADO_WORKFLOW,
  ...ORIGEN,
  ...SITUACION_RESOLVER,
  ...CUSTODIA,
  ...ROL,
};

/**
 * Un mensaje del backend sin códigos técnicos: cada «PROC-REP-120» se
 * reemplaza por el nombre del paso (si la Orden lo conoce) y se quitan
 * las referencias a reglas o escenarios entre paréntesis. Los IDs de
 * usuarios y estaciones conocidos (`nombres`) se dicen por su nombre. El
 * texto original se conserva aparte, como detalle técnico.
 */
export function mensajeLegible(
  texto: string,
  orden: Orden | null,
  nombres: Record<string, string> = {},
): string {
  const pasos = new Map(
    (orden?.progreso ?? []).map((paso) => [paso.process_id, paso.etiqueta]),
  );
  return texto
    .replace(
      /\s*\((?:BR|EXC|HP|VAR|ACC|FEAT)-REP-[\w/.-]+\)|\s*\(E\d+\)|\s*\(V1\.\d\)/g,
      "",
    )
    .replace(/PROC-REP-(\d+)(?:\/(\d+))?/g, (codigo) => {
      const etiquetaPaso = pasos.get(codigo);
      return etiquetaPaso ? `«${etiquetaPaso}»` : "un paso del proceso";
    })
    .replace(/\b[A-Z]+-\d{3}\b/g, (id) => nombres[id] ?? id)
    .replace(/\b[A-Z]+(?:_[A-Z]+)+\b|\b[A-Z]{6,}\b/g, (palabra) =>
      TODAS_LAS_ETIQUETAS[palabra]
        ? `«${TODAS_LAS_ETIQUETAS[palabra]}»`
        : palabra,
    )
    .replace(/\s{2,}/g, " ")
    .trim();
}
