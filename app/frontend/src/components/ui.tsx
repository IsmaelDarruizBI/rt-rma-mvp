/**
 * Piezas visuales compartidas. El estilo vive en `styles.css` (tokens,
 * tarjetas, botones); acá quedan las piezas con su API de siempre.
 */

import type { CSSProperties, ReactNode } from "react";

export const colores = {
  texto: "#111827",
  suave: "#6b7280",
  borde: "#e5e7eb",
  fondo: "#f9fafb",
  acento: "#2563eb",
  ok: "#15803d",
  alerta: "#b45309",
  error: "#b91c1c",
} as const;

export function Panel({
  titulo,
  children,
  style,
}: {
  titulo?: string;
  children: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <section className="rt-tarjeta" style={style}>
      {titulo && <h3 className="rt-tarjeta__titulo">{titulo}</h3>}
      {children}
    </section>
  );
}

export function Etiqueta({
  children,
  color = colores.suave,
}: {
  children: ReactNode;
  color?: string;
}) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "0.15rem 0.5rem",
        borderRadius: 999,
        border: `1px solid ${color}`,
        color,
        fontSize: "0.75rem",
        fontWeight: 600,
      }}
    >
      {children}
    </span>
  );
}

export function Campo({
  etiqueta,
  children,
}: {
  etiqueta: string;
  children: ReactNode;
}) {
  return (
    <label style={{ display: "block", marginBottom: "0.6rem" }}>
      <span
        style={{
          display: "block",
          fontSize: "0.75rem",
          color: colores.suave,
          marginBottom: "0.2rem",
        }}
      >
        {etiqueta}
      </span>
      {children}
    </label>
  );
}

export const estiloInput: CSSProperties = {
  width: "100%",
  padding: "0.45rem 0.6rem",
  border: "1px solid #d1d5db",
  borderRadius: 6,
  fontSize: "0.875rem",
  background: "#fff",
  fontFamily: "inherit",
  boxSizing: "border-box",
};

export function Boton({
  children,
  onClick,
  disabled,
  variante = "primario",
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variante?: "primario" | "secundario";
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rt-btn${variante === "primario" ? " rt-btn--primario" : ""}`}
    >
      {children}
    </button>
  );
}

export function MensajeError({ mensaje }: { mensaje: string }) {
  return (
    <p
      role="alert"
      style={{
        margin: "0.75rem 0 0",
        padding: "0.6rem 0.8rem",
        borderRadius: 6,
        border: `1px solid ${colores.error}`,
        background: "#fff5f5",
        color: colores.error,
        fontSize: "0.85rem",
      }}
    >
      {mensaje}
    </p>
  );
}

/** Los importes llegan como string (Decimal): solo se formatean. */
export function importe(valor: string): string {
  const numero = Number(valor);
  if (Number.isNaN(numero)) return valor;
  return numero.toLocaleString("es-AR", {
    style: "currency",
    currency: "ARS",
    maximumFractionDigits: 2,
  });
}

export function fechaCorta(iso: string): string {
  return new Date(iso).toLocaleString("es-AR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
