/**
 * Importar precios por modelo (DEC-AJ-13, BF-02), con «Gestionar precios».
 *
 * 1. Descargar la plantilla con los precios vigentes (.xlsx o CSV): modelos
 *    Apple en las filas y Tipos con precio por modelo en las columnas, por
 *    código.
 * 2. Elegir el archivo editado o pegar las celdas copiadas de Google Sheets
 *    o Excel.
 * 3. «Vista previa»: resumen, errores (con su celda), avisos y los precios
 *    nuevos o que cambian. No escribe nada.
 * 4. «Aplicar»: solo sin errores y con algún cambio. La API vuelve a leer y
 *    validar la misma planilla y aplica todo o nada, con la auditoría
 *    agrupada por importación.
 *
 * La edición individual (Tipos de reparación → Precios por modelo) no
 * cambia. Una celda vacía no cambia nada: los precios se quitan allí.
 */

import { useState } from "react";

import * as api from "../../api/configuracion";
import type { ResultadoImportacion, VistaPreviaImportacion } from "../../api/configuracion";
import { Mensajes, useComando } from "../../components/FormularioModal";
import { Boton, Campo, Etiqueta, colores, estiloInput, importe } from "../../components/ui";
import type { Usuario } from "../../types/api";
import { descargarArchivo } from "../ordenes-reparacion/whatsapp";
import {
  type Planilla,
  consultaImportacion,
  etiquetaEstado,
  motivoParaNoAplicar,
  nombrePlantilla,
  planillaDeArchivo,
  planillaPegada,
  puedeAplicar,
  textoObservacion,
  textoResumen,
} from "./importacionPrecios";

type Origen = "archivo" | "pegado";

const celda = { padding: "0.25rem 0.5rem", textAlign: "left" as const };

function ListaObservaciones({
  titulo,
  color,
  items,
}: {
  titulo: string;
  color: string;
  items: { celda: string | null; mensaje: string }[];
}) {
  if (items.length === 0) return null;
  return (
    <div style={{ marginTop: "0.6rem" }}>
      <strong style={{ color, fontSize: "0.85rem" }}>
        {titulo} ({items.length})
      </strong>
      <ul style={{ margin: "0.2rem 0 0", paddingLeft: "1.1rem", fontSize: "0.85rem", maxHeight: 240, overflowY: "auto" }}>
        {items.map((item, i) => (
          <li key={i}>{textoObservacion(item)}</li>
        ))}
      </ul>
    </div>
  );
}

function VistaPrevia({ vista }: { vista: VistaPreviaImportacion }) {
  return (
    <div style={{ marginTop: "0.8rem" }}>
      <p style={{ margin: 0, fontSize: "0.9rem" }}>
        {vista.resumen.modelos} modelos y {vista.resumen.tipos} tipos: {textoResumen(vista.resumen)}.
      </p>
      {vista.columnas_ignoradas.length > 0 && (
        <p style={{ margin: "0.3rem 0 0", fontSize: "0.8rem", color: colores.suave }}>
          Columnas ignoradas (no empiezan con un código TR):{" "}
          {vista.columnas_ignoradas
            .map((c) => `${c.columna}${c.encabezado ? ` «${c.encabezado}»` : ""}`)
            .join(", ")}
          .
        </p>
      )}
      <ListaObservaciones titulo="Errores" color={colores.error} items={vista.errores} />
      <ListaObservaciones titulo="Avisos" color={colores.alerta} items={vista.avisos} />
      {vista.cambios.length > 0 && (
        <div style={{ overflowX: "auto", marginTop: "0.6rem", maxHeight: 420, overflowY: "auto" }}>
          <table style={{ borderCollapse: "collapse", fontSize: "0.85rem", minWidth: 620 }}>
            <thead>
              <tr>
                {["Celda", "Modelo", "Tipo", "Antes", "Nuevo", ""].map((t) => (
                  <th key={t} style={celda}>
                    {t}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {vista.cambios.map((c) => (
                <tr key={c.celda}>
                  <td style={celda}>{c.celda}</td>
                  <td style={celda}>
                    {c.modelo_equipo_id} · {c.modelo}
                  </td>
                  <td style={celda}>
                    {c.tipo_reparacion_id} · {c.tipo}
                  </td>
                  <td style={celda}>{c.anterior === null ? "—" : importe(c.anterior)}</td>
                  <td style={celda}>{importe(c.nuevo)}</td>
                  <td style={celda}>
                    <Etiqueta color={c.estado === "NUEVO" ? colores.ok : colores.acento}>
                      {etiquetaEstado(c.estado)}
                    </Etiqueta>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function ImportarPrecios({ actor }: { actor: Usuario }) {
  const [origen, setOrigen] = useState<Origen>("archivo");
  const [planilla, setPlanilla] = useState<Planilla | null>(null);
  const [texto, setTexto] = useState("");
  const [vista, setVista] = useState<VistaPreviaImportacion | null>(null);
  const [resultado, setResultado] = useState<ResultadoImportacion | null>(null);
  const { error, setError, aviso, setAviso, ocupado, ejecutar } = useComando();

  const reiniciar = () => {
    setVista(null);
    setResultado(null);
    setAviso(null);
    setError(null);
  };

  const descargar = (formato: "xlsx" | "csv") =>
    void ejecutar(
      () => api.descargarPlantillaPrecios(formato),
      "Se descargó la plantilla con los precios vigentes.",
    ).then((archivo) => archivo && descargarArchivo(archivo, nombrePlantilla(formato)));

  const elegirArchivo = async (archivo: File | undefined) => {
    reiniciar();
    if (!archivo) {
      setPlanilla(null);
      return;
    }
    // Una copia del contenido: la vista previa y «Aplicar» envían
    // exactamente lo mismo, aunque el archivo cambie después en el disco.
    let contenido: Blob;
    try {
      contenido = new Blob([await archivo.arrayBuffer()]);
    } catch {
      setPlanilla(null);
      setError("No se pudo leer el archivo: volvé a elegirlo.");
      return;
    }
    const elegida = planillaDeArchivo(contenido, archivo.name);
    if ("error" in elegida) {
      setPlanilla(null);
      setError(elegida.error);
    } else {
      setPlanilla(elegida);
    }
  };

  const pegar = (valor: string) => {
    reiniciar();
    setTexto(valor);
    setPlanilla(planillaPegada(valor));
  };

  const revisar = () => {
    if (!planilla) return;
    setResultado(null);
    void ejecutar(
      () => api.previsualizarImportacion(consultaImportacion(actor.id, planilla.nombre), planilla.cuerpo),
      "Vista previa lista: revisá los cambios antes de aplicar.",
    ).then((v) => {
      if (!v) return;
      setVista(v);
      // Con errores no hay nada que confirmar: lo explican la lista y el
      // motivo junto a «Aplicar».
      if (v.errores.length > 0) setAviso(null);
    });
  };

  const aplicar = () => {
    if (!planilla || !puedeAplicar(vista)) return;
    void ejecutar(
      () => api.aplicarImportacion(consultaImportacion(actor.id, planilla.nombre), planilla.cuerpo),
      (r) =>
        `Se aplicó la importación: ${r.importacion.nuevos} precios nuevos y ${r.importacion.actualizados} actualizados.`,
    ).then((r) => {
      if (!r) return;
      setResultado(r);
      setVista(null);
    });
  };

  const motivo = motivoParaNoAplicar(vista);

  return (
    <section>
      <h3 style={{ margin: "0 0 0.5rem" }}>Importar precios por modelo</h3>
      <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.suave }}>
        Una matriz con los modelos en las filas (código MOD-…) y los Tipos de reparación con precio
        por modelo en las columnas (código TR-… al principio del encabezado). Solo modelos Apple
        existentes; no se crean modelos ni tipos. Una celda vacía no cambia el precio: para quitar un
        precio usá la edición individual en Tipos de reparación. Se aplica todo o nada y las Órdenes
        no cambian.
      </p>

      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.8rem" }}>
        <Boton variante="secundario" disabled={ocupado} onClick={() => descargar("xlsx")}>
          Descargar plantilla (.xlsx)
        </Boton>
        <Boton variante="secundario" disabled={ocupado} onClick={() => descargar("csv")}>
          Descargar plantilla (CSV)
        </Boton>
      </div>

      <div role="radiogroup" aria-label="Origen de los precios" style={{ display: "flex", gap: "1rem", marginBottom: "0.6rem", fontSize: "0.85rem" }}>
        {(
          [
            ["archivo", "Subir un archivo"],
            ["pegado", "Pegar celdas"],
          ] as const
        ).map(([valor, etiqueta]) => (
          <label key={valor}>
            <input
              type="radio"
              name="origen-importacion"
              checked={origen === valor}
              onChange={() => {
                setOrigen(valor);
                setPlanilla(valor === "pegado" ? planillaPegada(texto) : null);
                reiniciar();
              }}
            />{" "}
            {etiqueta}
          </label>
        ))}
      </div>

      {origen === "archivo" ? (
        <Campo etiqueta="Planilla (.xlsx o .csv; se importa la primera hoja)">
          <input
            type="file"
            accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
            disabled={ocupado}
            onChange={(e) => {
              void elegirArchivo(e.target.files?.[0]);
              // Así se puede volver a elegir el mismo archivo después de
              // editarlo.
              e.target.value = "";
            }}
            style={estiloInput}
          />
          {planilla?.nombre && (
            <span style={{ display: "block", marginTop: "0.2rem", fontSize: "0.8rem" }}>
              Elegido: {planilla.nombre}
            </span>
          )}
        </Campo>
      ) : (
        <Campo etiqueta="Celdas copiadas de Google Sheets o Excel, con el encabezado">
          <textarea
            value={texto}
            onChange={(e) => pegar(e.target.value)}
            rows={8}
            placeholder={"Modelo\tTR-001 · Cambio de batería\nMOD-0001\t80.000"}
            style={{ ...estiloInput, fontFamily: "monospace", whiteSpace: "pre" }}
          />
        </Campo>
      )}

      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
        <Boton variante="secundario" disabled={ocupado || !planilla} onClick={revisar}>
          Vista previa
        </Boton>
        <Boton disabled={ocupado || !puedeAplicar(vista)} onClick={aplicar}>
          Aplicar
        </Boton>
        {vista && motivo && (
          <span style={{ fontSize: "0.8rem", color: colores.suave }}>{motivo}</span>
        )}
      </div>

      <Mensajes error={error} aviso={aviso} />
      {vista && <VistaPrevia vista={vista} />}
      {resultado && (
        <div style={{ marginTop: "0.8rem", fontSize: "0.85rem" }}>
          <p style={{ margin: 0 }}>
            Importación {resultado.importacion.id.slice(0, 8)}
            {resultado.importacion.nombre_archivo ? ` (${resultado.importacion.nombre_archivo})` : ""}:{" "}
            {resultado.cambios_registrados} precios guardados, {resultado.importacion.sin_cambio} sin
            cambios. Queda en el historial de precios con este identificador.
          </p>
          <VistaPrevia vista={{ ...resultado.vista, errores: [], avisos: [] }} />
        </div>
      )}
    </section>
  );
}
