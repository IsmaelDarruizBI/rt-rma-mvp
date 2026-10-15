/**
 * Tipos de la API del MVP.
 *
 * Espejan los DTOs de `app/backend/app/api/schemas.py`. Los importes y
 * cantidades viajan como string porque el backend usa Decimal: se
 * convierten a number solo para mostrarlos, nunca para operar.
 */

export type EstadoWorkflow =
  | "REQUERIMIENTO"
  | "EN_REVISION"
  | "HABILITADA"
  | "EN_COLA"
  | "EN_REPARACION"
  | "REPARACION_LISTA"
  | "ENTREGADA"
  /** Todos los Detalles cancelados, o cancelada sin Detalles. No es ENTREGADA. */
  | "CANCELADA";

export type OrigenOrden =
  | "CLIENTE_EXTERNO"
  | "RT_INTERNO"
  | "RMA_GARANTIA_REPARACION";

/** BR-REP-016: condición comercial derivada del Origen, no del Detalle. */
export type CondicionComercial =
  | "COBRABLE"
  | "NO_COBRABLE_AL_CLIENTE"
  | "NO_COBRABLE";

export type EstadoPago = "PENDIENTE" | "PARCIAL" | "PAGADO" | "SALDO_A_FAVOR";

/**
 * Momento comercial del cobro. Distinto del medio (`metodo`). `PAGO` es el
 * valor anterior a PARCIAL/FINAL: solo aparece en datos viejos.
 */
export type TipoPago = "ANTICIPO" | "PARCIAL" | "FINAL" | "PAGO";

/** Lectura de la cuenta de la Orden, derivada por el backend. */
export type SituacionFinanciera =
  | "NO_COBRABLE"
  | "SALDO_PENDIENTE"
  | "SALDO_A_FAVOR"
  | "SALDADA"
  | "SIN_MOVIMIENTOS";

/** Medio de pago o de devolución (catálogo configurable). */
export interface MedioPago {
  id: string;
  nombre: string;
  activo: boolean;
  admite_devolucion: boolean;
}

/** COMPLETO y CANCELADO son terminales. Un CANCELADO no se cobra ni se borra. */
export type EstadoDetalle = "DEFINIDO" | "EN_PROGRESO" | "COMPLETO" | "CANCELADO";

/**
 * Condición de bloqueo del Detalle, enviada por el backend. Es una
 * dimensión independiente del estado: la UI nunca la infiere del stock.
 * `REQUIERE_DEFINICION` se muestra pero su flujo no está implementado.
 */
export type CondicionDetalle =
  | "SIN_BLOQUEO"
  | "REQUIERE_DEFINICION"
  | "BLOQUEADO_POR_RECURSOS";

/** Control VIGENTE: tras un rechazo vuelve a PENDIENTE hasta el retrabajo. */
export type EstadoControl = "PENDIENTE" | "APROBADO";

/** Resultado de UN control registrado (aprobación o rechazo). */
export type ResultadoControl = "APROBADO" | "RECHAZADO";

/** Un control técnico tal como ocurrió (E14: nunca se reemplaza). */
export interface ControlTecnico {
  resultado: ResultadoControl;
  usuario_id: string;
  fecha: string;
  observaciones: string | null;
  ejecucion_id: string | null;
}

/** Quién canceló el Detalle, cuándo y por qué (PROC-REP-300/305). */
export interface Cancelacion {
  usuario_id: string;
  fecha: string;
  motivo: string;
  /**
   * INTERNA; RECHAZO_CLIENTE (rechazó la propuesta pendiente) o
   * DESISTIMIENTO_CLIENTE (la había autorizado y desistió después).
   */
  origen: OrigenCancelacion;
}

export type OrigenCancelacion =
  | "INTERNA"
  | "RECHAZO_CLIENTE"
  | "DESISTIMIENTO_CLIENTE";

/** Decisión que se REGISTRA: "sin respuesta" no es una decisión. */
export type ResultadoAutorizacion = "AUTORIZADO" | "RECHAZADO";

/** Canal provisorio del MVP (BR-REP-028 deja el canal pendiente). */
export type CanalComunicacion =
  | "PRESENCIAL"
  | "TELEFONO"
  | "WHATSAPP"
  | "EMAIL"
  | "OTRO";

/** Estado derivado por el backend para la definición vigente del Detalle. */
export type EstadoAutorizacion =
  | "NO_REQUERIDA"
  | "PENDIENTE"
  | "AUTORIZADO"
  | "RECHAZADO"
  | "SIN_DECISION";

/** Dónde está el Detalle respecto de la decisión del cliente (derivado). */
export type SituacionAutorizacion =
  | "NO_REQUERIDA"
  | "PENDIENTE_AUTORIZACION"
  | "AUTORIZADO_FACTIBLE"
  | "AUTORIZADO_SIN_STOCK"
  | "REQUIERE_REDEFINICION"
  | "EN_EJECUCION"
  | "COMPLETO"
  | "CANCELADO_POR_RECHAZO"
  | "CANCELADO_POR_DESISTIMIENTO"
  | "CANCELADO";

/** Una decisión del cliente registrada (PROC-REP-046). Nunca se reemplaza. */
export interface AutorizacionCliente {
  version_definicion: number;
  resultado: ResultadoAutorizacion;
  usuario_id: string;
  fecha: string;
  canal: CanalComunicacion;
  observaciones: string | null;
}

/**
 * Qué haría hoy el desistimiento total del cliente (lo calcula el backend):
 * pendientes que se rechazan, autorizados que se cancelan, lo COMPLETO que
 * se conserva y lo que lo impide (con eso no se aplica nada).
 */
export interface Desistimiento {
  rechazables: string[];
  desistibles: string[];
  conservados: string[];
  bloqueantes: { detalle_id: string; motivo: string }[];
}

/** Lo que Recepción envía por cada Detalle con respuesta del cliente. */
export interface DecisionDetalle {
  detalle_id: string;
  version_definicion: number;
  resultado: ResultadoAutorizacion;
}

/** Qué se le entrega a quien retira (lo decide el backend). */
export type TipoEntrega = "REPARACION_TERMINADA" | "DEVOLUCION_SIN_REPARACION";

/**
 * Salida física del equipo (PROC-REP-270): la entrega de la Orden o la
 * devolución sin reparar de una Orden CANCELADA.
 */
export interface Devolucion {
  tipo: TipoEntrega;
  entregado_por: string;
  recibido_por: string;
  identificacion_receptor: string | null;
  fecha: string;
  observaciones: string | null;
}

/**
 * Dónde está el equipo. Independiente del comprobante de recepción: emitir
 * un documento no prueba que el equipo esté en el local.
 */
export type EstadoCustodia =
  | "PENDIENTE_CONFIRMACION"
  | "SIN_REGISTRO"
  | "EN_CUSTODIA"
  | "ENTREGADO"
  | "DEVUELTO"
  | "NO_RECIBIDO";

export interface DatosRecepcion {
  estado_fisico: string | null;
  accesorios: string[];
  observaciones: string | null;
}

/** Datos del ingreso reemplazados por una corrección (antes de confirmar). */
export interface VersionRecepcion {
  equipo: Equipo;
  datos: DatosRecepcion;
  registrado_por: string;
  registrado_en: string;
  reemplazado_por: string;
  reemplazado_en: string;
}

export interface Recepcion {
  /** INGRESO al crear la Orden; REGULARIZACION en una Orden anterior. */
  registro: "INGRESO" | "REGULARIZACION";
  datos: DatosRecepcion;
  registrado_por: string;
  registrado_en: string;
  versiones_anteriores: VersionRecepcion[];
  confirmacion: {
    usuario_id: string;
    fecha: string;
    observaciones: string | null;
  } | null;
  /** Decisión explícita: el equipo nunca ingresó (nunca se deduce). */
  no_recibido: { usuario_id: string; fecha: string; motivo: string } | null;
  notas: { usuario_id: string; fecha: string; texto: string }[];
}

export interface Custodia {
  estado: EstadoCustodia;
  /** El Origen exige confirmar la recepción (RT_INTERNO no). */
  confirmacion_requerida: boolean;
  confirmada_por: string | null;
  confirmada_en: string | null;
  /** Otro hecho: no prueba la custodia. */
  comprobante_recepcion_emitido: boolean;
  salida: Devolucion | null;
}

export type TipoDocumento =
  | "COMPROBANTE_RECEPCION"
  | "COMPROBANTE_ENTREGA"
  | "GARANTIA";

/** Documento emitido, sin contenido (listado en la Orden). */
export interface DocumentoResumen {
  id: string;
  tipo: TipoDocumento;
  version: number;
  fecha_emision: string;
  usuario_id: string | null;
  motivo: string | null;
  reemplaza_a: string | null;
  /** Es la última versión emitida de su tipo. */
  vigente: boolean;
}

export interface UsuarioEnDocumento {
  id: string;
  nombre: string;
}

export interface EmpresaEnDocumento {
  nombre: string;
  razon_social: string | null;
  cuit: string | null;
  direccion: string | null;
  telefono: string | null;
  email: string | null;
  condiciones_garantia: string | null;
}

export interface TrabajoEnDocumento {
  detalle_id: string;
  tipo_reparacion_id: string;
  nombre: string;
  /** `null` si la Orden no se cobra: no se muestran cobros inexistentes. */
  precio: string | null;
  detalle_origen_id: string | null;
}

interface ContenidoBase {
  empresa: EmpresaEnDocumento;
  orden_id: string;
  origen: OrigenOrden;
  fecha_ingreso: string;
  cliente: Cliente | null;
  referencia_rt: string | null;
  equipo: Equipo;
  orden_origen_id: string | null;
  detalles_reclamados: TrabajoEnDocumento[];
}

export interface ContenidoRecepcion extends ContenidoBase {
  tipo: "COMPROBANTE_RECEPCION";
  estado_fisico: string | null;
  accesorios: string[];
  observaciones: string | null;
  notas: string[];
  registrado_por: UsuarioEnDocumento | null;
  registrado_en: string | null;
  recepcion_fisica: EstadoCustodia;
  confirmada_por: UsuarioEnDocumento | null;
  confirmada_en: string | null;
  leyenda: string;
}

export interface ContenidoEntrega extends ContenidoBase {
  tipo: "COMPROBANTE_ENTREGA";
  estado_final: EstadoWorkflow;
  tipo_entrega: TipoEntrega;
  resultado: string;
  fecha_entrega: string | null;
  entregado_por: UsuarioEnDocumento | null;
  recibido_por: string | null;
  identificacion_receptor: string | null;
  observaciones_entrega: string | null;
  trabajos_realizados: TrabajoEnDocumento[];
  trabajos_cancelados: (TrabajoEnDocumento & {
    motivo: string | null;
    origen_cancelacion: string | null;
  })[];
  cobrable: boolean;
  total: string | null;
  pagado: string | null;
  devuelto: string | null;
  saldo: string | null;
  pagos: {
    id: string;
    fecha: string;
    tipo_pago: TipoPago;
    medio: string;
    monto: string;
    referencia: string | null;
  }[];
  devoluciones_dinero: {
    id: string;
    pago_id: string;
    fecha: string;
    medio: string;
    monto: string;
    motivo: string;
  }[];
}

export interface ContenidoGarantia extends ContenidoBase {
  tipo: "GARANTIA";
  /** Entrega efectiva; `null` en una vista previa anterior a la entrega. */
  fecha_inicio: string | null;
  coberturas: {
    detalle_id: string;
    tipo_reparacion_id: string;
    nombre: string;
    garantia_dias: number;
    /** Último día de garantía; `null` sin plazo o sin entrega todavía. */
    vence: string | null;
    detalle_origen_id: string | null;
    observaciones: string | null;
  }[];
  condiciones: string | null;
  observaciones_entrega: string | null;
}

export type ContenidoDocumento =
  | ContenidoRecepcion
  | ContenidoEntrega
  | ContenidoGarantia;

/** Documento emitido con su contenido, tal como se entregó. */
export interface DocumentoEmitido extends DocumentoResumen {
  orden_id: string;
  contenido: ContenidoDocumento;
}

/** `GET .../documents`. */
export interface DocumentosDeOrden {
  orden_id: string;
  cerrada: boolean;
  emitidos: DocumentoEmitido[];
  marcas: Documentos;
  previsualizables: TipoDocumento[];
}

/** `GET .../documents/preview/{tipo}`: NO está emitido. */
export interface VistaPreviaDocumento {
  orden_id: string;
  tipo: TipoDocumento;
  vista_previa: true;
  contenido: ContenidoDocumento;
}

/** INTERRUMPIDO y COMPLETADO son los resultados terminales de PROC-REP-200. */
export type EstadoEjecucion = "EN_PROGRESO" | "COMPLETADO" | "INTERRUMPIDO";

export type EstadoToma = "ACTIVA" | "CERRADA";

export type RolUsuario =
  | "ADMINISTRADOR"
  | "RECEPCION"
  | "COORDINADOR_RMA"
  | "TECNICO";

export interface Usuario {
  id: string;
  nombre: string;
  rol: RolUsuario;
  activo: boolean;
}

export interface TipoReparacion {
  id: string;
  nombre: string;
  precio: string;
  puntaje: number;
  garantia_dias: number;
  activo: boolean;
}

export interface Estacion {
  id: string;
  nombre: string;
  activa: boolean;
}

export interface Cliente {
  id: string;
  nombre: string;
  telefono: string;
  email: string | null;
}

export interface Equipo {
  id: string;
  marca: string;
  modelo: string;
  falla_reportada: string;
  imei: string | null;
  numero_serie: string | null;
}

/** Insumo que el Tipo de Reparación del Detalle prevé consumir. */
export interface InsumoPrevisto {
  insumo_id: string;
  codigo: string;
  nombre: string;
  cantidad_prevista: string;
}

export interface Detalle {
  id: string;
  tipo_reparacion_id: string;
  /** Nombre del catálogo, resuelto por la API. No se persiste. */
  tipo_reparacion_nombre: string;
  precio: string;
  puntaje: number;
  garantia_dias: number;
  estado: EstadoDetalle;
  condicion: CondicionDetalle;
  control_estado: EstadoControl;
  control_usuario_id: string | null;
  control_fecha: string | null;
  control_observaciones: string | null;
  observaciones: string | null;
  /** Detalle de la Orden origen que motiva esta garantía (HP-REP-003). */
  detalle_origen_id: string | null;
  /** Definiciones reemplazadas por PROC-REP-127 (EXC-REP-004). */
  definiciones_anteriores: DefinicionAnterior[];
  /** Todos los controles registrados, del más antiguo al más reciente. */
  controles: ControlTecnico[];
  /** Reabierto por un control rechazado y todavía sin rehacer. */
  pendiente_de_retrabajo: boolean;
  /** Solo en un Detalle CANCELADO. */
  cancelacion: Cancelacion | null;
  /** Resuelto por la API contra el catálogo; no vive en el dominio. */
  insumos_previstos: InsumoPrevisto[];
  /** Definición vigente: 1 + las reemplazadas por PROC-REP-127. */
  version_definicion: number;
  /** Todas las decisiones del cliente, de cualquier versión. */
  autorizaciones: AutorizacionCliente[];
  estado_autorizacion: EstadoAutorizacion;
  situacion_autorizacion: SituacionAutorizacion;
}

/** Definición de un Detalle reemplazada por PROC-REP-127 (BR-REP-015). */
export interface DefinicionAnterior {
  tipo_reparacion_id: string;
  precio: string;
  puntaje: number;
  garantia_dias: number;
  reemplazada_en: string;
  usuario_id: string;
}

export interface Toma {
  id: string;
  usuario_id: string;
  estacion_id: string;
  estado: EstadoToma;
  inicio: string;
  fin: string | null;
}

export interface InsumoUtilizado {
  insumo_id: string;
  cantidad: string;
}

export interface Ejecucion {
  id: string;
  reparacion_detail_id: string;
  toma_orden_id: string;
  usuario_id: string;
  estado: EstadoEjecucion;
  inicio: string;
  fin: string | null;
  insumos_utilizados: InsumoUtilizado[];
  observaciones: string | null;
  /** PROC-REP-200 "Requiere redefinicion" (EXC-REP-004). */
  motivo_redefinicion: string | null;
}

/**
 * Pago registrado. `monto` es siempre el original: uno anulado trae
 * `anulacion` y deja de contar como pagado. `devolvible` es lo que todavía
 * puede devolverse desde este Pago.
 */
export interface Pago {
  id: string;
  monto: string;
  tipo_pago: TipoPago;
  metodo: string;
  usuario_id: string;
  fecha: string;
  referencia: string | null;
  vigente: boolean;
  anulacion: { usuario_id: string; fecha: string; motivo: string } | null;
  devuelto: string;
  devolvible: string;
}

/** Dinero devuelto al cliente desde un Pago (no es un pago negativo). */
export interface DevolucionDinero {
  id: string;
  pago_id: string;
  monto: string;
  medio: string;
  usuario_id: string;
  fecha: string;
  motivo: string;
  referencia: string | null;
}

export interface Documento {
  generado: boolean;
  fecha_generacion: string | null;
}

export interface Documentos {
  comprobante_recepcion: Documento;
  comprobante_final: Documento;
  garantia_reparacion: Documento;
}

export interface ResumenComercial {
  total: string;
  pagado: string;
  saldo: string;
  estado_pago: EstadoPago;
  puntaje_total: number;
  /** COBRABLE (cliente) / NO_COBRABLE_AL_CLIENTE (RT) / NO_COBRABLE. */
  condicion_comercial: CondicionComercial;
  /** Saldo = Total - Pagado (válido) + Devuelto. */
  devuelto: string;
  credito_a_favor: string;
  situacion_financiera: SituacionFinanciera;
}

/**
 * Qué clase de referencia guarda una entrada del historial.
 *
 * PROCESS_NODE      → paso del recorrido del Business Process.
 * FUNCTIONAL_ACTION → capacidad transversal (ACC-REP-*), que no mueve
 *                     `current_process`.
 */
export type TipoReferencia = "PROCESS_NODE" | "FUNCTIONAL_ACTION";

export interface PasoHistorial {
  tipo_referencia: TipoReferencia;
  referencia_id: string;
  accion: string;
  fecha: string;
  usuario_id: string | null;
  reparacion_detail_id: string | null;
  ejecucion_id: string | null;
  pago_id: string | null;
  observacion: string | null;
  /** Compatibilidad: `null` cuando la entrada es transversal. */
  process_id: string | null;
}

export interface PasoProgreso {
  process_id: string;
  etiqueta: string;
  alcanzado: boolean;
}

/** Accion humana que la Orden admite ahora, segun el backend. */
export interface Accion {
  codigo: string;
  etiqueta: string;
  /** Todos los actores autorizados. Vacío = el negocio no definió rol. */
  roles: RolUsuario[];
  detalle_id: string | null;
  ejecucion_id: string | null;
  /**
   * `false` marca un nodo `actor: ACT-SYSTEM` (p. ej. Informar a Gestión
   * RT): no hay actor humano que autorizar y el comando no recibe
   * `usuario_id`. `true` (default) es el caso humano normal.
   */
  requiere_actor: boolean;
  /**
   * E2: si viene, es la ÚNICA persona que puede ejecutarla (el titular de
   * la toma activa en las acciones técnicas). `null` = cualquiera con el rol.
   */
  usuario_id: string | null;
  /** Movimientos financieros: el Pago sobre el que actúa (anularlo). */
  pago_id: string | null;
  /** La acción corresponde pero hoy no puede ejecutarse (y por qué). */
  bloqueo: string | null;
}

/** Un insumo previsto ante el override (E3): lo que se confirma. */
export interface ImpactoStockInsumo {
  insumo_id: string;
  codigo: string;
  nombre: string;
  stock_fisico: string;
  reservado_otras_ordenes: string;
  reservado_esta_orden: string;
  disponible: string;
  requerido: string;
  disponible_resultante: string;
}

/** `GET .../resources/override-preview`: impacto de forzar un Detalle. */
export interface ImpactoOverride {
  orden_id: string;
  detalle_id: string;
  insumos: ImpactoStockInsumo[];
  deja_disponible_negativo: boolean;
  hay_reservas_de_otras_ordenes: boolean;
  advertencia: string;
}

/**
 * Detalle de la Orden origen de una garantía RMA (HP-REP-003). El nombre
 * del Tipo lo resuelve la API leyendo la Orden origen; no se persiste.
 */
export interface DetalleOrigen {
  id: string;
  tipo_reparacion_nombre: string;
}

export interface OrdenResumen {
  id: string;
  origen: OrigenOrden;
  /** Orden ENTREGADA de la que nace una garantía RMA; `null` si no aplica. */
  orden_origen_id: string | null;
  estado_workflow: EstadoWorkflow;
  current_process: string;
  prioridad: number;
  /** Nombre del Cliente, o identificación RT cuando no hay Cliente. */
  cliente_nombre: string;
  equipo: string;
  total: string;
  saldo: string;
  estado_pago: EstadoPago;
  created_at: string;
  updated_at: string;
}

export interface Orden {
  id: string;
  origen: OrigenOrden;
  estado_workflow: EstadoWorkflow;
  current_process: string;
  prioridad: number;
  /** `null` en RT_INTERNO: el equipo es de Rosario Tecno, no hay Cliente. */
  cliente: Cliente | null;
  equipo: Equipo;
  /** Contexto de Gestion RT (PROC-REP-020). `null` salvo en RT_INTERNO. */
  referencia_rt: string | null;
  /** Orden origen de una garantía RMA (HP-REP-003). `null` en los demás Origenes. */
  orden_origen_id: string | null;
  /** Detalles de la Orden origen identificados en PROC-REP-035 (garantía RMA). */
  detalles_origen_ids: string[];
  /** Los mismos Detalles origen, con el nombre de su Tipo (presentación). */
  detalles_origen: DetalleOrigen[];
  /**
   * PROC-REP-069: la revisión concluyó SIN_REPARACION. Lo deriva el backend
   * del historial; no es un estado de workflow.
   */
  finalizada_sin_reparacion: boolean;
  /**
   * E1: la Orden terminó su proceso (entregada o devuelta a Gestión RT) y
   * solo puede consultarse. Lo deriva el backend.
   */
  cerrada: boolean;
  reparaciones_detail: Detalle[];
  tomas: Toma[];
  /** E2: toma vigente (técnico, estación, inicio), o `null`. */
  toma_activa: Toma | null;
  ejecuciones: Ejecucion[];
  pagos: Pago[];
  /** Devoluciones de dinero al cliente (BR-REP-038). */
  devoluciones_dinero: DevolucionDinero[];
  documentos: Documentos;
  resumen: ResumenComercial;
  historial: PasoHistorial[];
  progreso: PasoProgreso[];
  acciones_disponibles: Accion[];
  /** Cancelaciones posibles ahora (Detalle u Orden), aparte del flujo. */
  acciones_cancelacion: Accion[];
  /** El Origen exige la decisión del cliente por Detalle (BR-REP-028). */
  autorizacion_requerida: boolean;
  /** Decisiones comerciales del cliente posibles ahora (decidir, desistir). */
  acciones_autorizacion: Accion[];
  /** Vista previa del desistimiento total (Cliente Externo con Detalles). */
  desistimiento: Desistimiento | null;
  /** Cobrar, anular un Pago o devolver dinero, si corresponde ahora. */
  acciones_financieras: Accion[];
  /** Orden CANCELADA: devolución física registrada, o `null`. */
  devolucion: Devolucion | null;
  /** Orden CANCELADA con el equipo todavía en custodia. */
  devolucion_pendiente: boolean;
  /** Datos del ingreso físico; `null` en una Orden anterior a este registro. */
  recepcion: Recepcion | null;
  custodia: Custodia;
  /** Orden ENTREGADA: quién retiró el equipo. */
  entrega: Devolucion | null;
  documentos_emitidos: DocumentoResumen[];
  /** Registrar/corregir el ingreso, confirmar (o "no recibido"), observar, re-emitir. */
  acciones_custodia: Accion[];
  /** Orden CANCELADA abierta: qué falta para cerrarla. */
  pendientes_de_cierre: string[];
  /** Situación operativa para la pantalla (solo lectura). */
  situacion: Situacion | null;
  created_at: string;
  updated_at: string;
  /** Solo lo devuelven notificar y registrar pago (PROC-REP-265). */
  puede_entregar?: boolean;
}

// --- Situación operativa (solo lectura) --------------------------------------

/** Algo que hay que hacer ahora; sus acciones son las que la Orden publica. */
export interface TareaSituacion {
  titulo: string;
  motivo: string;
  responsable: string;
  acciones: Accion[];
}

/** Un bloqueo secundario que la situación principal no oculta. */
export interface AvisoSituacion {
  codigo: string;
  titulo: string;
  responsable: string | null;
  acciones: Accion[];
}

export type EstadoEtapa = "COMPLETA" | "EN_CURSO" | "PENDIENTE" | "NO_APLICA";

/** Una de las seis etapas del negocio (no es un paso lineal). */
export interface EtapaSituacion {
  codigo: string;
  titulo: string;
  estado: EstadoEtapa;
  detalle: string | null;
}

/** Qué pasa con la Orden, a quién le toca y qué sigue. */
export interface Situacion {
  codigo: string;
  titulo: string;
  descripcion: string;
  responsable: string | null;
  /** Desde cuándo, solo si el historial lo registra. */
  desde: string | null;
  tareas: TareaSituacion[];
  avisos: AvisoSituacion[];
  etapas: EtapaSituacion[];
}

export interface Catalogos {
  tipos: TipoReparacion[];
  estaciones: Estacion[];
  usuarios: Usuario[];
}

// --- Inventario operativo ---------------------------------------------------

export type TipoMovimientoInsumo =
  | "RESERVA"
  | "CONSUMO"
  | "LIBERACION_RESERVA"
  | "DEVOLUCION"
  | "INGRESO"
  | "AJUSTE_POSITIVO"
  | "AJUSTE_NEGATIVO";

/** Un insumo con sus tres cantidades: disponible = físico − reservado. */
export interface SituacionInsumo {
  id: string;
  codigo: string;
  nombre: string;
  unidad: string | null;
  activo: boolean;
  stock_fisico: string;
  reservado: string;
  disponible: string;
  /** Disponible o físico negativos. */
  faltante: boolean;
  disponible_negativo: boolean;
  fisico_negativo: boolean;
  ordenes_con_reserva: number;
  detalles_con_reserva: number;
}

export interface ReservaVigente {
  orden_id: string;
  detalle_id: string;
  movimiento_id: string;
  ejecucion_id: string | null;
  cantidad: string;
  fecha: string;
}

/**
 * Un movimiento tal como se registró. ORDEN: trazado a un Detalle;
 * INVENTARIO: ingreso o ajuste manual (con stock antes y después).
 */
export interface MovimientoInventario {
  id: string;
  origen: "ORDEN" | "INVENTARIO";
  tipo: TipoMovimientoInsumo;
  insumo_id: string;
  cantidad: string;
  fecha: string;
  usuario_id: string | null;
  orden_id: string | null;
  detalle_id: string | null;
  ejecucion_id: string | null;
  movimiento_origen_id: string | null;
  observacion: string | null;
  referencia: string | null;
  stock_anterior: string | null;
  stock_resultante: string | null;
  disponible_resultante: string | null;
}

export interface EvidenciaFaltante {
  fecha: string;
  origen: string;
  descripcion: string;
  orden_id: string | null;
  movimiento_id: string | null;
}

export interface DetalleInsumo {
  insumo: SituacionInsumo;
  reservas: ReservaVigente[];
  movimientos: MovimientoInventario[];
  faltantes: EvidenciaFaltante[];
}

export interface ResultadoMovimientoStock {
  movimiento: MovimientoInventario;
  insumo: SituacionInsumo;
}

export interface RevalidacionOrden {
  orden_id: string;
  resultado:
    | "TRABAJABLE"
    | "SIGUE_ESPERANDO"
    | "OTRA_INTERVENCION"
    | "SIN_CAMBIOS"
    | "ERROR";
  detalle: string;
  current_process: string | null;
  estado_workflow: string | null;
  detalles_revalidados: string[];
}

export interface ResultadoRevalidacion {
  usuario_id: string;
  fecha: string;
  evaluadas: number;
  trabajables: number;
  siguen_esperando: number;
  otra_intervencion: number;
  sin_cambios: number;
  errores: number;
  ordenes: RevalidacionOrden[];
}
