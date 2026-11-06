/**
 * «Pendientes»: lo que falta resolver para que la Orden avance.
 *
 * Una lista breve con el estado real que manda el backend
 * (`orden.situacion`: tareas y avisos), más el paso recomendado. Si el
 * pendiente le toca al usuario actual, cada acción con la que puede
 * resolverlo (las que publica el backend para esa tarea) abre su ventana;
 * si no, dice quién lo resuelve.
 */

import { Panel } from "../../components/ui";
import type { Accion, Orden, Usuario } from "../../types/api";
import { claveDeAccion, pendientesDe } from "./acciones";
import { nombreDeUsuario } from "./DetalleOrden";
import { type ErrorDeComando, MensajeDeComando } from "./presentacion";

export function Pendientes({
  orden,
  actor,
  usuarios,
  onResolver,
  nombreAccion,
  abrible,
  errorGeneral,
}: {
  orden: Orden;
  actor: Usuario | null;
  usuarios: Usuario[];
  onResolver: (clave: string) => void;
  /** El mismo nombre que la acción tiene en la barra superior. */
  nombreAccion: (accion: Accion) => string;
  /** Si la acción tiene su ventana disponible (su formulario existe). */
  abrible: (clave: string) => boolean;
  /** Un error que no corresponde a ninguna ventana abierta. */
  errorGeneral: ErrorDeComando | null;
}) {
  const pendientes = pendientesDe(orden, actor).map((pendiente) => ({
    ...pendiente,
    acciones: pendiente.acciones.filter((accion) => abrible(claveDeAccion(accion))),
  }));
  return (
    <Panel titulo="Pendientes">
      {orden.situacion?.descripcion && (
        <p style={{ margin: "0 0 0.6rem", fontSize: "0.85rem" }}>
          {orden.situacion.descripcion}
        </p>
      )}
      {pendientes.length === 0 ? (
        <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--rt-suave)" }}>
          {orden.cerrada
            ? "Orden cerrada: no admite tareas."
            : "No hay pendientes en este momento."}
        </p>
      ) : (
        <ul className="rt-pendientes">
          {pendientes.map((pendiente) => {
            const quien = pendiente.titularId
              ? `${nombreDeUsuario(usuarios, pendiente.titularId)} (técnico titular)`
              : pendiente.responsable;
            const clases = [
              "rt-pendiente",
              pendiente.acciones.length > 0 ? "rt-pendiente--propio" : "",
              pendiente.aviso ? "rt-pendiente--aviso" : "",
            ]
              .filter(Boolean)
              .join(" ");
            return (
              <li key={pendiente.clave} className={clases}>
                <span className="rt-pendiente__punto" aria-hidden="true" />
                <span className="rt-pendiente__texto">
                  {pendiente.titulo}
                  {pendiente.acciones.length === 0 && quien && (
                    <span className="rt-pendiente__quien">A cargo de {quien}</span>
                  )}
                </span>
                {pendiente.acciones.length > 0 && (
                  <span className="rt-pendiente__acciones">
                    {pendiente.acciones.map((accion) => (
                      <button
                        key={claveDeAccion(accion)}
                        type="button"
                        className="rt-btn"
                        onClick={() => onResolver(claveDeAccion(accion))}
                      >
                        {nombreAccion(accion)}
                      </button>
                    ))}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {errorGeneral && <MensajeDeComando error={errorGeneral} />}
    </Panel>
  );
}
