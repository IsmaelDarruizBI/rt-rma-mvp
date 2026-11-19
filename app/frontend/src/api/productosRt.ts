/**
 * Reparación RT (etapa 1): Productos de Gestión RT en reparación.
 *
 * Los GET leen la copia del backend (nunca Gestión RT); sincronizar la
 * actualiza desde el origen configurado (solo Administración, DEC-RT-05).
 * Nada escribe en Gestión RT. Toda relación con una Orden llega como
 * `coincidencias_sugeridas`: una sugerencia, nunca un vínculo (DEC-RT-03).
 */

import { get, post } from "./client";

export type ResultadoSincronizacion =
  | "EXITOSA"
  | "FALLIDA"
  | "RECHAZADA"
  | "INTERRUMPIDA";

export interface SincronizacionProductosRt {
  id: string;
  usuario_id: string;
  origen: string;
  filtro: string;
  iniciada_en: string;
  finalizada_en: string;
  resultado: ResultadoSincronizacion;
  mensaje: string | null;
  contadores: Record<string, number>;
  avisos: string[];
}

export interface EstadoCopiaRt {
  habilitado: boolean;
  sincronizable: boolean;
  origen: string | null;
  filtro: string;
  /** Fecha de los datos: la última sincronización exitosa. */
  datos_del: string | null;
  ultima: SincronizacionProductosRt | null;
  ultima_exitosa: SincronizacionProductosRt | null;
  desactualizada: boolean;
  antiguedad_aviso_horas: number;
}

export type CriterioCoincidencia = "REFERENCIA_RT" | "IMEI";

/** Una Orden que COINCIDE con el producto: solo una sugerencia. */
export interface CoincidenciaSugerida {
  orden_id: string;
  criterios: CriterioCoincidencia[];
  origen: string;
  estado_workflow: string;
  cerrada: boolean;
  creada_en: string;
}

export type AvisoProductoRt =
  | "SIN_IMEI"
  | "IMEI_INVALIDO"
  | "IMEI_VERIFICADOR_INCORRECTO"
  | "IMEI_REPETIDO"
  | "TIPO_NO_ENCONTRADO"
  | "TIPO_ELIMINADO"
  | "SIN_SEDE"
  | "SEDE_NO_CONFIRMADA"
  | "CONFLICTO_ORIGEN"
  | "CAMBIO_IDENTIDAD"
  | "FUERA_DE_REPARACION"
  | "ELIMINADO_EN_ORIGEN"
  | "AUSENTE_DEL_ORIGEN";

export interface ProductoRtResumen {
  producto_id: string;
  imei: string | null;
  imei_valido: boolean;
  imei_repetido: boolean;
  modelo: string | null;
  capacidad: string | null;
  color: string | null;
  descripcion_tipo: string | null;
  sede: string | null;
  estado_gestion_rt: string;
  en_reparacion: boolean;
  en_reparacion_desde: string | null;
  salio_de_reparacion_en: string | null;
  eliminado_en_origen: boolean;
  presente_en_origen: boolean;
  avisos: AvisoProductoRt[];
  coincidencias_sugeridas: CoincidenciaSugerida[];
}

export interface ProductoRt extends ProductoRtResumen {
  imei_normalizado: string | null;
  imei_luhn_valido: boolean | null;
  tipo_producto_id: string | null;
  tipo_producto_encontrado: boolean;
  tipo_producto_eliminado: boolean;
  categoria: string | null;
  subcategoria: string | null;
  bateria: string | null;
  detalle_estetico: string | null;
  defecto: string | null;
  toma_rt: string | null;
  tipo_reparacion_origen: string | null;
  repuesto: string | null;
  creado_en_origen: string | null;
  conflicto_origen: boolean;
  cambio_identidad: boolean;
  identidad_anterior: Record<string, string | null> | null;
  primera_vez_visto_en: string;
  sincronizado_en: string;
}

export interface SedeRt {
  sede: string | null;
  cantidad: number;
  confirmada: boolean;
}

export interface ListadoProductosRt {
  copia: EstadoCopiaRt;
  sedes: SedeRt[];
  total: number;
  pagina: number;
  tamano: number;
  productos: ProductoRtResumen[];
}

export interface FichaProductoRt {
  copia: EstadoCopiaRt;
  producto: ProductoRt;
}

const RUTA = "/api/rt-products";

/** `parametros`: los de `filtros.parametrosApi` (búsqueda, sedes...). */
export function listarProductosRt(
  parametros: URLSearchParams,
): Promise<ListadoProductosRt> {
  const consulta = parametros.toString();
  return get<ListadoProductosRt>(consulta ? `${RUTA}?${consulta}` : RUTA);
}

export function obtenerProductoRt(productoId: string): Promise<FichaProductoRt> {
  return get<FichaProductoRt>(`${RUTA}/${encodeURIComponent(productoId)}`);
}

export function sincronizarProductosRt(
  usuarioId: string,
): Promise<SincronizacionProductosRt> {
  const consulta = new URLSearchParams({ usuario_id: usuarioId });
  return post<SincronizacionProductosRt>(`${RUTA}/sync?${consulta}`, {});
}

export function sincronizacionesProductosRt(): Promise<
  SincronizacionProductosRt[]
> {
  return get<SincronizacionProductosRt[]>(`${RUTA}/syncs`);
}
