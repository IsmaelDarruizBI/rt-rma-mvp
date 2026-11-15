/**
 * Checklist de recepción (DC12) y advertencia por información faltante
 * (BR-REP-025).
 *
 * - Recepción elige el tipo de equipo entre los del catálogo de Ventas de
 *   Gestión RT (copia de solo lectura) y responde lo que quiera: todas las
 *   verificaciones son opcionales y pueden quedar «no realizadas».
 * - La Orden conserva el identificador y la descripción del tipo elegido.
 * - Lo registrado guarda la copia de las preguntas; corregirlo agrega una
 *   versión con motivo (la anterior se conserva).
 * - La advertencia nunca bloquea: se puede completar lo que falta o
 *   continuar igualmente, y esa confirmación queda registrada.
 */

import { useEffect, useState } from "react";

import * as api from "../../api/checklist";
import type { CatalogoChecklist, RegistroChecklist } from "../../api/checklist";
import { Boton, Campo, colores, estiloInput, fechaCorta } from "../../components/ui";
import { puede } from "../../lib/roles";
import type { Orden, Usuario } from "../../types/api";
import {
  NO_REALIZADA,
  motivoSinChecklist,
  preguntasDelTipo,
  puedeRegistrarChecklist,
  respuestasParaEnviar,
  tipoPropuesto,
} from "./checklist";

const QUIENES = ["RECEPCION", "COORDINADOR_RMA", "ADMINISTRADOR"];

type OrdenConChecklist = Orden & {
  checklists_recepcion?: RegistroChecklist[];
  informacion_faltante?: string[];
  tipo_equipo?: { id: string; descripcion: string } | null;
};

export function AdvertenciaFaltante({
  orden,
  actor,
  ocupado,
  ejecutarComando,
}: {
  orden: OrdenConChecklist;
  actor: Usuario | null;
  ocupado: boolean;
  ejecutarComando: (comando: () => Promise<Orden>) => Promise<boolean>;
}) {
  const faltantes = orden.informacion_faltante ?? [];
  if (faltantes.length === 0) return null;
  const habilitado = puede(actor, "CHECKLIST_REGISTRAR", QUIENES);
  return (
    <div
      role="status"
      style={{
        margin: "0 0 0.8rem",
        padding: "0.5rem 0.7rem",
        borderRadius: 6,
        border: `1px solid ${colores.alerta}`,
        background: "#fff8e6",
        fontSize: "0.85rem",
      }}
    >
      Falta registrar: {faltantes.join(", ")}. Podés completarlo (Cliente y
      equipo, Fotos) o continuar igualmente: no bloquea.{" "}
      {habilitado && (
        <Boton
          variante="secundario"
          disabled={ocupado}
          onClick={() =>
            void ejecutarComando(() => api.confirmarFaltantes(orden.id, actor?.id ?? ""))
          }
        >
          Continuar igualmente
        </Boton>
      )}
    </div>
  );
}

export function ChecklistRecepcion({
  orden,
  actor,
  ocupado,
  ejecutarComando,
}: {
  orden: OrdenConChecklist;
  actor: Usuario | null;
  ocupado: boolean;
  ejecutarComando: (comando: () => Promise<Orden>) => Promise<boolean>;
}) {
  const [catalogo, setCatalogo] = useState<CatalogoChecklist | null>(null);
  const [cargando, setCargando] = useState(true);
  const [tipo, setTipo] = useState("");
  const [respuestas, setRespuestas] = useState<Record<string, string>>({});
  const [motivo, setMotivo] = useState("");
  const [editando, setEditando] = useState(false);
  const registros = orden.checklists_recepcion ?? [];
  const vigente = registros[registros.length - 1] ?? null;
  const habilitado =
    puede(actor, "CHECKLIST_REGISTRAR", QUIENES) &&
    orden.estado_workflow !== "ENTREGADA";

  useEffect(() => {
    api
      .catalogo()
      .then(setCatalogo)
      .catch(() => setCatalogo(null))
      .finally(() => setCargando(false));
  }, []);

  const preguntas = preguntasDelTipo(catalogo, tipo);
  const sinChecklist = cargando ? null : motivoSinChecklist(catalogo);
  const tiposVigentes = (catalogo?.tipos ?? []).filter((t) => t.activo);

  return (
    <section aria-label="Checklist de recepción" style={{ marginTop: "0.8rem" }}>
      <h4 style={{ margin: "0 0 0.4rem" }}>Checklist de recepción (opcional)</h4>
      {vigente ? (
        <div style={{ fontSize: "0.85rem", marginBottom: "0.4rem" }}>
          Tipo de equipo: {vigente.tipo_equipo_nombre} ({vigente.tipo_equipo_id}) ·{" "}
          {fechaCorta(vigente.fecha)} · {vigente.usuario_id}
          {registros.length > 1 ? ` · versión ${registros.length} (${vigente.motivo})` : ""}
          <ul style={{ margin: "0.2rem 0", paddingLeft: "1.1rem" }}>
            {vigente.respuestas.map((r) => (
              <li key={r.pregunta_id}>
                {r.texto}: {r.no_realizada ? "no realizada" : r.respuesta}
              </li>
            ))}
            {vigente.sin_registrar.map((texto) => (
              <li key={texto} style={{ color: colores.suave }}>
                {texto}: sin registrar
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p style={{ margin: "0 0 0.4rem", fontSize: "0.85rem", color: colores.suave }}>
          Sin checklist registrado.
        </p>
      )}
      {cargando && <p style={{ fontSize: "0.8rem", color: colores.suave }}>Cargando el catálogo…</p>}
      {sinChecklist && (
        <p style={{ fontSize: "0.8rem", color: colores.suave }}>{sinChecklist}</p>
      )}
      {habilitado && !sinChecklist && !cargando && !editando && (
        <Boton
          variante="secundario"
          disabled={ocupado}
          onClick={() => {
            setTipo(tipoPropuesto(catalogo?.tipos ?? [], orden.tipo_equipo));
            setRespuestas({});
            setEditando(true);
          }}
        >
          {vigente ? "Corregir el checklist" : "Completar el checklist"}
        </Boton>
      )}
      {editando && catalogo && (
        <div style={{ maxWidth: 520 }}>
          <Campo etiqueta="Tipo de equipo">
            <select
              value={tipo}
              onChange={(e) => {
                setTipo(e.target.value);
                setRespuestas({});
              }}
              style={estiloInput}
            >
              <option value="">Elegir…</option>
              {tiposVigentes.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.nombre}
                </option>
              ))}
            </select>
          </Campo>
          {preguntas.map((p) => (
            <Campo key={p.id} etiqueta={p.texto}>
              <select
                value={respuestas[p.id] ?? ""}
                onChange={(e) => setRespuestas({ ...respuestas, [p.id]: e.target.value })}
                style={estiloInput}
              >
                <option value="">Sin registrar</option>
                {p.opciones.map((o) => (
                  <option key={o} value={`R:${o}`}>
                    {o}
                  </option>
                ))}
                <option value={NO_REALIZADA}>No realizada</option>
              </select>
            </Campo>
          ))}
          {vigente && (
            <Campo etiqueta="Motivo de la corrección (obligatorio)">
              <input value={motivo} onChange={(e) => setMotivo(e.target.value)} style={estiloInput} />
            </Campo>
          )}
          <div style={{ display: "flex", gap: "0.4rem" }}>
            <Boton
              disabled={ocupado || !puedeRegistrarChecklist(tipo, vigente !== null, motivo)}
              onClick={() =>
                void ejecutarComando(() =>
                  api.registrar(orden.id, {
                    usuario_id: actor?.id ?? "",
                    tipo_equipo_id: tipo,
                    respuestas: respuestasParaEnviar(respuestas),
                    motivo: motivo.trim() || null,
                  }),
                ).then((ok) => {
                  if (ok) {
                    setEditando(false);
                    setMotivo("");
                  }
                })
              }
            >
              Registrar el checklist
            </Boton>
            <Boton variante="secundario" disabled={ocupado} onClick={() => setEditando(false)}>
              Cancelar
            </Boton>
          </div>
        </div>
      )}
    </section>
  );
}
