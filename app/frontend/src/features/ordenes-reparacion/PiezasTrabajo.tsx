/**
 * Requisitos de insumo de un trabajo y su pieza elegida (DEC-AJ-14, D-14.4).
 *
 * - `RequisitosTrabajo`: cada requisito del Tipo (categoría y cantidad) con
 *   la pieza elegida o «Pendiente de elegir», sus marcas y, con
 *   PIEZA_ELEGIR, «Elegir pieza» o «Sustituir».
 * - `VentanaElegirPieza`: lee las piezas que la API ofrece para el
 *   requisito (ya filtradas por compatibilidad), muestra su disponible y
 *   pide el motivo cuando corresponde.
 *
 * La lógica está en `piezas.ts`; la API valida todo de nuevo.
 */

import { useEffect, useState } from "react";

import { opcionesDePieza } from "../../api/ordenes";
import { FormularioModal, mensajeDe } from "../../components/FormularioModal";
import { SelectorInsumo, useClasificacionInsumos } from "../../components/SelectorInsumo";
import { Boton, Campo, Etiqueta, colores, estiloInput, fechaCorta } from "../../components/ui";
import type { Detalle, OpcionesPieza, RequisitoInsumoDetalle } from "../../types/api";
import { etiquetaInsumo } from "../inventario/clasificacion";
import {
  type AccionPieza,
  MOTIVO_PIEZA_MAXIMO,
  type PedidoPieza,
  type TonoMarca,
  accionDePieza,
  alcanza,
  etiquetaPiezaElegida,
  exigeMotivo,
  marcasDeRequisito,
  pedidoDePieza,
  requisitosDe,
  textoCantidad,
  textoDisponible,
} from "./piezas";

const COLOR_DE_TONO: Record<TonoMarca, string> = {
  alerta: colores.alerta,
  ok: colores.ok,
  suave: colores.suave,
  acento: colores.acento,
  error: colores.error,
};

interface PropsRequisitos {
  ordenId: string;
  detalle: Detalle;
  puedeElegir: boolean;
  ocupado: boolean;
  nombreUsuario: (usuarioId: string | null) => string;
  /** Sin él, solo se muestra (no se ofrece elegir). */
  onElegir?: (detalleId: string, pedido: PedidoPieza) => Promise<void>;
}

/** Sin requisitos (o con un backend anterior) no dibuja nada ni pide nada. */
export function RequisitosTrabajo(props: PropsRequisitos) {
  if (requisitosDe(props.detalle).length === 0) return null;
  return <ListaRequisitos {...props} />;
}

function ListaRequisitos({
  ordenId,
  detalle,
  puedeElegir,
  ocupado,
  nombreUsuario,
  onElegir,
}: PropsRequisitos) {
  const clasificacion = useClasificacionInsumos();
  const [abierta, setAbierta] = useState<{
    requisito: RequisitoInsumoDetalle;
    accion: AccionPieza;
  } | null>(null);
  const requisitos = requisitosDe(detalle);
  return (
    <div style={{ fontSize: "0.8rem", color: colores.suave, marginTop: "0.15rem" }}>
      Piezas por categoría:
      <ul style={{ margin: "0.15rem 0 0", paddingLeft: "1.1rem" }}>
        {requisitos.map((requisito) => {
          const accion = onElegir
            ? accionDePieza(detalle.estado, requisito, puedeElegir)
            : null;
          return (
            <li
              key={requisito.requisito_id}
              style={{ marginBottom: "0.2rem", overflowWrap: "anywhere" }}
            >
              {requisito.categoria_nombre} × {textoCantidad(requisito.cantidad)}:{" "}
              {requisito.estado === "ELEGIDA" && (
                <strong style={{ color: colores.texto }}>
                  {etiquetaPiezaElegida(requisito, (insumo) =>
                    etiquetaInsumo(insumo, clasificacion),
                  )}
                </strong>
              )}{" "}
              <span style={{ display: "inline-flex", flexWrap: "wrap", gap: "0.25rem" }}>
                {marcasDeRequisito(requisito).map((marca) => (
                  <Etiqueta key={marca.texto} color={COLOR_DE_TONO[marca.tono]}>
                    {marca.texto}
                  </Etiqueta>
                ))}
              </span>
              {accion && (
                <>
                  {" "}
                  <Boton
                    variante="secundario"
                    disabled={ocupado}
                    onClick={() => setAbierta({ requisito, accion })}
                  >
                    {accion === "ELEGIR" ? "Elegir pieza" : "Sustituir"}
                  </Boton>
                </>
              )}
              {requisito.estado === "ELEGIDA" &&
                requisito.causa !== "AUTOMATICA" &&
                requisito.elegida_por && (
                  <span style={{ display: "block" }}>
                    {requisito.causa === "SUSTITUCION" ? "Sustituida" : "Elegida"} por{" "}
                    {nombreUsuario(requisito.elegida_por)}
                    {requisito.elegida_en ? ` el ${fechaCorta(requisito.elegida_en)}` : ""}
                    {requisito.motivo ? ` · ${requisito.motivo}` : ""}
                  </span>
                )}
            </li>
          );
        })}
      </ul>
      {abierta && onElegir && (
        <VentanaElegirPieza
          ordenId={ordenId}
          detalle={detalle}
          requisito={abierta.requisito}
          accion={abierta.accion}
          onCerrar={() => setAbierta(null)}
          onConfirmar={(pedido) => onElegir(detalle.id, pedido)}
        />
      )}
    </div>
  );
}

export function VentanaElegirPieza({
  ordenId,
  detalle,
  requisito,
  accion,
  onCerrar,
  onConfirmar,
}: {
  ordenId: string;
  detalle: Detalle;
  requisito: RequisitoInsumoDetalle;
  accion: AccionPieza;
  onCerrar: () => void;
  onConfirmar: (pedido: PedidoPieza) => Promise<void>;
}) {
  const clasificacion = useClasificacionInsumos();
  const [datos, setDatos] = useState<OpcionesPieza | null>(null);
  const [errorCarga, setErrorCarga] = useState<string | null>(null);
  const [insumoId, setInsumoId] = useState("");
  const [motivo, setMotivo] = useState("");

  useEffect(() => {
    let vigente = true;
    opcionesDePieza(ordenId, detalle.id, requisito.requisito_id)
      .then((leidas) => {
        if (vigente) setDatos(leidas);
      })
      .catch((causa: unknown) => {
        if (vigente) setErrorCarga(mensajeDe(causa));
      });
    return () => {
      vigente = false;
    };
  }, [ordenId, detalle.id, requisito.requisito_id]);

  const opciones = datos?.opciones ?? [];
  const opcion = opciones.find((candidata) => candidata.id === insumoId) ?? null;
  const cantidad = datos?.cantidad ?? requisito.cantidad;
  const { pedido, error } = pedidoDePieza(requisito, opciones, insumoId, motivo);
  const pideMotivo = exigeMotivo(requisito, opcion);
  const categoria = datos?.categoria_nombre ?? requisito.categoria_nombre;

  return (
    <FormularioModal
      amplio
      titulo={`${accion === "ELEGIR" ? "Elegir pieza" : "Sustituir la pieza"} · ${categoria}`}
      textoConfirmar={accion === "ELEGIR" ? "Elegir la pieza" : "Sustituir la pieza"}
      listo={pedido !== null}
      onCerrar={onCerrar}
      onConfirmar={() => (pedido ? onConfirmar(pedido) : Promise.resolve())}
    >
      <p style={{ margin: "0 0 0.6rem", fontSize: "0.85rem" }}>
        {detalle.tipo_reparacion_nombre}: hace falta {textoCantidad(cantidad)} de {categoria}.
      </p>
      {accion === "SUSTITUIR" && (
        <p style={{ margin: "0 0 0.6rem", fontSize: "0.85rem" }}>
          Pieza actual: <strong>{etiquetaPiezaElegida(requisito)}</strong>.{" "}
          {requisito.reservada
            ? "Está reservada: al sustituirla se libera esa reserva y se reserva la nueva en la misma operación. Si la nueva no tiene disponible, no cambia nada."
            : "Todavía no se reservó: solo cambia la elección."}
        </p>
      )}
      {errorCarga && (
        <p role="alert" style={{ margin: "0 0 0.6rem", color: colores.error, fontSize: "0.85rem" }}>
          {errorCarga}
        </p>
      )}
      {!datos && !errorCarga && (
        <p role="status" style={{ margin: "0 0 0.6rem", color: colores.suave, fontSize: "0.85rem" }}>
          Buscando las piezas que se pueden elegir…
        </p>
      )}
      {datos?.compatibilidad_no_verificada && (
        <p
          role="note"
          style={{
            margin: "0 0 0.6rem",
            padding: "0.5rem",
            border: `1px solid ${colores.alerta}`,
            borderRadius: 6,
            fontSize: "0.85rem",
          }}
        >
          El equipo no tiene un modelo técnico y no hay piezas universales de esta categoría:
          se ofrecen todas las de la categoría. La que elijas queda marcada «Compatibilidad no
          verificada» y exige el motivo.
        </p>
      )}
      {datos && opciones.length === 0 && (
        <p style={{ margin: "0 0 0.6rem", fontSize: "0.85rem", color: colores.alerta }}>
          No hay piezas de {categoria} que se puedan elegir para este equipo. Hace falta dar
          de alta o comprar una compatible.
        </p>
      )}
      {opciones.length > 0 && (
        <SelectorInsumo
          insumos={opciones}
          clasificacion={clasificacion}
          valor={insumoId}
          onCambiar={setInsumoId}
          etiqueta="Pieza"
          opcionVacia="Elegir la pieza…"
          sufijo={(candidata) =>
            [
              textoDisponible(candidata),
              candidata.elegida ? "elegida ahora" : null,
              candidata.compatibilidad_no_verificada ? "sin verificar" : null,
            ]
              .filter(Boolean)
              .join(" · ")
          }
        />
      )}
      {opcion && (
        <p
          style={{
            margin: "0 0 0.6rem",
            fontSize: "0.85rem",
            color: alcanza(opcion, cantidad) ? colores.suave : colores.alerta,
          }}
        >
          Pieza elegida en el formulario: {textoDisponible(opcion)}
          {alcanza(opcion, cantidad)
            ? "."
            : ` (hace falta ${textoCantidad(cantidad)}): ${
                detalle.estado === "EN_PROGRESO"
                  ? "no se puede reservar ahora."
                  : "se puede elegir igual, pero no alcanza para reservarla al iniciar."
              }`}
        </p>
      )}
      <Campo etiqueta={pideMotivo ? "Motivo (obligatorio)" : "Motivo (opcional)"}>
        <textarea
          value={motivo}
          maxLength={MOTIVO_PIEZA_MAXIMO}
          rows={2}
          onChange={(evento) => setMotivo(evento.target.value)}
          style={{ ...estiloInput, resize: "vertical" }}
        />
      </Campo>
      {error && (
        <p style={{ margin: "0 0 0.6rem", color: colores.error, fontSize: "0.85rem" }}>{error}</p>
      )}
    </FormularioModal>
  );
}
