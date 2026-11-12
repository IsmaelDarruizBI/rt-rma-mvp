/**
 * Reporte operativo, primera versión (macroiteración V1.4, módulo K).
 *
 * Solo métricas calculables con el modelo existente: Órdenes por estado y
 * origen, trabajos por técnico, tiempos por estación, pendientes por
 * antigüedad, reprocesos y garantías, consumo de insumos y cobros. No
 * define umbrales («demorada») ni políticas: informa días abierta y días
 * sin movimiento. Solo lectura.
 */

import { useEffect, useState } from "react";

import { obtenerReporteOperativo } from "../../api/consultas";
import type { ReporteOperativo } from "../../api/consultas";
import { colores, importe } from "../../components/ui";
import { ESTADO_WORKFLOW, ORIGEN } from "../ordenes-reparacion/etiquetas";

function Tabla({
  titulo,
  columnas,
  filas,
}: {
  titulo: string;
  columnas: string[];
  filas: (string | number)[][];
}) {
  return (
    <section style={{ marginBottom: "1.2rem" }}>
      <h3 style={{ margin: "0 0 0.4rem", fontSize: "0.95rem" }}>{titulo}</h3>
      {filas.length === 0 ? (
        <p style={{ margin: 0, fontSize: "0.85rem", color: colores.suave }}>
          Sin datos.
        </p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", fontSize: "0.85rem" }}>
            <thead>
              <tr>
                {columnas.map((columna) => (
                  <th
                    key={columna}
                    style={{
                      textAlign: "left",
                      padding: "0.25rem 0.6rem",
                      borderBottom: `1px solid ${colores.borde}`,
                    }}
                  >
                    {columna}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filas.map((fila, i) => (
                <tr key={i}>
                  {fila.map((celda, j) => (
                    <td key={j} style={{ padding: "0.25rem 0.6rem" }}>
                      {celda}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function ReportesPanel() {
  const [reporte, setReporte] = useState<ReporteOperativo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    obtenerReporteOperativo()
      .then(setReporte)
      .catch((causa: unknown) =>
        setError(causa instanceof Error ? causa.message : String(causa)),
      );
  }, []);

  if (error) return <p role="alert">{error}</p>;
  if (!reporte) return <p>Cargando el reporte…</p>;

  const pares = (
    registro: Record<string, number | string>,
    nombres: Record<string, string> = {},
  ) =>
    Object.entries(registro).map(([clave, valor]) => [
      nombres[clave] ?? clave,
      valor,
    ]);

  return (
    <div>
      <p style={{ margin: "0 0 1rem", fontSize: "0.8rem", color: colores.suave }}>
        Calculado con los datos registrados. Primera versión: sin umbrales de
        demora ni proyecciones.
      </p>
      <Tabla
        titulo="Órdenes por estado"
        columnas={["Estado", "Órdenes"]}
        filas={pares(reporte.ordenes_por_estado, ESTADO_WORKFLOW)}
      />
      <Tabla
        titulo="Órdenes por origen"
        columnas={["Origen", "Órdenes"]}
        filas={pares(reporte.ordenes_por_origen, ORIGEN)}
      />
      <Tabla
        titulo="Trabajos por técnico"
        columnas={["Técnico", "Completadas", "Interrumpidas", "Puntaje"]}
        filas={reporte.trabajos_por_tecnico.map((t) => [
          t.usuario_id,
          t.completadas,
          t.interrumpidas,
          t.puntaje,
        ])}
      />
      <Tabla
        titulo="Tiempos de ejecución por estación"
        columnas={["Estación", "Ejecuciones", "Horas totales", "Horas promedio"]}
        filas={reporte.tiempos_por_estacion.map((e) => [
          e.estacion_id,
          e.ejecuciones,
          e.horas_totales,
          e.horas_promedio,
        ])}
      />
      <Tabla
        titulo="Órdenes abiertas, de la más antigua a la más nueva"
        columnas={["Orden", "Estado", "Origen", "Días abierta", "Días sin movimiento"]}
        filas={reporte.pendientes.map((p) => [
          p.orden_id,
          ESTADO_WORKFLOW[p.estado_workflow] ?? p.estado_workflow,
          ORIGEN[p.origen] ?? p.origen,
          p.dias_abierta,
          p.dias_sin_movimiento,
        ])}
      />
      <Tabla
        titulo="Reprocesos y garantías"
        columnas={["Indicador", "Cantidad"]}
        filas={pares(reporte.reprocesos, {
          controles_rechazados: "Controles rechazados",
          redefiniciones: "Redefiniciones",
          descartes_tecnicos: "Descartes técnicos",
          garantias_rma: "Órdenes de garantía RMA",
          excepciones_de_garantia: "Excepciones de garantía vencida",
        })}
      />
      <Tabla
        titulo="Consumo de insumos"
        columnas={["Insumo", "Cantidad consumida"]}
        filas={reporte.consumo_insumos.map((c) => [c.insumo_id, c.cantidad])}
      />
      <Tabla
        titulo="Cobros y saldos"
        columnas={["Concepto", "Importe"]}
        filas={[
          ["Cobrado", importe(reporte.cobros.cobrado)],
          ["Devuelto", importe(reporte.cobros.devuelto)],
          [
            "Saldo pendiente (Órdenes abiertas)",
            importe(reporte.cobros.saldo_pendiente_ordenes_abiertas),
          ],
          [
            "Crédito a favor por devolver",
            importe(reporte.cobros.credito_a_favor_pendiente),
          ],
        ]}
      />
    </div>
  );
}
