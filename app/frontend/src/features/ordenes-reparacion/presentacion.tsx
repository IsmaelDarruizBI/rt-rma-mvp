/**
 * Dónde se muestra cada acción de la Orden y para quién.
 *
 * Los formularios siguen siendo los mismos y los sigue dibujando su panel
 * de siempre; `UbicacionAccion` solo decide DÓNDE aparecen. Todos van al
 * panel de acciones (a la derecha en escritorio, arriba en el celular),
 * separados de la información de la Orden:
 *
 * - en la tarjeta «Próximo paso», si la acción resuelve una tarea de la
 *   situación (la lista la manda el backend en `orden.situacion`);
 * - en «Situaciones especiales», si es excepcional (cancelar, desistir,
 *   pedir redefinición, forzar sin stock, anular un pago…);
 * - en «Otras acciones», en cualquier otro caso (o en su sección, si la
 *   pantalla no tiene ese lugar).
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
import { puedeEjecutar } from "./permisos";

/**
 * Acciones excepcionales: van plegadas, aparte del flujo normal. Si una
 * resuelve la tarea actual (interrumpir junto a completar, forzar sin
 * stock al esperar repuestos) va a «Próximo paso» con su tarea.
 */
export const CODIGOS_ESPECIALES = new Set([
  "INTERRUMPIR_EJECUCION",
  "REQUIERE_REDEFINICION",
  "OVERRIDE_RECURSOS",
  "LIBERAR_ORDEN",
  "LIBERAR_ORDEN_AJENA",
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

// La regla vive en `permisos.ts` (pura, con tests); se reexporta acá.
export { puedeEjecutar };

/** Todas las acciones que la Orden publica, de todos sus grupos. */
export function accionesDeLaOrden(orden: Orden): Accion[] {
  return [
    ...orden.acciones_disponibles,
    ...orden.acciones_cancelacion,
    ...orden.acciones_autorizacion,
    ...orden.acciones_financieras,
    ...orden.acciones_custodia,
    ...(orden.acciones_complementarias ?? []),
  ];
}

/**
 * Opciones secundarias de una tarea: van debajo de la principal, plegadas
 * detrás de su botón (interrumpir la reparación junto a completarla).
 */
export const CODIGOS_SECUNDARIOS = new Set(["INTERRUMPIR_EJECUCION"]);

/** Dónde va una acción que resuelve una tarea de «Próximo paso». */
export interface LugarEnTarjeta {
  lugar: HTMLElement;
  /** Es la única acción principal de su tarea: su título alcanza. */
  unica: boolean;
}

interface Presentacion {
  actor: Usuario | null;
  /** Lugar de la acción en «Próximo paso», si resuelve una tarea. */
  enProximoPaso: (accion: Accion) => LugarEnTarjeta | null;
  /** Lugar de «Situaciones especiales». */
  especiales: HTMLElement | null;
  /** Lugar de «Otras acciones» (las demás que el usuario puede hacer). */
  otras: HTMLElement | null;
  error: ErrorDeComando | null;
}

const PresentacionContext = createContext<Presentacion>({
  actor: null,
  enProximoPaso: () => null,
  especiales: null,
  otras: null,
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
  const { actor, enProximoPaso, especiales, otras } = usePresentacion();
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
  if (CODIGOS_ESPECIALES.has(accion.codigo)) {
    return especiales ? createPortal(contenido, especiales) : contenido;
  }
  return otras ? createPortal(contenido, otras) : contenido;
}

/**
 * Las acciones que el usuario puede hacer y que van a cada lugar del
 * panel: las de las tareas, las especiales y las otras. Es la misma
 * regla que `UbicacionAccion`, para decir qué hay en cada sección plegada.
 */
export function accionesPorLugar(
  orden: Orden,
  actor: Usuario | null,
): { especiales: Accion[]; otras: Accion[] } {
  const enTareas = new Set(
    (orden.situacion?.tareas ?? []).flatMap((tarea) =>
      tarea.acciones
        .filter((accion) => puedeEjecutar(accion, actor))
        .map(claveDeAccion),
    ),
  );
  const propias = accionesDeLaOrden(orden).filter(
    (accion) =>
      puedeEjecutar(accion, actor) && !enTareas.has(claveDeAccion(accion)),
  );
  return {
    especiales: propias.filter((accion) => CODIGOS_ESPECIALES.has(accion.codigo)),
    otras: propias.filter(
      (accion) =>
        !CODIGOS_ESPECIALES.has(accion.codigo) &&
        !(accion.codigo in PASOS_RECOMENDADOS),
    ),
  };
}

/**
 * Pasos recomendados que no son una tarea del backend: si el usuario puede
 * hacerlos, «Próximo paso» los muestra como un paso propio (antes de las
 * tareas). Generar el comprobante de autorización sigue a registrar la
 * autorización del cliente; nunca se genera solo.
 */
export const PASOS_RECOMENDADOS: Record<
  string,
  { titulo: string; motivo: string }
> = {
  EMITIR_COMPROBANTE_AUTORIZACION: {
    titulo: "Generar el comprobante de autorización",
    motivo:
      "Para enviarle al cliente los trabajos que autorizó (no es un " +
      "comprobante de pago).",
  },
};

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
