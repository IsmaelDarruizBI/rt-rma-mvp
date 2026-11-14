/**
 * Checklist de recepción por tipo de equipo (DC12): Administración define los
 * tipos de equipo y, para cada uno, sus preguntas con opciones. Empieza
 * vacío: el sistema no trae una clasificación. Todo queda auditado; lo ya
 * registrado en las Órdenes no cambia. Solo sobre PostgreSQL.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/checklist";
import type { CatalogoChecklist, PreguntaChecklist } from "../../api/checklist";
import { Boton, Campo, colores, estiloInput } from "../../components/ui";
import type { Usuario } from "../../types/api";

const mensaje = (causa: unknown) =>
  causa instanceof Error ? causa.message : String(causa);

export function ChecklistAdmin({ actor }: { actor: Usuario }) {
  const [datos, setDatos] = useState<CatalogoChecklist | null>(null);
  const [nombreTipo, setNombreTipo] = useState("");
  const [tipo, setTipo] = useState("");
  const [texto, setTexto] = useState("");
  const [opciones, setOpciones] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(() => {
    api
      .catalogoAdmin()
      .then(setDatos)
      .catch((causa: unknown) => setError(mensaje(causa)));
  }, []);
  useEffect(cargar, [cargar]);

  const ejecutar = (accion: () => Promise<unknown>, exito: string) => {
    setOcupado(true);
    setError(null);
    setAviso(null);
    return accion()
      .then(() => {
        setAviso(exito);
        cargar();
        return true;
      })
      .catch((causa: unknown) => {
        setError(mensaje(causa));
        return false;
      })
      .finally(() => setOcupado(false));
  };

  if (!datos) return error ? <p role="alert">{error}</p> : null;
  if (!datos.editable) {
    return (
      <p style={{ color: colores.suave }}>
        El checklist se administra sobre la base PostgreSQL.
      </p>
    );
  }
  const preguntas = datos.preguntas.filter((p) => p.tipo_equipo_id === tipo);
  const listaOpciones = opciones
    .split(",")
    .map((o) => o.trim())
    .filter(Boolean);

  const cambiarPregunta = (p: PreguntaChecklist, cambio: Partial<PreguntaChecklist>) =>
    ejecutar(() => api.guardarPregunta(actor.id, { ...p, ...cambio }), `Se guardó «${p.texto}».`);

  return (
    <section>
      <h3 style={{ margin: "0 0 0.5rem" }}>Checklist de recepción por tipo de equipo</h3>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Todas las verificaciones son opcionales y pueden registrarse como no
        realizadas. Recepción elige el tipo de equipo al completar el checklist.
      </p>
      {error && (
        <p role="alert" style={{ color: colores.error, fontSize: "0.85rem" }}>
          {error}
        </p>
      )}
      {aviso && (
        <p role="status" style={{ color: colores.ok, fontSize: "0.85rem" }}>
          {aviso}
        </p>
      )}
      <h4 style={{ margin: "0 0 0.3rem" }}>Tipos de equipo</h4>
      <ul style={{ paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
        {datos.tipos.map((t) => (
          <li key={t.id}>
            <button
              type="button"
              onClick={() => setTipo(t.id)}
              style={{ background: "none", border: "none", color: colores.acento, cursor: "pointer", padding: 0 }}
            >
              {t.nombre}
            </button>{" "}
            ({t.id}
            {t.activo ? "" : " · no vigente"}){" "}
            <label style={{ fontSize: "0.8rem" }}>
              <input
                type="checkbox"
                checked={t.activo}
                disabled={ocupado}
                onChange={(e) =>
                  void ejecutar(
                    () => api.guardarTipo(actor.id, { ...t, activo: e.target.checked }),
                    `Se guardó ${t.nombre}.`,
                  )
                }
              />{" "}
              vigente
            </label>
          </li>
        ))}
        {datos.tipos.length === 0 && <li style={{ color: colores.suave }}>Sin tipos de equipo.</li>}
      </ul>
      <div style={{ display: "flex", gap: "0.4rem", alignItems: "end", maxWidth: 420 }}>
        <Campo etiqueta="Nuevo tipo de equipo">
          <input value={nombreTipo} onChange={(e) => setNombreTipo(e.target.value)} style={estiloInput} />
        </Campo>
        <Boton
          disabled={ocupado || !nombreTipo.trim()}
          onClick={() =>
            void ejecutar(
              () => api.guardarTipo(actor.id, { nombre: nombreTipo.trim(), activo: true }),
              `Se agregó ${nombreTipo.trim()}.`,
            ).then((ok) => ok && setNombreTipo(""))
          }
        >
          Agregar
        </Boton>
      </div>

      {tipo && (
        <div style={{ marginTop: "0.8rem" }}>
          <h4 style={{ margin: "0 0 0.3rem" }}>
            Preguntas de {datos.tipos.find((t) => t.id === tipo)?.nombre}
          </h4>
          <ul style={{ paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
            {preguntas.map((p) => (
              <li key={p.id}>
                {p.texto} — {p.opciones.join(" / ")}
                {p.activa ? "" : " · no vigente"}{" "}
                <label style={{ fontSize: "0.8rem" }}>
                  <input
                    type="checkbox"
                    checked={p.activa}
                    disabled={ocupado}
                    onChange={(e) => void cambiarPregunta(p, { activa: e.target.checked })}
                  />{" "}
                  vigente
                </label>
              </li>
            ))}
            {preguntas.length === 0 && <li style={{ color: colores.suave }}>Sin preguntas.</li>}
          </ul>
          <div style={{ maxWidth: 420 }}>
            <Campo etiqueta="Nueva pregunta">
              <input value={texto} onChange={(e) => setTexto(e.target.value)} style={estiloInput} />
            </Campo>
            <Campo etiqueta="Opciones (separadas por coma; al menos dos)">
              <input value={opciones} onChange={(e) => setOpciones(e.target.value)} style={estiloInput} />
            </Campo>
            <Boton
              disabled={ocupado || !texto.trim() || listaOpciones.length < 2}
              onClick={() =>
                void ejecutar(
                  () =>
                    api.guardarPregunta(actor.id, {
                      tipo_equipo_id: tipo,
                      texto: texto.trim(),
                      opciones: listaOpciones,
                      activa: true,
                      orden: preguntas.length + 1,
                    }),
                  "Se agregó la pregunta.",
                ).then((ok) => {
                  if (ok) {
                    setTexto("");
                    setOpciones("");
                  }
                })
              }
            >
              Agregar pregunta
            </Boton>
          </div>
        </div>
      )}
    </section>
  );
}
