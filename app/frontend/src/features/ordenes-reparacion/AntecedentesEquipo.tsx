/**
 * Antecedentes del equipo (BR-REP-022): otras Órdenes con el mismo IMEI o
 * número de serie. Solo consulta: no confirma que sea el mismo equipo
 * físico (la reutilización confirmada y los equipos sin IMEI siguen
 * pendientes, ABI-05).
 */

import { useEffect, useState } from "react";

import {
  obtenerAntecedentesEquipo,
  type AntecedentesEquipo as Datos,
} from "../../api/consultas";
import { colores } from "../../components/ui";
import type { Orden } from "../../types/api";
import { ESTADO_WORKFLOW } from "./etiquetas";

export function AntecedentesEquipo({ orden }: { orden: Orden }) {
  const [datos, setDatos] = useState<Datos | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { imei, numero_serie: serie } = orden.equipo;

  useEffect(() => {
    setDatos(null);
    obtenerAntecedentesEquipo(imei, serie, orden.id)
      .then(setDatos)
      .catch((causa: unknown) =>
        setError(causa instanceof Error ? causa.message : String(causa)),
      );
  }, [imei, serie, orden.id]);

  if (error) return <p role="alert">{error}</p>;
  if (!datos) return <p style={{ fontSize: "0.85rem" }}>Buscando…</p>;
  if (datos.sin_identificacion) {
    return (
      <p style={{ margin: 0, fontSize: "0.85rem", color: colores.suave }}>
        El equipo no tiene IMEI ni número de serie registrados: no hay con qué
        buscar antecedentes.
      </p>
    );
  }
  if (datos.ordenes.length === 0) {
    return (
      <p style={{ margin: 0, fontSize: "0.85rem", color: colores.suave }}>
        No hay otras Órdenes con este IMEI o número de serie.
      </p>
    );
  }
  return (
    <ul style={{ margin: 0, paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
      {datos.ordenes.map((antecedente) => (
        <li key={antecedente.orden_id} style={{ marginBottom: "0.35rem" }}>
          <a href={`#/ordenes/${encodeURIComponent(antecedente.orden_id)}`}>
            {antecedente.orden_id}
          </a>{" "}
          ·{" "}
          {ESTADO_WORKFLOW[antecedente.estado_workflow] ??
            antecedente.estado_workflow}{" "}
          · ingresó el{" "}
          {antecedente.creada_en.slice(0, 10).split("-").reverse().join("/")}
          {antecedente.entregada_en &&
            ` · entregada el ${antecedente.entregada_en
              .slice(0, 10)
              .split("-")
              .reverse()
              .join("/")}`}
          {antecedente.orden_origen_id &&
            ` · garantía de ${antecedente.orden_origen_id}`}{" "}
          · {antecedente.falla_reportada}
          <span style={{ color: colores.suave }}>
            {" "}
            (coincide por {antecedente.coincide_por.join(" y ")};{" "}
            {antecedente.trabajos.length} trabajo
            {antecedente.trabajos.length === 1 ? "" : "s"})
          </span>
        </li>
      ))}
    </ul>
  );
}
