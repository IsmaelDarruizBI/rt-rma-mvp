/**
 * Dónde se muestra cada acción de la Orden y para quién.
 *
 * Los formularios siguen siendo los mismos y los sigue dibujando su panel
 * de siempre; `UbicacionAccion` solo decide DÓNDE aparecen:
 *
 * - en la tarjeta «Próximo paso», si la acción resuelve una tarea de la
 *   situación (la lista la manda el backend en `orden.situacion`);
 * - en «Otras acciones / Situaciones especiales», si es excepcional
 *   (cancelar, desistir, interrumpir, forzar…);
 * - en su sección, en cualquier otro caso.
 *
 * Una acción que el usuario actual no puede ejecutar no se dibuja (la
 * tarjeta dice a quién le toca). Es presentación: el backend vuelve a
 * validar rol, titular y estado cuando llega el comando.
 */

import {
  type ReactNode,
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { colores } from "../../components/ui";
import type { Accion, Orden, Usuario } from "../../types/api";

/** Acciones excepcionales: van plegadas, aparte del flujo normal. */
export const CODIGOS_ESPECIALES = new Set([
  "INTERRUMPIR_EJECUCION",
  "REQUIERE_REDEFINICION",
  "OVERRIDE_RECURSOS",
  "LIBERAR_ORDEN",
  "CANCELAR_DETALLE",
  "CANCELAR_ORDEN",
  "DESISTIR_DETALLE",
  "DESISTIR_TODO",
  "REGISTRAR_EQUIPO_NO_RECIBIDO",
  "ANULAR_PAGO",
  "INICIAR_GARANTIA_RMA",
  "ESPERAR_RECURSOS",
]);

/** Error de un comando, con la acción desde la que se envió. */
export interface ErrorDeComando {
  mensaje: string;
  tecnico: string;
  /** `data-accion` del formulario que lo envió, si se conoce. */
  clave: string | null;
}

export function claveDeAccion(accion: Accion): string {
  return [
    accion.codigo,
    accion.detalle_id ?? "",
    accion.ejecucion_id ?? "",
    accion.pago_id ?? "",
  ].join("|");
}

/**
 * Lo mismo que valida el backend, para no ofrecer lo que va a rechazar:
 * rol (salvo un paso de sistema o sin rol definido) y titular de la toma.
 */
export function puedeEjecutar(accion: Accion, actor: Usuario | null): boolean {
  if (!accion.requiere_actor) return true;
  if (actor === null) return false;
  if (accion.roles.length > 0 && !accion.roles.includes(actor.rol)) {
    return false;
  }
  return accion.usuario_id === null || accion.usuario_id === actor.id;
}

/** Todas las acciones que la Orden publica, de todos sus grupos. */
export function accionesDeLaOrden(orden: Orden): Accion[] {
  return [
    ...orden.acciones_disponibles,
    ...orden.acciones_cancelacion,
    ...orden.acciones_autorizacion,
    ...orden.acciones_financieras,
    ...orden.acciones_custodia,
  ];
}

/** Dónde va una acción que resuelve una tarea de «Próximo paso». */
export interface LugarEnTarjeta {
  lugar: HTMLElement;
  /** Es la única acción de su tarea: el título de la tarea alcanza. */
  unica: boolean;
}

interface Presentacion {
  actor: Usuario | null;
  /** Lugar de la acción en «Próximo paso», si resuelve una tarea. */
  enProximoPaso: (accion: Accion) => LugarEnTarjeta | null;
  /** Lugar de «Otras acciones / Situaciones especiales». */
  especiales: HTMLElement | null;
  error: ErrorDeComando | null;
}

const PresentacionContext = createContext<Presentacion>({
  actor: null,
  enProximoPaso: () => null,
  especiales: null,
  error: null,
});

export const ProveedorPresentacion = PresentacionContext.Provider;

// Dentro de la tarjeta, el formulario de una tarea de una sola acción no
// repite el título: ya lo dice la tarea.
const TituloVisibleContext = createContext(true);

/** El título de un formulario de acción (se omite si repite la tarea). */
export function TituloAccion({ children }: { children: ReactNode }) {
  if (!useContext(TituloVisibleContext)) return null;
  return <p style={{ margin: "0 0 0.5rem", fontWeight: 600 }}>{children}</p>;
}

export function usePresentacion(): Presentacion {
  return useContext(PresentacionContext);
}

/**
 * Envuelve el formulario de UNA acción: lo oculta si el usuario no puede
 * ejecutarla y lo lleva a la tarjeta o al grupo de especiales cuando
 * corresponde. El error de esa acción aparece justo debajo.
 */
export function UbicacionAccion({
  accion,
  children,
}: {
  accion: Accion;
  children: ReactNode;
}) {
  const { actor, enProximoPaso, especiales } = usePresentacion();
  if (!puedeEjecutar(accion, actor)) return null;
  const clave = claveDeAccion(accion);
  const contenido = (
    <div id={idDeAccion(clave)} data-accion={clave}>
      {children}
      <ErrorJuntoAccion clave={clave} />
    </div>
  );
  const tarea = enProximoPaso(accion);
  if (tarea) {
    return createPortal(
      <TituloVisibleContext.Provider value={!tarea.unica}>
        {contenido}
      </TituloVisibleContext.Provider>,
      tarea.lugar,
    );
  }
  return CODIGOS_ESPECIALES.has(accion.codigo) && especiales
    ? createPortal(contenido, especiales)
    : contenido;
}

export function idDeAccion(clave: string): string {
  return `accion-${clave.replace(/[^\w-]/g, "_")}`;
}

function ErrorJuntoAccion({ clave }: { clave: string }) {
  const { error } = usePresentacion();
  const ref = useRef<HTMLDivElement>(null);
  const visible = error !== null && error.clave === clave;
  useEffect(() => {
    if (visible) ref.current?.scrollIntoView({ block: "nearest" });
  }, [visible, error]);
  if (!visible || error === null) return null;
  return (
    <div ref={ref}>
      <MensajeDeComando error={error} />
    </div>
  );
}

/** Un error legible, con el texto técnico original a un clic. */
export function MensajeDeComando({ error }: { error: ErrorDeComando }) {
  return (
    <div
      role="alert"
      style={{
        margin: "0.6rem 0",
        padding: "0.6rem 0.8rem",
        borderRadius: 6,
        border: `1px solid ${colores.error}`,
        background: "#fff5f5",
        color: colores.error,
        fontSize: "0.85rem",
      }}
    >
      {error.mensaje}
      {error.tecnico !== error.mensaje && (
        <details style={{ marginTop: "0.3rem", color: colores.suave }}>
          <summary style={{ cursor: "pointer", fontSize: "0.75rem" }}>
            Detalle técnico
          </summary>
          <span style={{ fontSize: "0.75rem" }}>{error.tecnico}</span>
        </details>
      )}
    </div>
  );
}

/**
 * Lleva al formulario de una acción: abre las secciones que lo contienen,
 * lo centra en pantalla y pone el foco en su primer campo.
 */
export function irAAccion(clave: string): void {
  const elemento = document.getElementById(idDeAccion(clave));
  if (!elemento) return;
  let padre = elemento.parentElement;
  while (padre) {
    if (padre instanceof HTMLDetailsElement) padre.open = true;
    padre = padre.parentElement;
  }
  elemento.scrollIntoView({ behavior: "smooth", block: "center" });
  const foco = elemento.querySelector<HTMLElement>(
    "input, select, textarea, button:not([disabled])",
  );
  foco?.focus({ preventScroll: true });
}

/**
 * Sección plegable con su título y una línea de resumen que se ve aunque
 * esté cerrada. Cada una se abre por separado.
 */
export function SeccionPlegable({
  titulo,
  resumen,
  abierta = false,
  children,
}: {
  titulo: string;
  resumen?: ReactNode;
  abierta?: boolean;
  children: ReactNode;
}) {
  const [abiertaAhora, setAbiertaAhora] = useState(abierta);
  return (
    <details
      open={abierta}
      onToggle={(evento) => setAbiertaAhora(evento.currentTarget.open)}
      style={{
        border: `1px solid ${colores.borde}`,
        borderRadius: 8,
        background: "#fff",
      }}
    >
      <summary
        style={{
          cursor: "pointer",
          padding: "0.8rem 1rem",
          listStyle: "revert",
        }}
      >
        <span
          style={{
            fontSize: "0.85rem",
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            color: colores.suave,
          }}
        >
          {titulo}
        </span>
        {resumen && !abiertaAhora && (
          <span
            style={{
              display: "block",
              marginTop: "0.2rem",
              fontSize: "0.85rem",
              color: colores.texto,
              overflowWrap: "anywhere",
            }}
          >
            {resumen}
          </span>
        )}
      </summary>
      <div style={{ padding: "0 1rem 1rem" }}>{children}</div>
    </details>
  );
}

/**
 * Un lugar para formularios que otros componentes dibujan con un portal.
 * `onElemento` recibe el nodo cuando existe (y `null` al desmontarse).
 */
export function LugarDeFormularios({
  onElemento,
}: {
  onElemento: (elemento: HTMLElement | null) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    onElemento(ref.current);
    return () => onElemento(null);
  }, [onElemento]);
  return <div ref={ref} />;
}
