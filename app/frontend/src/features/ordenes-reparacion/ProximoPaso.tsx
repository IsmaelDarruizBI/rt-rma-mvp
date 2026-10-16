/**
 * «Próximo paso»: qué hay que hacer con la Orden, quién puede hacerlo, por
 * qué está pendiente y, si le toca al usuario actual, el formulario.
 *
 * Las tareas y sus acciones las manda el backend (`orden.situacion`). Los
 * formularios no se dibujan acá: cada panel dibuja el suyo y
 * `UbicacionAccion` lo trae al lugar de su tarea con un portal, así que
 * no hay un segundo mecanismo para ejecutar acciones.
 *
 * Antes de las tareas puede ir un paso recomendado que no es una tarea
 * del backend (`PASOS_RECOMENDADOS`: generar el comprobante de
 * autorización), solo si el usuario puede hacerlo.
 */

import { colores } from "../../components/ui";
import type {
  EtapaSituacion,
  Orden,
  TareaSituacion,
  Usuario,
} from "../../types/api";
import { nombreDeUsuario } from "./DetalleOrden";
import {
  type ErrorDeComando,
  LugarDeFormularios,
  MensajeDeComando,
  PASOS_RECOMENDADOS,
  accionesDeLaOrden,
  claveDeAccion,
  irAAccion,
  puedeEjecutar,
} from "./presentacion";

/** Lugar del paso recomendado (no es el índice de ninguna tarea). */
export const INDICE_PASO_RECOMENDADO = -1;

/** Quién debe actuar, con el nombre del titular si la tarea es suya. */
function quienDebe(
  tarea: { responsable: string | null; acciones: TareaSituacion["acciones"] },
  usuarios: Usuario[],
): string {
  const titular = tarea.acciones.find((accion) => accion.usuario_id)?.usuario_id;
  if (titular) return `${nombreDeUsuario(usuarios, titular)} (técnico titular)`;
  return tarea.responsable ?? "otro sector";
}

function enMinuscula(texto: string): string {
  return texto.charAt(0).toLowerCase() + texto.slice(1);
}

export function ProximoPaso({
  orden,
  actor,
  usuarios,
  registrarTarea,
  errorGeneral,
}: {
  orden: Orden;
  actor: Usuario | null;
  usuarios: Usuario[];
  /** Lugar donde los paneles dibujan el formulario de la tarea `indice`. */
  registrarTarea: (indice: number) => (elemento: HTMLElement | null) => void;
  /** Un error que no corresponde a ningún formulario visible. */
  errorGeneral: ErrorDeComando | null;
}) {
  const situacion = orden.situacion;
  if (!situacion) return null;
  const { tareas, avisos } = situacion;
  const recomendado = orden.cerrada
    ? undefined
    : accionesDeLaOrden(orden).find(
        (accion) =>
          accion.codigo in PASOS_RECOMENDADOS && puedeEjecutar(accion, actor),
      );

  return (
    <section
      aria-label="Próximo paso"
      style={{
        border: `2px solid ${tareas.length ? colores.acento : colores.borde}`,
        borderRadius: 8,
        padding: "1rem",
        background: "#fff",
      }}
    >
      <h3
        style={{
          margin: "0 0 0.3rem",
          fontSize: "0.85rem",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          color: colores.acento,
        }}
      >
        Próximo paso
      </h3>
      <p style={{ margin: "0 0 0.8rem", fontSize: "0.9rem" }}>
        {situacion.descripcion}
      </p>

      {recomendado && (
        <div
          style={{
            marginBottom: "0.8rem",
            paddingBottom: tareas.length ? "0.8rem" : 0,
            borderBottom: tareas.length ? `1px solid ${colores.borde}` : "none",
          }}
        >
          <p style={{ margin: "0 0 0.15rem", fontWeight: 700 }}>
            {PASOS_RECOMENDADOS[recomendado.codigo].titulo}
          </p>
          <p
            style={{
              margin: "0 0 0.5rem",
              fontSize: "0.8rem",
              color: colores.suave,
            }}
          >
            Lo hace: {quienDebe(
              {
                responsable: recomendado.roles.includes("RECEPCION")
                  ? "Recepción"
                  : null,
                acciones: [recomendado],
              },
              usuarios,
            )}{" "}
            · {PASOS_RECOMENDADOS[recomendado.codigo].motivo}
          </p>
          <LugarDeFormularios
            onElemento={registrarTarea(INDICE_PASO_RECOMENDADO)}
          />
        </div>
      )}

      {tareas.length === 0 && !recomendado && (
        <p style={{ margin: 0, fontSize: "0.85rem", color: colores.suave }}>
          {orden.cerrada
            ? "Orden cerrada: se puede consultar, pero no admite tareas."
            : "No hay tareas pendientes en este momento."}
        </p>
      )}

      {tareas.map((tarea, indice) => {
        const propias = tarea.acciones.filter((accion) =>
          puedeEjecutar(accion, actor),
        );
        return (
          <div
            key={`${orden.id}-${indice}-${tarea.titulo}`}
            style={{
              paddingTop: indice > 0 ? "0.8rem" : 0,
              marginTop: indice > 0 ? "0.8rem" : 0,
              borderTop: indice > 0 ? `1px solid ${colores.borde}` : "none",
            }}
          >
            <p style={{ margin: "0 0 0.15rem", fontWeight: 700 }}>
              {tarea.titulo}
            </p>
            <p
              style={{
                margin: "0 0 0.5rem",
                fontSize: "0.8rem",
                color: colores.suave,
              }}
            >
              Lo hace: {quienDebe(tarea, usuarios)} · {tarea.motivo}
            </p>
            {propias.length > 0 ? (
              <LugarDeFormularios onElemento={registrarTarea(indice)} />
            ) : (
              <p
                role="status"
                style={{
                  margin: 0,
                  padding: "0.5rem 0.7rem",
                  borderRadius: 6,
                  background: colores.fondo,
                  border: `1px dashed ${colores.borde}`,
                  fontSize: "0.85rem",
                }}
              >
                Esperando a {quienDebe(tarea, usuarios)}:{" "}
                {enMinuscula(tarea.titulo)}.
              </p>
            )}
          </div>
        );
      })}

      {avisos.length > 0 && (
        <div
          style={{
            marginTop: "0.9rem",
            padding: "0.6rem 0.8rem",
            borderRadius: 6,
            border: `1px solid ${colores.alerta}`,
            background: "#fff8e6",
            fontSize: "0.85rem",
          }}
        >
          <strong>También pendiente</strong>
          <ul style={{ margin: "0.3rem 0 0", paddingLeft: "1.1rem" }}>
            {avisos.map((aviso) => {
              const propia = aviso.acciones.find((accion) =>
                puedeEjecutar(accion, actor),
              );
              return (
                <li key={aviso.codigo} style={{ marginBottom: "0.2rem" }}>
                  {aviso.titulo}{" "}
                  {propia ? (
                    <button
                      type="button"
                      onClick={() => irAAccion(claveDeAccion(propia))}
                      style={{
                        border: "none",
                        background: "none",
                        padding: 0,
                        color: colores.acento,
                        textDecoration: "underline",
                        cursor: "pointer",
                        font: "inherit",
                      }}
                    >
                      Resolver
                    </button>
                  ) : (
                    aviso.responsable && (
                      <span style={{ color: colores.suave }}>
                        (a cargo de {aviso.responsable})
                      </span>
                    )
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {errorGeneral && <MensajeDeComando error={errorGeneral} />}
    </section>
  );
}

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
