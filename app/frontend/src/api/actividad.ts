/**
 * Actividad de red: qué pedidos están en curso.
 *
 * Sirve para dos cosas: la barra de actividad del layout, que avisa que algo
 * se está cargando o guardando sin bloquear la pantalla, y para no repetir
 * una lectura idéntica que todavía no terminó.
 *
 * Sin dependencias de React ni del navegador: se prueba con node --test.
 */

/** Cuenta los pedidos en curso y avisa cuando cambia si hay alguno. */
export class ActividadDeRed {
  private enCurso = 0;
  private readonly oyentes = new Set<() => void>();

  activa = (): boolean => this.enCurso > 0;

  suscribir = (oyente: () => void): (() => void) => {
    this.oyentes.add(oyente);
    return () => this.oyentes.delete(oyente);
  };

  /** Cuenta `pedido` mientras dura, termine bien o mal. */
  async seguir<T>(pedido: () => Promise<T>): Promise<T> {
    this.cambiar(1);
    try {
      return await pedido();
    } finally {
      this.cambiar(-1);
    }
  }

  private cambiar(diferencia: number): void {
    const antes = this.activa();
    this.enCurso += diferencia;
    if (antes !== this.activa()) {
      this.oyentes.forEach((oyente) => oyente());
    }
  }
}

/**
 * Lecturas iguales simultáneas: la segunda espera la respuesta de la primera.
 * Solo mientras está en curso: al terminar se olvida, así que no es un caché
 * y nunca devuelve datos de una lectura ya terminada.
 */
export class LecturasEnCurso {
  private readonly pendientes = new Map<string, Promise<unknown>>();

  compartir<T>(clave: string, leer: () => Promise<T>): Promise<T> {
    const pendiente = this.pendientes.get(clave);
    if (pendiente) return pendiente as Promise<T>;
    const nueva = leer().finally(() => this.pendientes.delete(clave));
    this.pendientes.set(clave, nueva);
    return nueva;
  }
}
