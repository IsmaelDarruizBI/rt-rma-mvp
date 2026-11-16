/**
 * Firma opcional de los documentos emitidos (DEC-MI-06). Ningún documento
 * la exige. Si el cliente firma, queda la evidencia ligada al documento:
 * el trazo en pantalla o una foto del papel firmado. Se puede registrar
 * también con la Orden entregada (no la modifica).
 */

import { type PointerEvent, useCallback, useEffect, useRef, useState } from "react";

import * as api from "../../api/firmas";
import type { FirmaDocumento, FormaFirma } from "../../api/firmas";
import { Boton, Campo, colores, estiloInput, fechaCorta } from "../../components/ui";
import { puede } from "../../lib/roles";
import type { Orden, Usuario } from "../../types/api";
import { nombreDeUsuario } from "./DetalleOrden";

const POR_DEFECTO = ["RECEPCION", "COORDINADOR_RMA", "ADMINISTRADOR"];

const mensajeDe = (causa: unknown) =>
  causa instanceof Error ? causa.message : String(causa);

export function FirmasDocumentos({
  orden,
  actor,
  usuarios,
  sugerido = null,
}: {
  orden: Orden;
  actor: Usuario | null;
  usuarios: Usuario[];
  /** UX-07: documento elegido desde «Registrar firma» (con su pedido). */
  sugerido?: { documentoId: string; pedido: number } | null;
}) {
  const [firmas, setFirmas] = useState<FirmaDocumento[]>([]);
  const [documentoId, setDocumentoId] = useState("");
  const seccion = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!sugerido) return;
    setDocumentoId(sugerido.documentoId);
    seccion.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [sugerido]);
  const [forma, setForma] = useState<FormaFirma>("PANTALLA");
  const [firmante, setFirmante] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const habilitado =
    orden.fotos_habilitadas === true &&
    puede(actor, "FIRMA_REGISTRAR", POR_DEFECTO);
  const documentos = orden.documentos_emitidos ?? [];

  const cargar = useCallback(() => {
    api
      .listarFirmas(orden.id)
      .then(setFirmas)
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, [orden.id]);
  useEffect(cargar, [cargar]);

  const registrar = (imagen: Blob) => {
    if (!actor || !documentoId) return;
    setOcupado(true);
    setError(null);
    api
      .registrarFirma(orden.id, documentoId, actor.id, forma, imagen, firmante.trim() || null)
      .then((lista) => {
        setFirmas(lista);
        setDocumentoId("");
        setFirmante("");
      })
      .catch((causa: unknown) => setError(mensajeDe(causa)))
      .finally(() => setOcupado(false));
  };

  if (documentos.length === 0) return null;

  return (
    <section
      ref={seccion}
      aria-label="Firmas de los documentos"
      style={{ marginTop: "1rem" }}
    >
      <h4 style={{ margin: "0 0 0.4rem" }}>Firmas (opcionales)</h4>
      {error && (
        <p role="alert" style={{ color: colores.error, fontSize: "0.85rem" }}>
          {error}
        </p>
      )}
      {firmas.length === 0 ? (
        <p style={{ fontSize: "0.85rem", color: colores.suave, margin: "0 0 0.5rem" }}>
          Ningún documento tiene firma registrada. No es obligatoria.
        </p>
      ) : (
        <ul style={{ paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
          {firmas.map((firma) => (
            <li key={firma.id} style={{ marginBottom: "0.4rem" }}>
              {firma.documento_id} ·{" "}
              {firma.forma === "PANTALLA" ? "firma en pantalla" : "foto del documento firmado"}
              {firma.firmante ? ` · ${firma.firmante}` : ""} · {fechaCorta(firma.fecha)} ·
              registró {nombreDeUsuario(usuarios, firma.usuario_id)}
              <ImagenFirma ordenId={orden.id} firmaId={firma.id} />
            </li>
          ))}
        </ul>
      )}
      {!habilitado && orden.fotos_habilitadas !== true && (
        <p style={{ fontSize: "0.8rem", color: colores.suave }}>
          Para registrar firmas hace falta el almacenamiento de imágenes de este
          entorno.
        </p>
      )}
      {habilitado && (
        <div style={{ maxWidth: 480 }}>
          <Campo etiqueta="Documento">
            <select
              value={documentoId}
              onChange={(e) => setDocumentoId(e.target.value)}
              disabled={ocupado}
              style={estiloInput}
            >
              <option value="">Elegir…</option>
              {documentos.map((documento) => (
                <option key={documento.id} value={documento.id}>
                  {documento.id} · {documento.tipo} v{documento.version}
                </option>
              ))}
            </select>
          </Campo>
          {documentoId && (
            <>
              <Campo etiqueta="Forma">
                <select
                  value={forma}
                  onChange={(e) => setForma(e.target.value as FormaFirma)}
                  disabled={ocupado}
                  style={estiloInput}
                >
                  <option value="PANTALLA">Firma en pantalla</option>
                  <option value="FOTO_DOCUMENTO">Foto del documento firmado</option>
                </select>
              </Campo>
              <Campo etiqueta="Quién firma (opcional)">
                <input
                  value={firmante}
                  onChange={(e) => setFirmante(e.target.value)}
                  disabled={ocupado}
                  style={estiloInput}
                />
              </Campo>
              {forma === "PANTALLA" ? (
                <LienzoFirma ocupado={ocupado} onGuardar={registrar} />
              ) : (
                <Campo etiqueta="Foto del documento firmado">
                  <input
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    capture="environment"
                    disabled={ocupado}
                    onChange={(e) => {
                      const archivo = e.target.files?.[0];
                      if (archivo) registrar(archivo);
                      e.target.value = "";
                    }}
                  />
                </Campo>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}

function ImagenFirma({ ordenId, firmaId }: { ordenId: string; firmaId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let creada: string | null = null;
    let vigente = true;
    api
      .imagenDeFirma(ordenId, firmaId)
      .then((imagen) => {
        if (!vigente) return;
        creada = URL.createObjectURL(imagen);
        setUrl(creada);
      })
      .catch(() => undefined);
    return () => {
      vigente = false;
      if (creada) URL.revokeObjectURL(creada);
    };
  }, [ordenId, firmaId]);
  if (!url) return null;
  return (
    <div>
      <img
        src={url}
        alt={`Firma ${firmaId}`}
        style={{ maxWidth: 240, maxHeight: 120, border: `1px solid ${colores.borde}` }}
      />
    </div>
  );
}

/** Trazo con el dedo o el mouse; se guarda como PNG. */
function LienzoFirma({
  ocupado,
  onGuardar,
}: {
  ocupado: boolean;
  onGuardar: (imagen: Blob) => void;
}) {
  const lienzo = useRef<HTMLCanvasElement>(null);
  const dibujando = useRef(false);
  const [trazada, setTrazada] = useState(false);

  const punto = (evento: PointerEvent<HTMLCanvasElement>) => {
    const rect = evento.currentTarget.getBoundingClientRect();
    const escala = evento.currentTarget.width / rect.width;
    return {
      x: (evento.clientX - rect.left) * escala,
      y: (evento.clientY - rect.top) * escala,
    };
  };

  const empezar = (evento: PointerEvent<HTMLCanvasElement>) => {
    const ctx = evento.currentTarget.getContext("2d");
    if (!ctx) return;
    evento.currentTarget.setPointerCapture(evento.pointerId);
    dibujando.current = true;
    const { x, y } = punto(evento);
    ctx.lineWidth = 2.5;
    ctx.lineCap = "round";
    ctx.strokeStyle = "#111827";
    ctx.beginPath();
    ctx.moveTo(x, y);
  };

  const mover = (evento: PointerEvent<HTMLCanvasElement>) => {
    if (!dibujando.current) return;
    const ctx = evento.currentTarget.getContext("2d");
    if (!ctx) return;
    const { x, y } = punto(evento);
    ctx.lineTo(x, y);
    ctx.stroke();
    setTrazada(true);
  };

  const limpiar = () => {
    const elemento = lienzo.current;
    const ctx = elemento?.getContext("2d");
    if (elemento && ctx) {
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, elemento.width, elemento.height);
    }
    setTrazada(false);
  };

  useEffect(limpiar, []);

  return (
    <div>
      <canvas
        ref={lienzo}
        width={600}
        height={200}
        aria-label="Lienzo para firmar"
        onPointerDown={empezar}
        onPointerMove={mover}
        onPointerUp={() => (dibujando.current = false)}
        onPointerLeave={() => (dibujando.current = false)}
        style={{
          width: "100%",
          maxWidth: 480,
          border: `1px solid ${colores.borde}`,
          borderRadius: 6,
          touchAction: "none",
          background: "#fff",
        }}
      />
      <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.4rem" }}>
        <Boton
          disabled={ocupado || !trazada}
          onClick={() =>
            lienzo.current?.toBlob((imagen) => {
              if (imagen) onGuardar(imagen);
              limpiar();
            }, "image/png")
          }
        >
          Guardar firma
        </Boton>
        <Boton variante="secundario" disabled={ocupado} onClick={limpiar}>
          Borrar
        </Boton>
      </div>
    </div>
  );
}
