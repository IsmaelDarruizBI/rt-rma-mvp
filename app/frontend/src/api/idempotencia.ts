/**
 * Claves de idempotencia de los envíos (E6, B3).
 *
 * Las operaciones que crean registros en cada llamada (diseño E6, §6.1)
 * viajan con el encabezado `Idempotency-Key`. La clave identifica UNA
 * operación del usuario:
 *
 * - reintentar la misma operación (misma ruta y mismo cuerpo, o el mismo
 *   archivo) reutiliza la clave mientras su resultado sea incierto: sin
 *   conexión, error del servidor o `PERSISTENCIA_RESULTADO_INCIERTO`. El
 *   servidor devuelve lo ya confirmado o la ejecuta una sola vez;
 * - con una respuesta definitiva (éxito o rechazo funcional) la clave se
 *   descarta: hacer después la misma operación a propósito (por ejemplo,
 *   un segundo pago igual) es otra operación, con otra clave;
 * - otra ruta u otro cuerpo es otra operación: otra clave.
 *
 * Sin dependencias de React ni del navegador: se prueba con node --test.
 */

/** Operaciones del primer grupo de E6 (POST que crean registros). */
const RUTAS_CON_CLAVE: readonly RegExp[] = [
  /^\/api\/orders$/,
  /^\/api\/orders\/rt-interno$/,
  /^\/api\/orders\/[^/]+\/warranty-rma$/,
  /^\/api\/orders\/[^/]+\/details$/,
  /^\/api\/orders\/[^/]+\/review\/details$/,
  /^\/api\/orders\/[^/]+\/reception\/notes$/,
  /^\/api\/orders\/[^/]+\/notify$/,
  /^\/api\/orders\/[^/]+\/payments$/,
  /^\/api\/orders\/[^/]+\/refunds$/,
  /^\/api\/orders\/[^/]+\/photos$/,
  /^\/api\/inventory\/[^/]+\/(receipts|adjustments)$/,
  /^\/api\/catalogs\/equipment\/sync$/,
];

/** Si un POST a `ruta` (con o sin consulta) lleva clave. */
export function llevaClave(ruta: string): boolean {
  const camino = ruta.split("?")[0];
  return RUTAS_CON_CLAVE.some((patron) => patron.test(camino));
}

/** El resultado no se sabe: la misma operación conserva su clave. */
export function resultadoIncierto(estado: number): boolean {
  return estado === 0 || estado >= 500;
}

export function nuevaClave(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `k-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** Las claves de las operaciones con resultado pendiente o incierto. */
export class ClavesDeEnvio {
  private readonly porCuerpo = new Map<string, string>();
  private readonly porArchivo = new WeakMap<Blob, Map<string, string>>();
  private readonly generar: () => string;

  constructor(generar: () => string = nuevaClave) {
    this.generar = generar;
  }

  /** La clave de esta operación: la misma mientras siga pendiente. */
  clave(ruta: string, cuerpo: string | Blob): string {
    const mapa = this.mapa(cuerpo);
    const identidad = this.identidad(ruta, cuerpo);
    let clave = mapa.get(identidad);
    if (clave === undefined) {
      clave = this.generar();
      mapa.set(identidad, clave);
    }
    return clave;
  }

  /** Con una respuesta definitiva, la operación terminó. */
  resolver(ruta: string, cuerpo: string | Blob, estado: number): void {
    if (!resultadoIncierto(estado)) {
      this.mapa(cuerpo).delete(this.identidad(ruta, cuerpo));
    }
  }

  private mapa(cuerpo: string | Blob): Map<string, string> {
    if (typeof cuerpo === "string") return this.porCuerpo;
    let mapa = this.porArchivo.get(cuerpo);
    if (mapa === undefined) {
      mapa = new Map();
      this.porArchivo.set(cuerpo, mapa);
    }
    return mapa;
  }

  private identidad(ruta: string, cuerpo: string | Blob): string {
    return typeof cuerpo === "string" ? `${ruta}\n${cuerpo}` : ruta;
  }
}

/**
 * Un identificador de operación (`operacion_id` del cuerpo) estable para
 * los mismos datos hasta `olvidar`: así el reintento manda el mismo cuerpo
 * y conserva su clave. Lo usa el inventario, que antes generaba uno nuevo
 * en cada clic.
 */
export class OperacionesEstables {
  private readonly ids = new Map<string, string>();
  private readonly generar: () => string;

  constructor(generar: () => string = nuevaClave) {
    this.generar = generar;
  }

  id(alcance: string, datos: unknown): string {
    const identidad = `${alcance}\n${JSON.stringify(datos)}`;
    let id = this.ids.get(identidad);
    if (id === undefined) {
      id = this.generar();
      this.ids.set(identidad, id);
    }
    return id;
  }

  olvidar(alcance: string, datos: unknown): void {
    this.ids.delete(`${alcance}\n${JSON.stringify(datos)}`);
  }
}

/** Un error con el código HTTP (0: sin conexión), como `ApiError`. */
interface ConEstado {
  status?: number;
}

/**
 * Envía una operación con su clave, si la lleva. `enviar` recibe la clave
 * (o `undefined`) y hace el pedido; la clave se descarta cuando la
 * respuesta es definitiva y se conserva cuando es incierta.
 */
export async function conClave<T>(
  claves: ClavesDeEnvio,
  ruta: string,
  cuerpo: string | Blob,
  enviar: (clave: string | undefined) => Promise<T>,
): Promise<T> {
  if (!llevaClave(ruta)) return enviar(undefined);
  const clave = claves.clave(ruta, cuerpo);
  try {
    const resultado = await enviar(clave);
    claves.resolver(ruta, cuerpo, 200);
    return resultado;
  } catch (error) {
    claves.resolver(ruta, cuerpo, (error as ConEstado).status ?? 0);
    throw error;
  }
}
