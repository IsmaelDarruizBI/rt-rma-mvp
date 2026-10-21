/**
 * Cliente HTTP minimo contra la API del MVP.
 *
 * Su unica responsabilidad es hablar HTTP y traducir los errores de la
 * API a algo que la UI pueda mostrar. No decide nada de negocio: que
 * acciones son posibles lo dice el backend en cada respuesta.
 */

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

/** Error funcional devuelto por la API, con su mensaje legible. */
export class ApiError extends Error {
  readonly status: number;
  readonly codigo: string;

  constructor(status: number, codigo: string, mensaje: string) {
    super(mensaje);
    this.name = "ApiError";
    this.status = status;
    this.codigo = codigo;
  }
}

interface CuerpoError {
  error?: { codigo?: string; mensaje?: string };
}

async function pedir<T>(ruta: string, init?: RequestInit): Promise<T> {
  let respuesta: Response;

  try {
    respuesta = await fetch(`${API_BASE_URL}${ruta}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(
      0,
      "SIN_CONEXION",
      "No se pudo contactar al backend. Verificá que esté levantado.",
    );
  }

  if (!respuesta.ok) {
    let codigo = "ERROR";
    let mensaje = `La operación falló (HTTP ${respuesta.status}).`;
    try {
      const cuerpo: CuerpoError = await respuesta.json();
      codigo = cuerpo.error?.codigo ?? codigo;
      mensaje = cuerpo.error?.mensaje ?? mensaje;
    } catch {
      // La respuesta no traía el cuerpo de error esperado.
    }
    throw new ApiError(respuesta.status, codigo, mensaje);
  }

  return (await respuesta.json()) as T;
}

export function get<T>(ruta: string): Promise<T> {
  return pedir<T>(ruta);
}

/** Un archivo (por ejemplo, un PDF) en vez de JSON. */
export async function getArchivo(ruta: string): Promise<Blob> {
  let respuesta: Response;
  try {
    respuesta = await fetch(`${API_BASE_URL}${ruta}`);
  } catch {
    throw new ApiError(
      0,
      "SIN_CONEXION",
      "No se pudo contactar al backend. Verificá que esté levantado.",
    );
  }
  if (!respuesta.ok) {
    let codigo = "ERROR";
    let mensaje = `No se pudo obtener el archivo (HTTP ${respuesta.status}).`;
    try {
      const cuerpo: CuerpoError = await respuesta.json();
      codigo = cuerpo.error?.codigo ?? codigo;
      mensaje = cuerpo.error?.mensaje ?? mensaje;
    } catch {
      // La respuesta no traía el cuerpo de error esperado.
    }
    throw new ApiError(respuesta.status, codigo, mensaje);
  }
  return respuesta.blob();
}

export function post<T>(ruta: string, cuerpo: unknown): Promise<T> {
  return pedir<T>(ruta, {
    method: "POST",
    body: JSON.stringify(cuerpo),
  });
}

/** URL absoluta de un recurso de la API (por ejemplo, una foto). */
export function urlApi(ruta: string): string {
  return `${API_BASE_URL}${ruta}`;
}

/** Un archivo como cuerpo (por ejemplo, una foto), con respuesta JSON. */
export function postArchivo<T>(ruta: string, archivo: Blob): Promise<T> {
  return pedir<T>(ruta, {
    method: "POST",
    body: archivo,
    headers: { "Content-Type": archivo.type || "application/octet-stream" },
  });
}

export function put<T>(ruta: string, cuerpo: unknown): Promise<T> {
  return pedir<T>(ruta, {
    method: "PUT",
    body: JSON.stringify(cuerpo),
  });
}
