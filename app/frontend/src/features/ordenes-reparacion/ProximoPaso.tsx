/**
 * Las etapas del negocio de la Orden (con su estado real).
 *
 * «Próximo paso» se reemplazó por «Pendientes» (`Pendientes.tsx`) y por
 * las acciones de la barra superior: los formularios se abren en ventanas.
 */

import { colores } from "../../components/ui";
import type { EtapaSituacion } from "../../types/api";

const ESTILO_ETAPA: Record<
  EtapaSituacion["estado"],
  { icono: string; color: string; fondo: string }
> = {
  COMPLETA: { icono: "✓", color: colores.ok, fondo: "#f3faf4" },
  EN_CURSO: { icono: "●", color: colores.acento, fondo: "#eef4ff" },
  PENDIENTE: { icono: "○", color: colores.suave, fondo: "#fff" },
  NO_APLICA: { icono: "–", color: "#999", fondo: colores.fondo },
};

const TEXTO_ESTADO: Record<EtapaSituacion["estado"], string> = {
  COMPLETA: "completa",
  EN_CURSO: "en curso",
  PENDIENTE: "pendiente",
  NO_APLICA: "no aplica",
};

/**
 * Las seis etapas del negocio. Cada una muestra su estado real: el
 * proceso no es lineal y puede haber más de una en curso.
 */
export function EtapasNegocio({ etapas }: { etapas: EtapaSituacion[] }) {
  return (
    <ol
      aria-label="Etapas de la Orden"
      style={{
        margin: "0.7rem 0 0",
        padding: 0,
        listStyle: "none",
        display: "flex",
        flexWrap: "wrap",
        gap: "0.3rem",
      }}
    >
      {etapas.map((etapa) => {
        const estilo = ESTILO_ETAPA[etapa.estado];
        return (
          <li
            key={etapa.codigo}
            title={`${etapa.titulo}: ${TEXTO_ESTADO[etapa.estado]}${
              etapa.detalle ? ` · ${etapa.detalle}` : ""
            }`}
            style={{
              padding: "0.15rem 0.5rem",
              borderRadius: 999,
              border: `1px solid ${estilo.color}`,
              background: estilo.fondo,
              color: estilo.color,
              fontSize: "0.75rem",
              fontWeight: etapa.estado === "EN_CURSO" ? 700 : 500,
              textDecoration:
                etapa.estado === "NO_APLICA" ? "line-through" : undefined,
            }}
          >
            {estilo.icono} {etapa.titulo}
            {etapa.estado === "EN_CURSO" && etapa.detalle && (
              <span className="rt-solo-escritorio" style={{ fontWeight: 400 }}>
                {" "}
                · {etapa.detalle}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
