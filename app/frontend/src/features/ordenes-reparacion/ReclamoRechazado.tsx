/**
 * Reclamo de garantía rechazado (DEC-MI-02): quedó registrado y, si la
 * persona puede, se continúa como reparación paga de cliente externo con el
 * mismo cliente y equipo. Pide confirmar; la API impide duplicarla.
 */

import { useState } from "react";

import { continuarReclamo } from "../../api/reclamos";
import { Boton, Campo, colores, estiloInput } from "../../components/ui";
import { puede } from "../../lib/roles";
import type { Orden, Usuario } from "../../types/api";

export function ReclamoRechazado({
  reclamoId,
  origen,
  actor,
  onContinuada,
  onCerrar,
}: {
  reclamoId: string;
  origen: Orden | null;
  actor: Usuario | null;
  onContinuada: (ordenId: string) => void;
  onCerrar: () => void;
}) {
  const [confirmando, setConfirmando] = useState(false);
  const [falla, setFalla] = useState(origen?.equipo.falla_reportada ?? "");
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const habilitado = puede(actor, "RECLAMO_CONTINUAR", ["RECEPCION"]);

  const confirmar = () => {
    if (!actor) return;
    setOcupado(true);
    setError(null);
    continuarReclamo(reclamoId, actor.id, falla.trim() || null)
      .then((r) => onContinuada(r.orden_id))
      .catch((causa: unknown) =>
        setError(causa instanceof Error ? causa.message : String(causa)),
      )
      .finally(() => setOcupado(false));
  };

  return (
    <div
      role="status"
      style={{
        margin: "0.6rem 0",
        padding: "0.7rem 0.9rem",
        border: `1px solid ${colores.alerta}`,
        borderRadius: 8,
      }}
    >
      <p style={{ margin: "0 0 0.4rem" }}>
        Se registró el reclamo de garantía rechazado <strong>{reclamoId}</strong>.
        La Orden original no cambia.
      </p>
      {habilitado && !confirmando && (
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <Boton onClick={() => setConfirmando(true)}>
            Continuar como reparación paga…
          </Boton>
          <Boton variante="secundario" onClick={onCerrar}>
            Cerrar
          </Boton>
        </div>
      )}
      {habilitado && confirmando && (
        <div style={{ display: "grid", gap: "0.4rem", maxWidth: 520 }}>
          <p style={{ margin: 0, fontSize: "0.85rem" }}>
            Se crea una Orden nueva de cliente externo, cobrable, para{" "}
            <strong>{origen?.cliente?.nombre_apellido ?? "el mismo cliente"}</strong>{" "}
            y el equipo{" "}
            <strong>
              {origen ? `${origen.equipo.marca} ${origen.equipo.modelo}` : "del reclamo"}
            </strong>
            , vinculada a {reclamoId}.
          </p>
          <Campo etiqueta="Falla declarada">
            <input
              value={falla}
              onChange={(e) => setFalla(e.target.value)}
              style={estiloInput}
            />
          </Campo>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <Boton disabled={ocupado} onClick={confirmar}>
              Confirmar y crear la Orden paga
            </Boton>
            <Boton variante="secundario" onClick={() => setConfirmando(false)}>
              Volver
            </Boton>
          </div>
        </div>
      )}
      {!habilitado && (
        <p style={{ margin: 0, fontSize: "0.85rem", color: colores.suave }}>
          Recepción puede continuarlo como reparación paga.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
