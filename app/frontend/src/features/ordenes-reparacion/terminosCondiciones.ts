/**
 * Términos y Condiciones del servicio técnico de Rosario Tecno.
 *
 * Transcripción textual de la hoja que firma el cliente al retirar el
 * equipo: los 19 apartados en su orden, sin resumir ni reescribir. Cada
 * apartado es una lista de líneas: la primera abre el apartado y las
 * siguientes son los renglones que la hoja muestra aparte.
 *
 * Solo datos: la página que los imprime vive en `DocumentosOrden.tsx`.
 */

import type { TipoEntrega } from "../../types/api";

export interface ApartadoTerminos {
  lineas: string[];
  /** Se imprime resaltado (fondo amarillo, borde y negrita). */
  destacado?: boolean;
}

export const ENCABEZADO_TERMINOS = {
  marca: "ROSARIO | TECNO",
  titulo: "TÉRMINOS Y CONDICIONES",
  subtitulo: "SERVICIO TÉCNICO",
} as const;

/** Espacios en blanco del pie: el cliente los completa a mano. */
export const PIE_TERMINOS = ["FIRMA DEL CLIENTE", "ACLARACIÓN", "FECHA"] as const;

export const APARTADOS_TERMINOS: ApartadoTerminos[] = [
  {
    lineas: [
      "La reparación cuenta con una garantía de seis meses (180 días de corrido), válida exclusivamente sobre el trabajo realizado y/o el repuesto colocado, contados a partir de la fecha de entrega del equipo.",
    ],
  },
  {
    lineas: [
      "La garantía NO cubre, sin excepción, daños ocasionados por golpes, caídas, presión, humedad, ingreso de líquidos, sulfatación, corrosión, polvo, calor, frío, sobrecargas eléctricas, uso indebido, uso de cargadores no originales o defectuosos, cables en mal estado, tomas eléctricas inestables, ni cualquier tipo de manipulación, apertura o reparación realizada por terceros ajenos a este servicio técnico.",
    ],
  },
  {
    lineas: [
      "En casos de cambios de tapa y cambios de vidrio de cámara la garantía cubre el repuesto si viene despegado sin ningún tipo de daño o fractura, el repuesto debe estar entero y en óptimas condiciones.",
    ],
  },
  {
    lineas: [
      "Asimismo, no se encuentran cubiertos por la garantía los fallos derivados de:",
      "Uso incorrecto del cargador.",
      "Ciclos de carga interrumpidos.",
      "Ciclos de carga excesivos (múltiples cargas diarias).",
      "Consumos elevados y continuos de aplicaciones o procesos en segundo plano.",
      "Configuraciones del sistema o del usuario que afecten el rendimiento, autonomía o condición de la batería.",
    ],
  },
  {
    lineas: [
      "Asimismo el Servicio Técnico no realiza reacondicionamientos del equipo bajo ningún concepto.",
    ],
  },
  {
    lineas: [
      "Los equipos que ingresen apagados, bloqueados, sin clave, sin acceso al sistema operativo o sin posibilidad de realizar pruebas funcionales completas, no cuentan con garantía, dado que resulta imposible verificar su correcto funcionamiento al momento del ingreso.",
    ],
  },
  {
    lineas: [
      "El servicio técnico no se responsabiliza, en ningún caso, por la pérdida total o parcial de información, incluyendo —pero no limitado a— datos personales, fotografías, contactos, aplicaciones, configuraciones o contenido multimedia.",
      "Es responsabilidad exclusiva del cliente realizar una copia de seguridad (backup) previa al ingreso del equipo.",
    ],
  },
  {
    lineas: [
      "En equipos con daño por líquido, humedad o sulfatación, el cliente acepta expresamente que la reparación puede ser parcial, limitada o temporal, y que pueden manifestarse fallas futuras sin que ello genere derecho a reclamo, repetición o indemnización alguna.",
    ],
  },
  {
    lineas: [
      "No se garantiza el correcto funcionamiento de Face ID, Touch ID, True Tone, sensores, cámaras u otras funciones, cuando:",
      "No funcionaban correctamente antes del ingreso del equipo.",
      "El equipo sufrió un golpe/caída severa.",
      "La reparación afecte su funcionamiento por limitaciones técnicas, de diseño del fabricante o por el estado general del dispositivo.",
    ],
  },
  {
    lineas: [
      "No se garantiza el correcto funcionamiento de equipos que hayan sido previamente reparados, manipulados o intervenidos por terceros, aun cuando dichas fallas no sean visibles o detectables al momento del ingreso.",
    ],
  },
  {
    lineas: [
      "En el caso de cambio de batería, el cliente declara haber sido debidamente informado sobre la necesidad de:",
      "Realizar copia de seguridad.",
      "Contar con el correo electrónico y contraseña de la cuenta iCloud.",
      "El servicio técnico no realiza intentos de inicio de sesión, desbloqueo ni recuperación de cuentas, ya que el ingreso incorrecto de credenciales puede provocar el bloqueo definitivo del equipo, siendo esta responsabilidad exclusiva del cliente.",
    ],
  },
  {
    lineas: [
      "Los diagnósticos son estimativos y podrán ser actualizados o modificados si, con posterioridad al primer diagnóstico, se detectan fallas adicionales que impidan la reparación total o alteren el alcance inicialmente informado. Dichas situaciones serán notificadas al cliente para su evaluación y aceptación.",
    ],
  },
  {
    lineas: [
      "Una vez confirmada la reparación por parte del cliente, no podrá ser revertida bajo ningún concepto, y el abono del servicio será obligatorio, independientemente del resultado final, siempre que el trabajo haya sido realizado conforme al diagnóstico aceptado.",
    ],
  },
  {
    lineas: [
      "El equipo será entregado únicamente contra el pago total de la reparación, la presentación del comprobante correspondiente y el retiro por parte de la misma persona que dejó el equipo en el servicio técnico.",
    ],
  },
  {
    lineas: [
      "La garantía quedará automáticamente anulada si el equipo es retirado por un comisionista, tercero, mensajero o cualquier persona distinta del titular que realizó el ingreso, aun cuando exista autorización verbal o escrita.",
    ],
    destacado: true,
  },
  {
    lineas: [
      "El cliente declara haber sido previamente informado y aceptar los medios de pago habilitados por el servicio técnico, no admitiéndose ningún otro medio distinto a los informados, publicados o comunicados con anterioridad.",
    ],
  },
  {
    lineas: [
      "Los plazos de reparación son estimativos y pueden variar sin que ello genere derecho a reclamo alguno.",
    ],
    destacado: true,
  },
  {
    lineas: [
      "Transcurridos quince (15) días corridos desde la notificación de reparación finalizada sin que el equipo sea retirado, el valor del servicio podrá ser actualizado. Transcurridos noventa (90) días corridos, el equipo será considerado abandonado.",
      "Previo a su desarme o disposición final, el cliente será notificado por última vez. De no obtener respuesta, se procederá conforme a lo dispuesto en los artículos 870 y 873 del Código Civil y Comercial de la Nación, sin derecho a reclamo posterior.",
    ],
  },
  {
    lineas: [
      "El cliente declara haber leído, comprendido y aceptado en su totalidad los presentes Términos y Condiciones, así como el presupuesto informado y los riesgos inherentes a la reparación del dispositivo.",
    ],
  },
];

/**
 * Solo la entrega de un equipo reparado lleva los Términos y Condiciones;
 * una devolución sin reparación (Orden SIN_REPARACION o CANCELADA), no.
 * El tipo lo deriva el backend del resultado de la Orden.
 */
export function llevaTerminos(contenido: { tipo_entrega: TipoEntrega }): boolean {
  return contenido.tipo_entrega === "REPARACION_TERMINADA";
}
