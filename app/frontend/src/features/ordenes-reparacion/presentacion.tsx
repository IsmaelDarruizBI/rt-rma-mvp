/**
 * Dónde se muestra cada acción de la Orden y para quién.
 *
 * Los formularios siguen siendo los mismos y los sigue dibujando su panel
 * de siempre; `UbicacionAccion` solo decide DÓNDE aparecen: cada uno se
 * registra como una acción de la barra superior y se abre en una ventana
 * superpuesta (`AnfitrionAcciones`).
 *
 * El formulario queda montado en un contenedor propio mientras la acción
 * exista: cerrar la ventana no borra lo que se escribió, y el error del
 * comando aparece dentro de la ventana, junto al formulario.
 *
 * Una acción que el usuario actual no puede ejecutar no se registra
 * (`puedeEjecutar`, la regla de siempre). Es presentación: el backend
 * vuelve a validar rol, titular y estado cuando llega el comando.
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

import { Alojar, Modal } from "../../components/Modal";
import type { Accion, Usuario } from "../../types/api";
import { claveDeAccion } from "./acciones";
import { puedeEjecutar } from "./permisos";

export {
  CODIGOS_ESPECIALES,
  CODIGOS_SECUNDARIOS,
  PASOS_RECOMENDADOS,
  accionesDeLaOrden,
  claveDeAccion,
} from "./acciones";
export { puedeEjecutar };

/** Error de un comando, con la acción desde la que se envió. */
export interface ErrorDeComando {
  mensaje: string;
  tecnico: string;
  /** `data-accion` del formulario que lo envió, si se conoce. */
  clave: string | null;
}

/** Una acción registrada: su formulario vive en `contenedor`. */
export interface AccionRegistrada {
  clave: string;
  accion: Accion;
  contenedor: HTMLElement;
}

interface Presentacion {
  actor: Usuario | null;
  error: ErrorDeComando | null;
  registrar: (registrada: AccionRegistrada) => void;
  quitar: (clave: string, contenedor: HTMLElement) => void;
}

const PresentacionContext = createContext<Presentacion>({
  actor: null,
  error: null,
  registrar: () => undefined,
  quitar: () => undefined,
});

export const ProveedorPresentacion = PresentacionContext.Provider;

// Dentro de la ventana el título de la acción ya está en la cabecera.
const TituloVisibleContext = createContext(true);

/** El título de un formulario de acción (se omite dentro de su ventana). */
export function TituloAccion({ children }: { children: ReactNode }) {
  if (!useContext(TituloVisibleContext)) return null;
  return <p style={{ margin: "0 0 0.5rem", fontWeight: 600 }}>{children}</p>;
}

export function usePresentacion(): Presentacion {
  return useContext(PresentacionContext);
}

/**
 * Envuelve el formulario de UNA acción: no lo dibuja si el usuario no
 * puede ejecutarla; si puede, lo registra para la barra de acciones y lo
 * mantiene montado fuera de la pantalla hasta que se abra su ventana.
 */
export function UbicacionAccion({
  accion,
  children,
}: {
  accion: Accion;
  children: ReactNode;
}) {
  const { actor } = usePresentacion();
  if (!puedeEjecutar(accion, actor)) return null;
  return <AccionEnVentana accion={accion}>{children}</AccionEnVentana>;
}

function AccionEnVentana({
  accion,
  children,
}: {
  accion: Accion;
  children: ReactNode;
}) {
  const { registrar, quitar } = usePresentacion();
  const [contenedor] = useState(() => document.createElement("div"));
  const clave = claveDeAccion(accion);
  const ultima = useRef(accion);
  ultima.current = accion;

  useEffect(() => {
    registrar({ clave, accion: ultima.current, contenedor });
    return () => quitar(clave, contenedor);
  }, [clave, contenedor, registrar, quitar]);

  return createPortal(
    <TituloVisibleContext.Provider value={false}>
      <div id={idDeAccion(clave)} data-accion={clave}>
        {children}
        <ErrorJuntoAccion clave={clave} />
      </div>
    </TituloVisibleContext.Provider>,
    contenedor,
  );
}

/**
 * La ventana de la acción abierta: trae su formulario (ya montado) y lo
 * devuelve a su contenedor al cerrarse, sin desmontarlo.
 */
export function AnfitrionAcciones({
  abierta,
  onCerrar,
  titulo,
}: {
  abierta: AccionRegistrada | null;
  onCerrar: () => void;
  /** El nombre de la acción, el mismo que tiene su botón. */
  titulo?: (accion: Accion) => string;
}) {
  if (!abierta) return null;
  return (
    <Modal
      titulo={titulo ? titulo(abierta.accion) : abierta.accion.etiqueta}
      onCerrar={onCerrar}
      amplio={VENTANAS_AMPLIAS.has(abierta.accion.codigo)}
    >
      <Alojar contenedor={abierta.contenedor} />
    </Modal>
  );
}

/** Formularios extensos: ventana amplia. */
const VENTANAS_AMPLIAS = new Set([
  "REGISTRAR_RECEPCION",
  "COMPLETAR_EJECUCION",
  "INTERRUMPIR_EJECUCION",
  "REQUIERE_REDEFINICION",
  "REGISTRAR_AUTORIZACION_CLIENTE",
  "REGISTRAR_DECISION_CLIENTE",
  "ENTREGAR",
  "REGISTRAR_DEVOLUCION",
  "LIBERAR_ORDEN_AJENA",
]);

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
        border: "1px solid #fecaca",
        background: "var(--rt-error-suave)",
        color: "var(--rt-error)",
        fontSize: "0.85rem",
      }}
    >
      {error.mensaje}
      {error.tecnico !== error.mensaje && (
        <details style={{ marginTop: "0.3rem", color: "var(--rt-suave)" }}>
          <summary style={{ cursor: "pointer", fontSize: "0.75rem" }}>
            Detalle técnico
          </summary>
          <span style={{ fontSize: "0.75rem" }}>{error.tecnico}</span>
        </details>
      )}
    </div>
  );
}

/** Pide abrir la ventana de una acción (la atiende el panel de la Orden). */
export const EVENTO_ABRIR_ACCION = "rt-abrir-accion";

export function irAAccion(clave: string): void {
  window.dispatchEvent(
    new CustomEvent<string>(EVENTO_ABRIR_ACCION, { detail: clave }),
  );
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
      className="rt-plegable"
      open={abierta}
      onToggle={(evento) => setAbiertaAhora(evento.currentTarget.open)}
    >
      <summary>
        <span className="rt-plegable__titulo">{titulo}</span>
        {resumen && !abiertaAhora && (
          <span className="rt-plegable__resumen">{resumen}</span>
        )}
      </summary>
      <div className="rt-plegable__cuerpo">{children}</div>
    </details>
  );
}
