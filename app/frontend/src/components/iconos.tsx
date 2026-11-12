/** Íconos de línea (SVG en línea, sin dependencias). */

import type { ReactNode } from "react";

function Icono({ children }: { children: ReactNode }) {
  return (
    <svg
      className="rt-sidebar__icono"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      width={20}
      height={20}
    >
      {children}
    </svg>
  );
}

export const IconoInicio = () => (
  <Icono>
    <path d="M3 10.5 12 3l9 7.5" />
    <path d="M5 9.5V21h14V9.5" />
    <path d="M10 21v-6h4v6" />
  </Icono>
);

export const IconoOrdenes = () => (
  <Icono>
    <rect x="5" y="3" width="14" height="18" rx="2" />
    <path d="M9 7h6M9 11h6M9 15h4" />
  </Icono>
);

export const IconoTaller = () => (
  <Icono>
    <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z" />
  </Icono>
);

export const IconoInventario = () => (
  <Icono>
    <path d="m21 8-9-5-9 5 9 5 9-5z" />
    <path d="M3 8v8l9 5 9-5V8" />
    <path d="M12 13v8" />
  </Icono>
);

export const IconoConfiguracion = () => (
  <Icono>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1" />
  </Icono>
);

export const IconoReportes = () => (
  <Icono>
    <path d="M4 20V10" />
    <path d="M10 20V4" />
    <path d="M16 20v-7" />
    <path d="M22 20H2" />
  </Icono>
);

export const IconoContraer = () => (
  <Icono>
    <path d="m15 6-6 6 6 6" />
  </Icono>
);

export const IconoExpandir = () => (
  <Icono>
    <path d="m9 6 6 6-6 6" />
  </Icono>
);

export const IconoMenu = () => (
  <Icono>
    <path d="M4 6h16M4 12h16M4 18h16" />
  </Icono>
);

export const IconoCerrar = () => (
  <Icono>
    <path d="M6 6l12 12M18 6 6 18" />
  </Icono>
);

export const IconoMas = () => (
  <Icono>
    <circle cx="5" cy="12" r="1.2" />
    <circle cx="12" cy="12" r="1.2" />
    <circle cx="19" cy="12" r="1.2" />
  </Icono>
);

export const IconoSalir = () => (
  <Icono>
    <path d="M15 4h4v16h-4" />
    <path d="M10 16l4-4-4-4M14 12H4" />
  </Icono>
);
