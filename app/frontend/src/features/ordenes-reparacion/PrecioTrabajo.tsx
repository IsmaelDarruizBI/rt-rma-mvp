/**
 * Precio de un trabajo según el modelo del equipo (DEC-AJ-12).
 *
 * - `CamposPrecioManual`: en los selectores de trabajo, cuando el Tipo no
 *   tiene precio para el modelo de la Orden. Con PRECIO_MANUAL pide precio
 *   y motivo; sin él avisa que el trabajo quedará con el precio pendiente.
 * - `FormularioDefinirPrecio`: «Definir precio» de un trabajo pendiente:
 *   tomar el precio de catálogo (si ya existe) o, con el permiso, uno
 *   manual con motivo.
 * - `MarcaPrecio`: «Precio manual» o «Precio pendiente» junto al trabajo.
 *
 * La lógica está en `precioModelo.ts`; la API valida todo de nuevo.
 */

import { useState } from "react";

import { Boton, Campo, colores, Etiqueta, estiloInput, importe } from "../../components/ui";
import { puede } from "../../lib/roles";
import type { Detalle, TipoReparacion, Usuario } from "../../types/api";
import {
  PERMISO_PRECIO_MANUAL,
  SIN_MANUAL,
  etiquetaOrigenPrecio,
  pedidoPrecioManual,
  precioDelTipo,
  textoPrecioDelTipo,
  type EstadoPrecioManual,
  type PedidoPrecioManual,
} from "./precioModelo";

const POR_DEFECTO = ["COORDINADOR_RMA", "ADMINISTRADOR"];

export function puedePrecioManual(actor: Usuario | null): boolean {
  return puede(actor, PERMISO_PRECIO_MANUAL, POR_DEFECTO);
}

/** «Cambio de batería — $ 60.000» o «… — Sin precio para este modelo». */
export function opcionDeTipo(tipo: TipoReparacion, modeloId: string | null | undefined): string {
  return `${tipo.nombre} — ${textoPrecioDelTipo(tipo, modeloId, importe)}`;
}

/** El estado del pedido manual de un formulario y lo que se enviaría. */
export function usePrecioManual(
  tipo: TipoReparacion | undefined,
  modeloId: string | null | undefined,
  actor: Usuario | null,
) {
  const [estado, setEstado] = useState<EstadoPrecioManual>(SIN_MANUAL);
  const resultado = pedidoPrecioManual(tipo, modeloId, puedePrecioManual(actor), estado);
  return {
    estado,
    setEstado,
    pedido: resultado.pedido,
    error: resultado.error,
    reiniciar: () => setEstado(SIN_MANUAL),
  };
}

export function CamposPrecioManual({
  tipo,
  modeloId,
  actor,
  estado,
  onCambio,
  error,
  deshabilitado,
}: {
  tipo: TipoReparacion | undefined;
  modeloId: string | null | undefined;
  actor: Usuario | null;
  estado: EstadoPrecioManual;
  onCambio: (estado: EstadoPrecioManual) => void;
  error: string | null;
  deshabilitado: boolean;
}) {
  if (!tipo || precioDelTipo(tipo, modeloId).precio !== null) return null;
  const conPermiso = puedePrecioManual(actor);
  return (
    <div
      role="note"
      style={{
        margin: "0 0 0.6rem",
        padding: "0.5rem",
        border: `1px solid ${colores.alerta}`,
        borderRadius: 6,
        fontSize: "0.85rem",
      }}
    >
      <strong style={{ color: colores.alerta }}>
        {modeloId
          ? "Falta el precio de catálogo de este trabajo para el modelo del equipo."
          : "El equipo no tiene un modelo del catálogo: este trabajo no tiene precio de catálogo."}
      </strong>
      {conPermiso ? (
        <>
          <p style={{ margin: "0.3rem 0" }}>
            Podés cargar un precio manual con su motivo (no cambia el catálogo). Si lo dejás
            vacío, el trabajo queda con el precio pendiente de definir.
          </p>
          <Campo etiqueta="Precio manual">
            <input
              value={estado.precio}
              onChange={(e) => onCambio({ ...estado, precio: e.target.value })}
              disabled={deshabilitado}
              inputMode="decimal"
              style={estiloInput}
            />
          </Campo>
          <Campo etiqueta="Motivo del precio manual">
            <input
              value={estado.motivo}
              onChange={(e) => onCambio({ ...estado, motivo: e.target.value })}
              disabled={deshabilitado}
              style={estiloInput}
            />
          </Campo>
          {error && <p style={{ margin: 0, color: colores.error }}>{error}</p>}
        </>
      ) : (
        <p style={{ margin: "0.3rem 0 0" }}>
          El trabajo quedará con el precio pendiente de definir: lo define quien tiene el permiso
          de precio manual, o se toma del catálogo cuando Administración lo cargue. Sin precio no
          se genera el comprobante de ingreso ni se registra la autorización del cliente.
        </p>
      )}
    </div>
  );
}

/** «Precio manual» o «Precio pendiente» (los demás orígenes no se marcan). */
export function MarcaPrecio({ detalle }: { detalle: Detalle }) {
  const texto = etiquetaOrigenPrecio(detalle.precio_pendiente ? "PENDIENTE" : detalle.origen_precio);
  if (!texto) return null;
  return (
    <span title={detalle.precio_motivo ?? undefined}>
      <Etiqueta color={detalle.precio_pendiente ? colores.alerta : colores.acento}>{texto}</Etiqueta>
    </span>
  );
}

/** «Definir precio» de un trabajo con el precio pendiente. */
export function FormularioDefinirPrecio({
  detalle,
  tipo,
  modeloId,
  actor,
  deshabilitado,
  onConfirmar,
}: {
  detalle: Detalle | undefined;
  tipo: TipoReparacion | undefined;
  modeloId: string | null | undefined;
  actor: Usuario | null;
  deshabilitado: boolean;
  onConfirmar: (manual: PedidoPrecioManual | null) => void;
}) {
  const [estado, setEstado] = useState<EstadoPrecioManual>(SIN_MANUAL);
  if (!detalle) return null;
  const catalogo = tipo ? precioDelTipo(tipo, modeloId).precio : null;
  if (catalogo !== null) {
    return (
      <Boton disabled={deshabilitado} onClick={() => onConfirmar(null)}>
        Tomar el precio de catálogo ({importe(catalogo)})
      </Boton>
    );
  }
  if (!puedePrecioManual(actor)) {
    return (
      <p style={{ margin: 0, fontSize: "0.85rem", color: colores.suave }}>
        Todavía no hay precio de catálogo para este modelo. Lo define quien tiene el permiso de
        precio manual, o se toma del catálogo cuando Administración lo cargue.
      </p>
    );
  }
  // Sin precio de catálogo: el pedido manual se valida como en el alta.
  const sinCatalogo = { precio: "0", precio_por_modelo: true, precios_modelo: {} };
  const { pedido, error } = pedidoPrecioManual(sinCatalogo, modeloId, true, estado);
  return (
    <div>
      <Campo etiqueta="Precio manual">
        <input
          value={estado.precio}
          onChange={(e) => setEstado({ ...estado, precio: e.target.value })}
          disabled={deshabilitado}
          inputMode="decimal"
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Motivo del precio manual">
        <input
          value={estado.motivo}
          onChange={(e) => setEstado({ ...estado, motivo: e.target.value })}
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      {error && <p style={{ margin: "0 0 0.4rem", color: colores.error }}>{error}</p>}
      <Boton
        disabled={deshabilitado || pedido === null}
        onClick={() => {
          onConfirmar(pedido);
          setEstado(SIN_MANUAL);
        }}
      >
        Definir el precio
      </Boton>
    </div>
  );
}
