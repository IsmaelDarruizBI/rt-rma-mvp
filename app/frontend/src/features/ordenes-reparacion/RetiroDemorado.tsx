/**
 * Retiro demorado (DEC-MI-14): el equipo está listo, se avisó al cliente y
 * venció el plazo configurado. La Orden sigue abierta: nunca se cierra ni
 * se dispone del equipo por el plazo. Recepción y Administración registran
 * los seguimientos (llamados, mensajes) con una nota.
 */

import { useState } from "react";

import { Boton, Campo, colores, estiloInput, fechaCorta } from "../../components/ui";
import { puede } from "../../lib/roles";
import type { Orden, Usuario } from "../../types/api";
import { nombreDeUsuario } from "./DetalleOrden";

const CANALES = ["TELEFONO", "WHATSAPP", "EMAIL", "PRESENCIAL"] as const;

export function RetiroDemorado({
  orden,
  actor,
  usuarios,
  ocupado,
  onRegistrar,
}: {
  orden: Orden;
  actor: Usuario | null;
  usuarios: Usuario[];
  ocupado: boolean;
  onRegistrar: (nota: string, canal: string | null) => void;
}) {
  const [nota, setNota] = useState("");
  const [canal, setCanal] = useState("");
  const dias = orden.retiro_demorado_dias ?? null;
  const seguimientos = orden.seguimientos_retiro ?? [];
  if (dias === null && seguimientos.length === 0) return null;
  const habilitado =
    dias !== null &&
    puede(actor, "RETIRO_SEGUIMIENTO", ["RECEPCION", "ADMINISTRADOR"]);

  return (
    <section
      aria-label="Retiro demorado"
      style={{
        margin: "0 0 0.8rem",
        padding: "0.6rem 0.8rem",
        borderRadius: 6,
        border: `1px solid ${colores.alerta}`,
        background: "#fff8e6",
        fontSize: "0.9rem",
      }}
    >
      {dias !== null && (
        <p role="status" style={{ margin: "0 0 0.4rem" }}>
          <strong>Retiro demorado:</strong> {dias} días desde el aviso de
          equipo listo. La Orden sigue abierta; registrá cada seguimiento.
        </p>
      )}
      {seguimientos.length > 0 && (
        <ul style={{ margin: "0 0 0.5rem", paddingLeft: "1.1rem" }}>
          {seguimientos.map((seguimiento, indice) => (
            <li key={`${seguimiento.fecha}-${indice}`}>
              {fechaCorta(seguimiento.fecha)} ·{" "}
              {nombreDeUsuario(usuarios, seguimiento.usuario_id)}
              {seguimiento.canal ? ` · ${seguimiento.canal}` : ""}:{" "}
              {seguimiento.nota}
            </li>
          ))}
        </ul>
      )}
      {habilitado && (
        <div>
          <Campo etiqueta="Seguimiento (obligatorio)">
            <input
              value={nota}
              onChange={(evento) => setNota(evento.target.value)}
              disabled={ocupado}
              style={estiloInput}
            />
          </Campo>
          <Campo etiqueta="Canal">
            <select
              value={canal}
              onChange={(evento) => setCanal(evento.target.value)}
              disabled={ocupado}
              style={estiloInput}
            >
              <option value="">Sin indicar</option>
              {CANALES.map((opcion) => (
                <option key={opcion} value={opcion}>
                  {opcion}
                </option>
              ))}
            </select>
          </Campo>
          <Boton
            disabled={ocupado || nota.trim() === ""}
            onClick={() => {
              onRegistrar(nota.trim(), canal || null);
              setNota("");
            }}
          >
            Registrar seguimiento
          </Boton>
        </div>
      )}
    </section>
  );
}
