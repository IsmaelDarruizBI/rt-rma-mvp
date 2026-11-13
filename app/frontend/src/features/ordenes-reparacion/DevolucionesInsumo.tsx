/**
 * Devolución al stock (DEC-MI-10): el insumo utilizable que se consumió en
 * la Orden vuelve al stock, al mismo lote, sin superar lo consumido menos lo
 * ya devuelto. Con la Orden abierta; por defecto Administración y
 * Coordinación (permiso configurable).
 */

import { useState } from "react";

import { post } from "../../api/client";
import { Boton, Campo, colores, estiloInput, fechaCorta } from "../../components/ui";
import { puede } from "../../lib/roles";
import type { Orden, Usuario } from "../../types/api";

export interface ConsumoInsumo {
  id: string;
  insumo_id: string;
  detalle_id: string;
  ejecucion_id: string | null;
  cantidad: string;
  devuelto: string;
  lote_id: string | null;
  fecha: string;
}

export function DevolucionesInsumo({
  orden,
  actor,
  ocupado,
  ejecutarComando,
}: {
  orden: Orden & { consumos_insumo?: ConsumoInsumo[] };
  actor: Usuario | null;
  ocupado: boolean;
  ejecutarComando: (comando: () => Promise<Orden>) => Promise<boolean>;
}) {
  const consumos = orden.consumos_insumo ?? [];
  const habilitado =
    puede(actor, "DEVOLUCION_STOCK", ["ADMINISTRADOR", "COORDINADOR_RMA"]) &&
    orden.estado_workflow !== "ENTREGADA";
  if (consumos.length === 0) return null;
  return (
    <section aria-label="Consumos y devoluciones" style={{ marginTop: "0.8rem" }}>
      <h4 style={{ margin: "0 0 0.4rem" }}>Consumos y devoluciones al stock</h4>
      <ul style={{ paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
        {consumos.map((consumo) => (
          <FilaConsumo
            key={consumo.id}
            consumo={consumo}
            habilitado={habilitado}
            ocupado={ocupado}
            onDevolver={(cantidad, motivo) =>
              ejecutarComando(() =>
                post<Orden>(
                  `/api/orders/${orden.id}/consumptions/${encodeURIComponent(consumo.id)}/return`,
                  { usuario_id: actor?.id ?? "", cantidad, motivo },
                ),
              )
            }
          />
        ))}
      </ul>
    </section>
  );
}

function FilaConsumo({
  consumo,
  habilitado,
  ocupado,
  onDevolver,
}: {
  consumo: ConsumoInsumo;
  habilitado: boolean;
  ocupado: boolean;
  onDevolver: (cantidad: string, motivo: string) => Promise<boolean>;
}) {
  const [abierta, setAbierta] = useState(false);
  const [cantidad, setCantidad] = useState("");
  const [motivo, setMotivo] = useState("");
  const pendiente = Number(consumo.cantidad) - Number(consumo.devuelto);
  const numero = Number(cantidad);
  const valida = numero > 0 && numero <= pendiente && motivo.trim() !== "";
  return (
    <li style={{ marginBottom: "0.4rem" }}>
      {consumo.insumo_id} · {consumo.detalle_id} · consumido {consumo.cantidad}
      {Number(consumo.devuelto) > 0 ? ` · devuelto ${consumo.devuelto}` : ""}
      {consumo.lote_id ? ` · lote ${consumo.lote_id}` : ""}
      <span style={{ color: colores.suave }}> · {fechaCorta(consumo.fecha)}</span>
      {habilitado && pendiente > 0 && !abierta && (
        <>
          {" "}
          <Boton variante="secundario" disabled={ocupado} onClick={() => setAbierta(true)}>
            Devolver al stock
          </Boton>
        </>
      )}
      {abierta && (
        <div style={{ maxWidth: 360, marginTop: "0.3rem" }}>
          <Campo etiqueta={`Cantidad (hasta ${pendiente})`}>
            <input
              value={cantidad}
              inputMode="decimal"
              onChange={(e) => setCantidad(e.target.value)}
              disabled={ocupado}
              style={estiloInput}
            />
          </Campo>
          <Campo etiqueta="Motivo (obligatorio)">
            <input
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
              disabled={ocupado}
              style={estiloInput}
            />
          </Campo>
          <div style={{ display: "flex", gap: "0.4rem" }}>
            <Boton
              disabled={ocupado || !valida}
              onClick={() =>
                void onDevolver(cantidad.trim(), motivo.trim()).then((hecho) => {
                  if (hecho) {
                    setAbierta(false);
                    setCantidad("");
                    setMotivo("");
                  }
                })
              }
            >
              Devolver
            </Boton>
            <Boton variante="secundario" disabled={ocupado} onClick={() => setAbierta(false)}>
              Cancelar
            </Boton>
          </div>
        </div>
      )}
    </li>
  );
}
