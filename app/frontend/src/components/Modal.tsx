/**
 * Ventana superpuesta para las operaciones de la aplicación.
 *
 * La pantalla principal queda visible detrás. Cierra con Escape, con la X
 * o tocando el fondo; el foco entra al primer campo y vuelve al botón que
 * la abrió. El contenido decide sus botones de confirmar (los formularios
 * de siempre); el modal solo los presenta.
 */

import {
  type ReactNode,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { IconoCerrar } from "./iconos";

export function Modal({
  titulo,
  onCerrar,
  amplio = false,
  children,
}: {
  titulo: string;
  onCerrar: () => void;
  amplio?: boolean;
  children: ReactNode;
}) {
  const id = useId();
  const ventana = useRef<HTMLDivElement>(null);
  const cerrar = useRef(onCerrar);
  cerrar.current = onCerrar;

  useEffect(() => {
    const previo = document.activeElement as HTMLElement | null;
    const enfocar = window.setTimeout(() => {
      const campo = ventana.current?.querySelector<HTMLElement>(
        ".rt-modal__cuerpo input:not([type=hidden]):not([disabled]), " +
          ".rt-modal__cuerpo select:not([disabled]), " +
          ".rt-modal__cuerpo textarea:not([disabled]), " +
          ".rt-modal__cuerpo button:not([disabled])",
      );
      (campo ?? ventana.current)?.focus();
    }, 0);
    const alTeclear = (evento: KeyboardEvent) => {
      if (evento.key === "Escape") {
        // Una capa por encima (p. ej. una foto ampliada) cierra primero.
        if (document.querySelector("[data-sobre-modal]")) return;
        evento.stopPropagation();
        cerrar.current();
        return;
      }
      if (evento.key !== "Tab" || !ventana.current) return;
      // El foco no se escapa del modal con Tab.
      const enfocables = Array.from(
        ventana.current.querySelectorAll<HTMLElement>(
          "a[href], button:not([disabled]), input:not([disabled]), " +
            "select:not([disabled]), textarea:not([disabled]), " +
            "[tabindex]:not([tabindex='-1'])",
        ),
      ).filter((elemento) => elemento.offsetParent !== null);
      if (enfocables.length === 0) return;
      const primero = enfocables[0];
      const ultimo = enfocables[enfocables.length - 1];
      if (evento.shiftKey && document.activeElement === primero) {
        evento.preventDefault();
        ultimo.focus();
      } else if (!evento.shiftKey && document.activeElement === ultimo) {
        evento.preventDefault();
        primero.focus();
      }
    };
    document.addEventListener("keydown", alTeclear);
    const desplazamiento = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.clearTimeout(enfocar);
      document.removeEventListener("keydown", alTeclear);
      document.body.style.overflow = desplazamiento;
      previo?.focus?.();
    };
  }, []);

  return createPortal(
    <div
      className="rt-modal-fondo"
      onMouseDown={(evento) => {
        if (evento.target === evento.currentTarget) onCerrar();
      }}
    >
      <div
        ref={ventana}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        tabIndex={-1}
        className={`rt-modal${amplio ? " rt-modal--amplio" : ""}`}
      >
        <div className="rt-modal__cabecera">
          <h2 id={id}>{titulo}</h2>
          <button
            type="button"
            className="rt-btn rt-btn--fantasma rt-btn--icono"
            aria-label="Cerrar"
            onClick={onCerrar}
          >
            <IconoCerrar />
          </button>
        </div>
        <div className="rt-modal__cuerpo">{children}</div>
      </div>
    </div>,
    document.body,
  );
}

/** Trae a la ventana un contenedor ya montado y lo devuelve al cerrarse. */
export function Alojar({ contenedor }: { contenedor: HTMLElement }) {
  const lugar = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const destino = lugar.current;
    if (!destino) return;
    destino.appendChild(contenedor);
    return () => {
      if (contenedor.parentElement === destino) destino.removeChild(contenedor);
    };
  }, [contenedor]);
  return <div ref={lugar} />;
}

/**
 * Una ventana cuyo contenido queda montado aunque se cierre: un formulario
 * a medio completar no se pierde si se cierra por accidente.
 */
export function VentanaConservada({
  abierta,
  titulo,
  onCerrar,
  amplio = false,
  children,
}: {
  abierta: boolean;
  titulo: string;
  onCerrar: () => void;
  amplio?: boolean;
  children: ReactNode;
}) {
  const [contenedor] = useState(() => document.createElement("div"));
  return (
    <>
      {createPortal(children, contenedor)}
      {abierta && (
        <Modal titulo={titulo} onCerrar={onCerrar} amplio={amplio}>
          <Alojar contenedor={contenedor} />
        </Modal>
      )}
    </>
  );
}
