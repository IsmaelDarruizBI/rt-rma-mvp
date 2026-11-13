/**
 * Identidad del Equipo (DEC-MI-11).
 *
 * - Al ingresar: con el IMEI o el número de serie se buscan Equipos ya
 *   registrados (primero por IMEI, después por serie; nunca por
 *   similitud). Recepción elige uno o indica «Ninguno».
 * - En la Orden: el historial de su identidad y la corrección de una
 *   vinculación errónea, con motivo.
 */

import { useCallback, useEffect, useId, useState } from "react";

import * as api from "../../api/identidad";
import type { CandidatoEquipo, OrdenDelEquipo } from "../../api/identidad";
import { Boton, Campo, colores, estiloInput, fechaCorta } from "../../components/ui";
import { puede } from "../../lib/roles";
import type { Orden, Usuario } from "../../types/api";

const mensajeDe = (causa: unknown) =>
  causa instanceof Error ? causa.message : String(causa);

function describir(candidato: CandidatoEquipo): string {
  const modelo = [candidato.marca, candidato.modelo, candidato.variante]
    .filter(Boolean)
    .join(" ");
  const ids = [
    candidato.imei ? `IMEI ${candidato.imei}` : null,
    candidato.numero_serie ? `serie ${candidato.numero_serie}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return `${candidato.equipo_id} · ${modelo} · ${ids} · ${candidato.ordenes.length} orden(es): ${candidato.ordenes.join(", ")}`;
}

/** Selector del ingreso: `null` es «Ninguno» (identidad nueva). */
export function SelectorIdentidad({
  imei,
  numeroSerie,
  elegido,
  onElegir,
}: {
  imei: string;
  numeroSerie: string;
  elegido: string | null;
  onElegir: (equipoId: string | null) => void;
}) {
  const [resultado, setResultado] = useState<api.Identificacion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const nombre = useId();
  const hayDato = imei.trim() !== "" || numeroSerie.trim() !== "";

  // Si cambia la identificación, lo encontrado ya no vale.
  useEffect(() => {
    setResultado(null);
    onElegir(null);
  }, [imei, numeroSerie]);

  const buscar = () => {
    setError(null);
    api
      .identificarEquipo(imei.trim() || null, numeroSerie.trim() || null)
      .then(setResultado)
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  };

  return (
    <div style={{ margin: "0 0 0.6rem" }}>
      <Boton variante="secundario" disabled={!hayDato} onClick={buscar}>
        Buscar el equipo por IMEI o serie
      </Boton>
      {error && (
        <p role="alert" style={{ color: colores.error, fontSize: "0.85rem" }}>
          {error}
        </p>
      )}
      {resultado && resultado.candidatos.length === 0 && (
        <p role="status" style={{ fontSize: "0.85rem", color: colores.suave }}>
          No hay equipos registrados con ese IMEI o serie: será un equipo nuevo.
        </p>
      )}
      {resultado && resultado.candidatos.length > 0 && (
        <fieldset style={{ border: `1px solid ${colores.borde}`, borderRadius: 6, fontSize: "0.85rem" }}>
          <legend>
            Coinciden por {resultado.criterio === "IMEI" ? "IMEI" : "número de serie"}:
            elegí el equipo o «Ninguno»
          </legend>
          {resultado.candidatos.map((candidato) => (
            <label key={candidato.equipo_id} style={{ display: "flex", gap: "0.4rem" }}>
              <input
                type="radio"
                name={nombre}
                checked={elegido === candidato.equipo_id}
                onChange={() => onElegir(candidato.equipo_id)}
              />
              {describir(candidato)}
            </label>
          ))}
          <label style={{ display: "flex", gap: "0.4rem" }}>
            <input
              type="radio"
              name={nombre}
              checked={elegido === null}
              onChange={() => onElegir(null)}
            />
            Ninguno: es otro equipo
          </label>
        </fieldset>
      )}
    </div>
  );
}

const CUSTODIA: Record<OrdenDelEquipo["custodia"], string> = {
  ENTREGADO: "entregado",
  EN_LOCAL: "en el local",
  SIN_CONFIRMAR: "recepción sin confirmar",
};

/** Historial de la identidad y corrección de la vinculación. */
export function IdentidadDeLaOrden({
  orden,
  actor,
  ocupado,
  ejecutarComando,
}: {
  orden: Orden;
  actor: Usuario | null;
  ocupado: boolean;
  ejecutarComando: (comando: () => Promise<Orden>) => Promise<boolean>;
}) {
  const [historial, setHistorial] = useState<OrdenDelEquipo[]>([]);
  const [candidatos, setCandidatos] = useState<CandidatoEquipo[] | null>(null);
  const [destino, setDestino] = useState<string>("");
  const [motivo, setMotivo] = useState("");
  const [error, setError] = useState<string | null>(null);
  const habilitado =
    puede(actor, "EQUIPO_VINCULO_CORREGIR", [
      "RECEPCION",
      "COORDINADOR_RMA",
      "ADMINISTRADOR",
    ]) && orden.estado_workflow !== "ENTREGADA";

  const cargar = useCallback(() => {
    api
      .historialDelEquipo(orden.equipo.id)
      .then((datos) => setHistorial(datos.ordenes))
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, [orden.equipo.id]);
  useEffect(cargar, [cargar]);

  const buscarOtros = () => {
    api
      .identificarEquipo(orden.equipo.imei ?? null, orden.equipo.numero_serie ?? null)
      .then((datos) =>
        setCandidatos(datos.candidatos.filter((c) => c.equipo_id !== orden.equipo.id)),
      )
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  };

  const correcciones = orden.correcciones_equipo ?? [];

  return (
    <section aria-label="Identidad del equipo" style={{ marginTop: "0.8rem" }}>
      <h4 style={{ margin: "0 0 0.4rem" }}>Identidad del equipo: {orden.equipo.id}</h4>
      {error && (
        <p role="alert" style={{ color: colores.error, fontSize: "0.85rem" }}>
          {error}
        </p>
      )}
      <ul style={{ paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
        {historial.map((item) => (
          <li key={item.orden_id}>
            {item.orden_id} · {item.origen} · {item.estado_workflow} · ingresó{" "}
            {fechaCorta(item.creada_en)}
            {item.orden_origen_id ? ` · garantía de ${item.orden_origen_id}` : ""} ·{" "}
            {item.trabajos.length} trabajo(s) · {CUSTODIA[item.custodia]}
          </li>
        ))}
      </ul>
      {correcciones.length > 0 && (
        <p style={{ fontSize: "0.8rem", color: colores.suave }}>
          Vinculación corregida:{" "}
          {correcciones
            .map(
              (c) =>
                `${fechaCorta(c.fecha)} de ${c.equipo_anterior_id} a ${c.equipo_nuevo_id} (${c.motivo})`,
            )
            .join("; ")}
        </p>
      )}
      {habilitado && (
        <details style={{ fontSize: "0.85rem" }}>
          <summary>Corregir la vinculación con el equipo</summary>
          <div style={{ maxWidth: 520, marginTop: "0.4rem" }}>
            {candidatos === null ? (
              <Boton variante="secundario" onClick={buscarOtros}>
                Buscar equipos con el mismo IMEI o serie
              </Boton>
            ) : (
              <Campo etiqueta="Vincular a">
                <select
                  value={destino}
                  onChange={(e) => setDestino(e.target.value)}
                  disabled={ocupado}
                  style={estiloInput}
                >
                  <option value="">Ninguno: es otro equipo (identidad nueva)</option>
                  {candidatos.map((c) => (
                    <option key={c.equipo_id} value={c.equipo_id}>
                      {describir(c)}
                    </option>
                  ))}
                </select>
              </Campo>
            )}
            <Campo etiqueta="Motivo (obligatorio)">
              <input
                value={motivo}
                onChange={(e) => setMotivo(e.target.value)}
                disabled={ocupado}
                style={estiloInput}
              />
            </Campo>
            <Boton
              disabled={ocupado || candidatos === null || motivo.trim() === ""}
              onClick={() =>
                void ejecutarComando(() =>
                  api.corregirVinculoEquipo(
                    orden.id,
                    actor?.id ?? "",
                    destino || null,
                    motivo.trim(),
                  ),
                ).then((hecho) => {
                  if (hecho) {
                    setMotivo("");
                    setCandidatos(null);
                    setDestino("");
                  }
                })
              }
            >
              Corregir la vinculación
            </Boton>
          </div>
        </details>
      )}
    </section>
  );
}
