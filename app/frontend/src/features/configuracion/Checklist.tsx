/**
 * Checklist de recepción por tipo de equipo (DC12). Los tipos de equipo
 * vienen del catálogo de Ventas de Gestión RT: acá solo se ven (con su
 * origen y su última actualización) y se actualiza la copia; no se crean
 * ni se editan. Administración configura las preguntas de cada tipo, su
 * vigencia y su orden. Todo queda auditado; lo ya registrado en las
 * Órdenes no cambia. Solo sobre PostgreSQL.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/checklist";
import type { CatalogoChecklist, PreguntaChecklist } from "../../api/checklist";
import { Boton, Campo, colores, estiloInput } from "../../components/ui";
import type { Usuario } from "../../types/api";
import {
  moverPregunta,
  preguntasDelTipo,
  textoOrigen,
} from "../ordenes-reparacion/checklist";

const mensaje = (causa: unknown) =>
  causa instanceof Error ? causa.message : String(causa);

export function ChecklistAdmin({ actor }: { actor: Usuario }) {
  const [datos, setDatos] = useState<CatalogoChecklist | null>(null);
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

  const ejecutar = (accion: () => Promise<unknown>, exito: string | ((r: unknown) => string)) => {
    setOcupado(true);
    setError(null);
    setAviso(null);
    return accion()
      .then((resultado) => {
        setAviso(typeof exito === "function" ? exito(resultado) : exito);
        cargar();
        return true;
      })
      .catch((causa: unknown) => {
        setError(mensaje(causa));
        return false;
      })
      .finally(() => setOcupado(false));
  };

  if (!datos) return error ? <p role="alert">{error}</p> : <p>Cargando…</p>;
  if (!datos.editable) {
    return (
      <p style={{ color: colores.suave }}>
        El checklist se administra sobre la base PostgreSQL.
      </p>
    );
  }
  // Las de todos los estados, para administrar (también las no vigentes).
  const preguntas = [...datos.preguntas]
    .filter((p) => p.tipo_equipo_id === tipo)
    .sort((a, b) => a.orden - b.orden || a.id.localeCompare(b.id));
  const vigentes = preguntasDelTipo(datos, tipo);
  const listaOpciones = opciones
    .split(",")
    .map((o) => o.trim())
    .filter(Boolean);
  const origen = datos.origen;

  const cambiarPregunta = (p: PreguntaChecklist, cambio: Partial<PreguntaChecklist>) =>
    ejecutar(() => api.guardarPregunta(actor.id, { ...p, ...cambio }), `Se guardó «${p.texto}».`);

  const mover = (p: PreguntaChecklist, sentido: -1 | 1) => {
    const cambios = moverPregunta(preguntas, p.id, sentido);
    if (cambios.length === 0) return;
    void ejecutar(async () => {
      for (const c of cambios) await api.guardarPregunta(actor.id, c);
    }, "Se guardó el orden.");
  };

  return (
    <section>
      <h3 style={{ margin: "0 0 0.5rem" }}>Checklist de recepción por tipo de equipo</h3>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Los tipos de equipo vienen del catálogo de Ventas de Gestión RT y no se
        editan desde RMA. Las verificaciones son opcionales y pueden registrarse
        como no realizadas.
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
      <p style={{ margin: "0 0 0.3rem", fontSize: "0.8rem" }}>{textoOrigen(origen)}</p>
      <Boton
        variante="secundario"
        disabled={ocupado || !origen?.sincronizable}
        onClick={() =>
          void ejecutar(
            () => api.sincronizarTipos(actor.id),
            (r) => {
              const x = r as api.ResultadoSincronizacionTipos;
              return `Tipos actualizados: ${x.vigentes} vigentes (${x.nuevos} nuevos, ${x.reactivados} reactivados, ${x.dados_de_baja} dados de baja).`;
            },
          )
        }
      >
        Actualizar desde el catálogo de Ventas
      </Boton>
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
            {t.activo ? "" : " · ya no está en el catálogo"})
          </li>
        ))}
        {datos.tipos.length === 0 && <li style={{ color: colores.suave }}>Sin tipos de equipo.</li>}
      </ul>

      {tipo && (
        <div style={{ marginTop: "0.8rem" }}>
          <h4 style={{ margin: "0 0 0.3rem" }}>
            Preguntas de {datos.tipos.find((t) => t.id === tipo)?.nombre} ({vigentes.length} vigentes)
          </h4>
          <ul style={{ paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
            {preguntas.map((p, i) => (
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
                </label>{" "}
                <button
                  type="button"
                  aria-label={`Subir ${p.texto}`}
                  disabled={ocupado || i === 0}
                  onClick={() => mover(p, -1)}
                >
                  ↑
                </button>
                <button
                  type="button"
                  aria-label={`Bajar ${p.texto}`}
                  disabled={ocupado || i === preguntas.length - 1}
                  onClick={() => mover(p, 1)}
                >
                  ↓
                </button>
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
