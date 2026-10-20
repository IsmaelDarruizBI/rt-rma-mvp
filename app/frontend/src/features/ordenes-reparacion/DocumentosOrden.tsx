/**
 * Documentos de la Orden: emitidos, vistas previas e impresión.
 *
 * Distingue siempre dos cosas: el documento EMITIDO (lo que se le entregó
 * al cliente, inmutable, con su versión) y la VISTA PREVIA (los datos
 * vigentes, sin emitir). La hoja se imprime en A4 o se guarda como PDF
 * desde el navegador; en la impresión no salen la navegación ni los
 * botones.
 *
 * En el ingreso inicial de Cliente Externo hay UN solo documento: el
 * comprobante de INGRESO Y AUTORIZACIÓN (lo genera Recepción con un
 * botón; acredita la recepción del equipo y los trabajos autorizados con
 * su precio). En los demás caminos siguen los dos de siempre: el de
 * RECEPCIÓN (lo emite el proceso al finalizar la definición, sin trabajos
 * ni precios) y el de AUTORIZACIÓN (a pedido, cuando cambia lo
 * autorizado). Los que llevan trabajos se descargan como PDF y se
 * comparten por WhatsApp. Ninguno es un comprobante de pago.
 */

import { type ReactNode, useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";

import * as api from "../../api/ordenes";
import {
  Boton,
  Campo,
  Etiqueta,
  colores,
  estiloInput,
  fechaCorta,
  importe,
} from "../../components/ui";
import type {
  Accion,
  CanalComunicacion,
  ContenidoAutorizacion,
  ContenidoDocumento,
  ContenidoEntrega,
  ContenidoGarantia,
  ContenidoIngreso,
  ContenidoRecepcion,
  DescuentoEnDocumento,
  DocumentoEmitido,
  DocumentosDeOrden,
  Orden,
  TipoDocumento,
  Usuario,
} from "../../types/api";
import { nombreDeUsuario } from "./DetalleOrden";
import { CANAL, etiqueta } from "./etiquetas";
import { CampoCheckin } from "./ListadoOrdenes";
import { Seccion, habilitada } from "./PagosOrden";
import {
  type ResultadoCompartir,
  compartirPorWhatsapp,
  descargarArchivo,
  mensajeComprobante,
  telefonoParaWhatsapp,
} from "./whatsapp";

const NOMBRE_TIPO: Record<TipoDocumento, string> = {
  COMPROBANTE_RECEPCION: "Comprobante de recepción",
  COMPROBANTE_ENTREGA: "Comprobante de entrega",
  GARANTIA: "Garantía",
  COMPROBANTE_AUTORIZACION: "Comprobante de autorización",
  COMPROBANTE_INGRESO: "Comprobante de ingreso y autorización",
};

/** Para qué sirve cada uno: los dos del ingreso no son lo mismo. */
const PARA_QUE: Partial<Record<TipoDocumento, string>> = {
  COMPROBANTE_RECEPCION:
    "Constancia de ingreso y custodia del equipo. No incluye trabajos ni precios.",
  COMPROBANTE_AUTORIZACION:
    "Trabajos que autorizó el cliente y su precio. No es un comprobante de pago.",
  COMPROBANTE_INGRESO:
    "Recepción del equipo y trabajos autorizados con su precio. No es un comprobante de pago.",
};

/** Los que llevan trabajos y precios: se descargan como PDF y se comparten. */
const CON_PDF = new Set<TipoDocumento>([
  "COMPROBANTE_AUTORIZACION",
  "COMPROBANTE_INGRESO",
]);

/** Canales por los que el cliente puede autorizar al ingresar. */
const CANALES: CanalComunicacion[] = [
  "PRESENCIAL",
  "WHATSAPP",
  "TELEFONO",
  "EMAIL",
  "OTRO",
];

/** Título del documento: una devolución sin reparación no es una entrega. */
function tituloDe(contenido: ContenidoDocumento): string {
  if (contenido.tipo === "COMPROBANTE_ENTREGA") {
    return contenido.tipo_entrega === "DEVOLUCION_SIN_REPARACION"
      ? "Comprobante de devolución sin reparación"
      : "Comprobante de entrega";
  }
  if (contenido.tipo === "GARANTIA") return "Certificado de garantía";
  if (contenido.tipo === "COMPROBANTE_AUTORIZACION") {
    return "Comprobante de autorización";
  }
  if (contenido.tipo === "COMPROBANTE_INGRESO") {
    return "Comprobante de ingreso y autorización";
  }
  return "Comprobante de recepción";
}

/**
 * La última versión emitida del comprobante de autorización, si hay. Sin
 * `Array.prototype.at`: no está en `lib` ES2020 ni en Safari < 15.4.
 */
function ultimoComprobanteAutorizacion(
  emitidos: DocumentoEmitido[],
): DocumentoEmitido | undefined {
  const versiones = emitidos.filter(
    (documento) => documento.tipo === "COMPROBANTE_AUTORIZACION",
  );
  return versiones[versiones.length - 1];
}

/** El último emitido que se descarga como PDF (ingreso o autorización). */
function ultimoConPdf(
  emitidos: DocumentoEmitido[],
): DocumentoEmitido | undefined {
  const conPdf = emitidos.filter((documento) => CON_PDF.has(documento.tipo));
  return conPdf[conPdf.length - 1];
}

/** Lo que se muestra en el visor: un emitido o una vista previa. */
type Visible =
  | { clase: "emitido"; documento: DocumentoEmitido }
  | { clase: "previa"; tipo: TipoDocumento; contenido: ContenidoDocumento };

interface Props {
  orden: Orden;
  actor: Usuario | null;
  usuarios: Usuario[];
  ocupado: boolean;
  onEmitirRecepcion: (motivo: string | null) => void;
  onEmitirAutorizacion: () => void;
  /** Ingreso inicial: confirma, autoriza y genera el comprobante. */
  onGenerarIngreso: (canal: CanalComunicacion, checkin: boolean | null) => void;
}

export function DocumentosOrden({
  orden,
  actor,
  usuarios,
  ocupado,
  onEmitirRecepcion,
  onEmitirAutorizacion,
  onGenerarIngreso,
}: Props) {
  const [documentos, setDocumentos] = useState<DocumentosDeOrden | null>(null);
  const [visible, setVisible] = useState<Visible | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Comprobante (ingreso o autorización) pedido desde esta pantalla: al
  // llegar el nuevo se abre para descargarlo o compartirlo. Generarlo no
  // es enviarlo: compartir es otro paso, a cargo de Recepción.
  const [pedido, setPedido] = useState<string | null>(null);

  // Se recargan cuando la Orden cambia (emisión, entrega, devolución).
  useEffect(() => {
    let vigente = true;
    api
      .obtenerDocumentos(orden.id)
      .then((datos) => vigente && setDocumentos(datos))
      .catch(() => vigente && setError("No se pudieron cargar los documentos."));
    return () => {
      vigente = false;
    };
  }, [orden.id, orden.updated_at]);

  useEffect(() => {
    if (pedido === null || !documentos) return;
    const ultimo = ultimoConPdf(documentos.emitidos);
    if (ultimo && ultimo.id !== pedido) {
      setPedido(null);
      setVisible({ clase: "emitido", documento: ultimo });
    }
  }, [documentos, pedido]);

  const verPrevia = useCallback(
    async (tipo: TipoDocumento) => {
      setError(null);
      try {
        const previa = await api.vistaPreviaDocumento(orden.id, tipo);
        setVisible({ clase: "previa", tipo, contenido: previa.contenido });
      } catch {
        setError("No hay vista previa de ese documento ahora.");
      }
    },
    [orden.id],
  );

  const emitir = orden.acciones_custodia.find(
    (accion) => accion.codigo === "EMITIR_COMPROBANTE_RECEPCION",
  );
  const generar = orden.acciones_autorizacion.find(
    (accion) => accion.codigo === "EMITIR_COMPROBANTE_AUTORIZACION",
  );
  const ingreso = orden.acciones_disponibles.find(
    (accion) => accion.codigo === "GENERAR_COMPROBANTE_INGRESO",
  );
  const emitidos = documentos?.emitidos ?? [];
  const marcas = documentos?.marcas ?? orden.documentos;
  // El comprobante de ingreso incluye la recepción: la marca del proceso
  // (PROC-REP-060) no es un documento aparte sin copia.
  const conIngreso = emitidos.some(
    (documento) => documento.tipo === "COMPROBANTE_INGRESO",
  );
  // Marcas del proceso sin copia del documento: Orden anterior.
  const sinCopia = (
    [
      ["COMPROBANTE_RECEPCION", marcas.comprobante_recepcion],
      ["COMPROBANTE_ENTREGA", marcas.comprobante_final],
      ["GARANTIA", marcas.garantia_reparacion],
    ] as const
  ).filter(
    ([tipo, marca]) =>
      marca.generado &&
      !emitidos.some((documento) => documento.tipo === tipo) &&
      !(tipo === "COMPROBANTE_RECEPCION" && conIngreso),
  );

  return (
    <div>
      {emitidos.length === 0 && sinCopia.length === 0 ? (
        <p style={{ margin: "0 0 0.6rem", fontSize: "0.85rem", color: colores.suave }}>
          Todavía no se emitió ningún documento.
        </p>
      ) : (
        <ul style={{ listStyle: "none", margin: "0 0 0.6rem", padding: 0 }}>
          {emitidos.map((documento) => (
            <li
              key={documento.id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "0.6rem",
                flexWrap: "wrap",
                padding: "0.45rem 0",
                borderBottom: `1px solid ${colores.borde}`,
                fontSize: "0.85rem",
              }}
            >
              <span style={{ minWidth: 0 }}>
                <strong>{tituloDe(documento.contenido)}</strong>{" "}
                <span style={{ color: colores.suave }}>
                  {documento.id} · v{documento.version} ·{" "}
                  {fechaCorta(documento.fecha_emision)} ·{" "}
                  {nombreDeUsuario(usuarios, documento.usuario_id)}
                </span>{" "}
                {documento.vigente ? (
                  <Etiqueta color={colores.ok}>VIGENTE</Etiqueta>
                ) : (
                  <Etiqueta color={colores.suave}>REEMPLAZADO</Etiqueta>
                )}
                {PARA_QUE[documento.tipo] && (
                  <span style={{ display: "block", color: colores.suave }}>
                    {PARA_QUE[documento.tipo]}
                  </span>
                )}
                {documento.motivo && (
                  <span style={{ display: "block", color: colores.suave }}>
                    Motivo de la versión: {documento.motivo}
                  </span>
                )}
              </span>
              <span style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                <Boton
                  variante="secundario"
                  onClick={() => setVisible({ clase: "emitido", documento })}
                >
                  {CON_PDF.has(documento.tipo) ? "Ver" : "Ver / imprimir"}
                </Boton>
                {CON_PDF.has(documento.tipo) && (
                  <AccionesPdf documento={documento} />
                )}
              </span>
            </li>
          ))}
          {sinCopia.map(([tipo, marca]) => (
            <li
              key={tipo}
              style={{
                padding: "0.45rem 0",
                borderBottom: `1px solid ${colores.borde}`,
                fontSize: "0.85rem",
                color: colores.suave,
              }}
            >
              <strong style={{ color: colores.texto }}>{NOMBRE_TIPO[tipo]}</strong>{" "}
              emitido el {fechaCorta(marca.fecha_generacion ?? "")} (registro
              anterior, sin copia del contenido).
            </li>
          ))}
        </ul>
      )}

      {(documentos?.previsualizables.length ?? 0) > 0 && (
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          {documentos?.previsualizables.map((tipo) => (
            <Boton key={tipo} variante="secundario" onClick={() => verPrevia(tipo)}>
              Vista previa: {NOMBRE_TIPO[tipo].toLowerCase()}
            </Boton>
          ))}
        </div>
      )}

      {ingreso && (
        <FormularioComprobanteIngreso
          accion={ingreso}
          orden={orden}
          ocupado={ocupado}
          onGenerar={(canal, checkin) => {
            setPedido(ultimoConPdf(emitidos)?.id ?? "");
            onGenerarIngreso(canal, checkin);
          }}
        />
      )}

      {generar && (
        <FormularioComprobanteAutorizacion
          accion={generar}
          orden={orden}
          emitidos={emitidos}
          ocupado={ocupado}
          onGenerar={() => {
            setPedido(ultimoConPdf(emitidos)?.id ?? "");
            onEmitirAutorizacion();
          }}
        />
      )}

      {emitir && (
        <FormularioReemision
          accion={emitir}
          actor={actor}
          ocupado={ocupado}
          onEmitir={onEmitirRecepcion}
        />
      )}

      {error && (
        <p role="alert" style={{ margin: "0.6rem 0 0", fontSize: "0.8rem", color: colores.error }}>
          {error}
        </p>
      )}

      {visible && (
        <VisorDocumento visible={visible} onCerrar={() => setVisible(null)} />
      )}
    </div>
  );
}

/**
 * Generar el comprobante de autorización (solo con el botón). Muestra qué
 * va a incluir: los trabajos autorizados, sin pendientes, rechazados ni
 * cancelados. El backend arma el contenido y no duplica si nada cambió.
 */
function FormularioComprobanteAutorizacion({
  accion,
  orden,
  emitidos,
  ocupado,
  onGenerar,
}: {
  accion: Accion;
  orden: Orden;
  emitidos: DocumentoEmitido[];
  ocupado: boolean;
  onGenerar: () => void;
}) {
  const autorizados = orden.reparaciones_detail.filter(
    (detalle) =>
      detalle.estado_autorizacion === "AUTORIZADO" &&
      detalle.estado !== "CANCELADO",
  );
  const subtotal = autorizados.reduce(
    (suma, detalle) => suma + Number(detalle.precio),
    0,
  );
  // El descuento vigente se calcula sobre todos los trabajos; el
  // comprobante lo aplica sobre lo autorizado (lo arma el backend).
  const descuento = orden.resumen.descuento;
  const anterior = ultimoComprobanteAutorizacion(emitidos);
  return (
    <Seccion titulo="Generar el comprobante de autorización" accion={accion}>
      <p style={{ margin: "0 0 0.4rem", fontSize: "0.8rem", color: colores.suave }}>
        Incluye solo lo que el cliente autorizó. No es un comprobante de pago
        y no lleva firma.
        {anterior &&
          ` Reemplaza a ${anterior.id}, que se conserva sin cambios.`}
      </p>
      <ul style={{ margin: "0 0 0.4rem", paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
        {autorizados.map((detalle) => (
          <li key={detalle.id}>
            {detalle.tipo_reparacion_nombre} · {importe(detalle.precio)}
          </li>
        ))}
      </ul>
      <p style={{ margin: "0 0 0.6rem", fontSize: "0.85rem" }}>
        {descuento
          ? `Subtotal autorizado: ${importe(String(subtotal))} · Descuento ${descuento.descripcion} (${descuento.motivo}).`
          : <>Total autorizado: <strong>{importe(String(subtotal))}</strong></>}
      </p>
      <Boton disabled={ocupado} onClick={onGenerar}>
        Generar comprobante de autorización
      </Boton>
    </Seccion>
  );
}

/**
 * Ingreso inicial de Cliente Externo: un solo botón confirma la recepción
 * del equipo, registra que el cliente autorizó los trabajos cargados y
 * genera el comprobante. Si falta información obligatoria lo dice antes
 * (el backend igual lo valida). Generarlo no es enviarlo: después se
 * descarga o se comparte por WhatsApp, y nada registra que el cliente lo
 * recibió o lo firmó.
 */
function FormularioComprobanteIngreso({
  accion,
  orden,
  ocupado,
  onGenerar,
}: {
  accion: Accion;
  orden: Orden;
  ocupado: boolean;
  onGenerar: (canal: CanalComunicacion, checkin: boolean | null) => void;
}) {
  const [canal, setCanal] = useState<CanalComunicacion>("PRESENCIAL");
  const [eleccionCheckin, setEleccionCheckin] = useState<"" | "si" | "no">("");
  const trabajos = orden.reparaciones_detail.filter(
    (detalle) => detalle.estado !== "CANCELADO",
  );
  const { resumen } = orden;
  const checkin = orden.recepcion?.datos.checkin;
  // Si el ingreso no registra el check-in (por ejemplo, una Orden anterior
  // con la recepción ya confirmada), se indica acá y viaja con el
  // comprobante. Con el estado físico y los trabajos, es lo único que
  // puede faltar.
  const pideCheckin = checkin === null || checkin === undefined;
  const conEstado = Boolean(orden.recepcion?.datos.estado_fisico);
  const habilitado =
    !ocupado &&
    (accion.bloqueo === null ||
      (pideCheckin && eleccionCheckin !== "" && conEstado));
  return (
    <Seccion titulo="Generar el comprobante de ingreso y autorización" accion={accion}>
      <p style={{ margin: "0 0 0.4rem", fontSize: "0.8rem", color: colores.suave }}>
        Confirma que el equipo quedó en el local, registra que el cliente
        autorizó estos trabajos y genera un único comprobante para
        compartirle. No es un comprobante de pago.
      </p>
      <ul style={{ margin: "0 0 0.4rem", paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
        {trabajos.map((detalle) => (
          <li key={detalle.id}>
            {detalle.tipo_reparacion_nombre} · {importe(detalle.precio)}
          </li>
        ))}
      </ul>
      {resumen.descuento && (
        <p style={{ margin: "0 0 0.2rem", fontSize: "0.85rem" }}>
          Subtotal {importe(resumen.subtotal)} · Descuento{" "}
          {resumen.descuento.descripcion} (−{importe(resumen.descuento_aplicado)}
          , {resumen.descuento.motivo})
        </p>
      )}
      <p style={{ margin: "0 0 0.4rem", fontSize: "0.85rem" }}>
        Total autorizado: <strong>{importe(resumen.total)}</strong>
        {checkin !== null && checkin !== undefined && (
          <span style={{ color: colores.suave }}>
            {" "}
            · Check-in {checkin ? "realizado (90 días)" : "no realizado (30 días)"}
          </span>
        )}
      </p>
      <Campo etiqueta="El cliente autorizó">
        <select
          value={canal}
          disabled={ocupado}
          onChange={(evento) => setCanal(evento.target.value as CanalComunicacion)}
          style={estiloInput}
        >
          {CANALES.map((opcion) => (
            <option key={opcion} value={opcion}>
              {etiqueta(CANAL, opcion)}
            </option>
          ))}
        </select>
      </Campo>
      {pideCheckin && (
        <CampoCheckin
          valor={eleccionCheckin}
          deshabilitado={ocupado}
          onCambiar={setEleccionCheckin}
        />
      )}
      {accion.bloqueo && !habilitado && (
        <p role="alert" style={{ margin: "0 0 0.5rem", fontSize: "0.85rem", color: colores.alerta }}>
          {accion.bloqueo}.
        </p>
      )}
      <Boton
        disabled={!habilitado}
        onClick={() =>
          onGenerar(
            canal,
            pideCheckin && eleccionCheckin !== "" ? eleccionCheckin === "si" : null,
          )
        }
      >
        Generar comprobante de ingreso y autorización
      </Boton>
    </Seccion>
  );
}

/**
 * «Descargar PDF» y «Compartir por WhatsApp» de un comprobante emitido.
 * Compartir no registra nada: no prueba que el cliente lo recibió.
 */
function AccionesPdf({ documento }: { documento: DocumentoEmitido }) {
  const [trabajando, setTrabajando] = useState(false);
  const [aviso, setAviso] = useState<ReactNode>(null);
  const nombre = `${documento.id}.pdf`;
  const contenido = documento.contenido as
    | ContenidoAutorizacion
    | ContenidoIngreso;

  const conPdf = async (usar: (pdf: Blob) => Promise<void> | void) => {
    setTrabajando(true);
    setAviso(null);
    try {
      await usar(await api.obtenerPdfDocumento(documento.orden_id, documento.id));
    } catch {
      setAviso("No se pudo obtener el PDF. Probá de nuevo.");
    } finally {
      setTrabajando(false);
    }
  };

  const compartir = () =>
    conPdf(async (pdf) => {
      const resultado = await compartirPorWhatsapp({
        pdf,
        nombre,
        mensaje: mensajeComprobante(contenido),
        telefono: telefonoParaWhatsapp(contenido.cliente?.telefono),
      });
      setAviso(textoCompartir(resultado, nombre));
    });

  return (
    <>
      <Boton
        variante="secundario"
        disabled={trabajando}
        onClick={() =>
          void conPdf((pdf) => {
            descargarArchivo(pdf, nombre);
            setAviso(`Se descargó ${nombre}.`);
          })
        }
      >
        Descargar PDF
      </Boton>
      <Boton variante="secundario" disabled={trabajando} onClick={() => void compartir()}>
        Compartir por WhatsApp
      </Boton>
      {aviso && (
        <span
          role="status"
          style={{ flexBasis: "100%", fontSize: "0.8rem", color: colores.suave }}
        >
          {aviso}
        </span>
      )}
    </>
  );
}

function textoCompartir(resultado: ResultadoCompartir, nombre: string): ReactNode {
  if (resultado.forma === "menu") {
    return "Se abrió el menú para compartir. Confirmá en WhatsApp que se envió: el sistema no lo registra.";
  }
  if (resultado.forma === "cancelado") {
    return "No se compartió.";
  }
  return (
    <>
      Se descargó {nombre} y {resultado.abierto ? "se abrió" : "se preparó"}{" "}
      WhatsApp con el mensaje: adjuntá el PDF antes de enviarlo.{" "}
      <a href={resultado.enlace} target="_blank" rel="noopener noreferrer">
        Abrir WhatsApp
      </a>
    </>
  );
}

function FormularioReemision({
  accion,
  actor,
  ocupado,
  onEmitir,
}: {
  accion: Parameters<typeof habilitada>[0];
  actor: Usuario | null;
  ocupado: boolean;
  onEmitir: (motivo: string | null) => void;
}) {
  const [motivo, setMotivo] = useState("");
  const deshabilitado = !habilitada(accion, actor) || ocupado;
  return (
    <Seccion titulo="Nueva versión del comprobante de recepción" accion={accion} actor={actor}>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Emite una versión con los datos vigentes (por ejemplo, tras corregir
        el ingreso o confirmar la recepción). La anterior se conserva. Si
        nada cambió, no se crea otra.
      </p>
      <Campo etiqueta="Motivo de la nueva versión">
        <input
          value={motivo}
          disabled={deshabilitado}
          onChange={(evento) => setMotivo(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Boton
        variante="secundario"
        disabled={deshabilitado || !motivo.trim()}
        onClick={() => onEmitir(motivo.trim())}
      >
        Emitir nueva versión
      </Boton>
    </Seccion>
  );
}

// --- Visor e impresión -------------------------------------------------------

/**
 * Hoja A4 sobre la página. Se monta en `body` (fuera de la app): al
 * imprimir se oculta todo lo demás, y la barra de botones también.
 */
const ESTILO_IMPRESION = `
@page { size: A4; margin: 14mm; }
@media print {
  body > *:not(.visor-documento) { display: none !important; }
  .visor-documento {
    position: static !important;
    background: none !important;
    padding: 0 !important;
    overflow: visible !important;
  }
  .visor-controles { display: none !important; }
  .hoja-documento {
    box-shadow: none !important;
    border: none !important;
    margin: 0 !important;
    padding: 0 !important;
    width: auto !important;
    min-height: 0 !important;
  }
  .hoja-documento table { page-break-inside: auto; }
  .hoja-documento tr { page-break-inside: avoid; }
}
`;

function VisorDocumento({
  visible,
  onCerrar,
}: {
  visible: Visible;
  onCerrar: () => void;
}) {
  useEffect(() => {
    const alPresionar = (evento: KeyboardEvent) => {
      if (evento.key === "Escape") onCerrar();
    };
    window.addEventListener("keydown", alPresionar);
    return () => window.removeEventListener("keydown", alPresionar);
  }, [onCerrar]);

  const contenido =
    visible.clase === "emitido" ? visible.documento.contenido : visible.contenido;

  return createPortal(
    <div
      className="visor-documento"
      role="dialog"
      aria-modal="true"
      aria-label={tituloDe(contenido)}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        background: "rgba(30, 30, 30, 0.55)",
        overflowY: "auto",
        padding: "1rem",
        boxSizing: "border-box",
      }}
    >
      <style>{ESTILO_IMPRESION}</style>
      <div
        className="visor-controles"
        style={{
          display: "flex",
          justifyContent: "center",
          gap: "0.5rem",
          flexWrap: "wrap",
          marginBottom: "0.75rem",
        }}
      >
        {visible.clase === "emitido" && CON_PDF.has(visible.documento.tipo) ? (
          <AccionesPdf documento={visible.documento} />
        ) : (
          <Boton onClick={() => window.print()}>Imprimir / guardar PDF</Boton>
        )}
        <Boton variante="secundario" onClick={onCerrar}>
          Cerrar
        </Boton>
      </div>
      <HojaDocumento visible={visible} />
    </div>,
    document.body,
  );
}

function HojaDocumento({ visible }: { visible: Visible }) {
  const previa = visible.clase === "previa";
  const contenido =
    visible.clase === "emitido" ? visible.documento.contenido : visible.contenido;
  const { empresa } = contenido;
  const datosEmpresa = [
    empresa.razon_social,
    empresa.cuit && `CUIT ${empresa.cuit}`,
    empresa.direccion,
    empresa.telefono,
    empresa.email,
  ].filter(Boolean);

  return (
    <article
      className="hoja-documento"
      style={{
        position: "relative",
        width: "min(210mm, 100%)",
        minHeight: "min(297mm, 100%)",
        margin: "0 auto",
        padding: "clamp(14px, 5vw, 14mm)",
        boxSizing: "border-box",
        background: "#fff",
        color: "#111",
        boxShadow: "0 2px 18px rgba(0,0,0,0.25)",
        fontSize: "10.5pt",
        lineHeight: 1.4,
      }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: "1rem",
          flexWrap: "wrap",
          borderBottom: "2px solid #111",
          paddingBottom: "0.6rem",
          marginBottom: "0.8rem",
        }}
      >
        <div>
          <div style={{ fontSize: "15pt", fontWeight: 700 }}>{empresa.nombre}</div>
          {datosEmpresa.map((dato) => (
            <div key={dato as string} style={{ fontSize: "9pt" }}>
              {dato}
            </div>
          ))}
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: "13pt", fontWeight: 700 }}>{tituloDe(contenido)}</div>
          <div>Orden {contenido.orden_id}</div>
          {visible.clase === "emitido" ? (
            <div style={{ fontSize: "9pt" }}>
              N.º {visible.documento.id} · versión {visible.documento.version}
              <br />
              Emitido el {fechaHora(visible.documento.fecha_emision)}
            </div>
          ) : (
            <div style={{ fontSize: "9pt", fontWeight: 700 }}>
              VISTA PREVIA · NO EMITIDO
            </div>
          )}
        </div>
      </header>
      {previa && (
        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            pointerEvents: "none",
            fontSize: "40pt",
            fontWeight: 700,
            color: "rgba(180, 35, 24, 0.12)",
            transform: "rotate(-24deg)",
          }}
        >
          VISTA PREVIA
        </div>
      )}

      <Partes contenido={contenido} />
      {contenido.tipo === "COMPROBANTE_RECEPCION" && (
        <CuerpoRecepcion contenido={contenido} />
      )}
      {contenido.tipo === "COMPROBANTE_ENTREGA" && (
        <CuerpoEntrega contenido={contenido} />
      )}
      {contenido.tipo === "GARANTIA" && <CuerpoGarantia contenido={contenido} />}
      {contenido.tipo === "COMPROBANTE_INGRESO" && (
        <CuerpoIngreso contenido={contenido} />
      )}
      {contenido.tipo === "COMPROBANTE_AUTORIZACION" && (
        <CuerpoAutorizacion
          contenido={contenido}
          reemplazaA={
            visible.clase === "emitido" ? visible.documento.reemplaza_a : null
          }
          motivo={visible.clase === "emitido" ? visible.documento.motivo : null}
        />
      )}
    </article>
  );
}

// --- Partes de la hoja ---------------------------------------------------------

function fechaHora(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("es-AR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "2027-01-17" -> "17/01/2027" (fecha calendario: sin zona horaria). */
function fechaDia(iso: string | null): string {
  if (!iso) return "—";
  const [anio, mes, dia] = iso.split("-");
  return `${dia}/${mes}/${anio}`;
}

function Titulo({ children }: { children: ReactNode }) {
  return (
    <h4
      style={{
        margin: "0.9rem 0 0.35rem",
        fontSize: "10pt",
        textTransform: "uppercase",
        letterSpacing: "0.04em",
        borderBottom: "1px solid #999",
      }}
    >
      {children}
    </h4>
  );
}

function Dato({ etiqueta, valor }: { etiqueta: string; valor: ReactNode }) {
  return (
    <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
      <span style={{ color: "#555", minWidth: "9.5rem" }}>{etiqueta}:</span>
      <span style={{ flex: "1 1 12rem", overflowWrap: "anywhere" }}>{valor}</span>
    </div>
  );
}

function Tabla({
  columnas,
  filas,
}: {
  columnas: string[];
  filas: ReactNode[][];
}) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "9.5pt" }}>
        <thead>
          <tr>
            {columnas.map((columna) => (
              <th
                key={columna}
                style={{
                  textAlign: "left",
                  borderBottom: "1px solid #111",
                  padding: "0.2rem 0.4rem 0.2rem 0",
                }}
              >
                {columna}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filas.map((fila, indice) => (
            <tr key={indice}>
              {fila.map((celda, columna) => (
                <td
                  key={columna}
                  style={{
                    borderBottom: "1px solid #ddd",
                    padding: "0.25rem 0.4rem 0.25rem 0",
                    verticalAlign: "top",
                  }}
                >
                  {celda}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Cliente (o Gestión RT), equipo y, en una garantía RMA, su origen. */
function Partes({ contenido }: { contenido: ContenidoDocumento }) {
  const { cliente, equipo } = contenido;
  return (
    <>
      <Titulo>Cliente y equipo</Titulo>
      {cliente ? (
        <Dato
          etiqueta="Cliente"
          valor={[cliente.nombre, cliente.telefono, cliente.email]
            .filter(Boolean)
            .join(" · ")}
        />
      ) : (
        <Dato etiqueta="Equipo interno" valor={`Gestión RT ${contenido.referencia_rt ?? ""}`} />
      )}
      <Dato etiqueta="Equipo" valor={`${equipo.marca} ${equipo.modelo}`} />
      <Dato etiqueta="IMEI" valor={equipo.imei ?? "—"} />
      <Dato etiqueta="N.º de serie" valor={equipo.numero_serie ?? "—"} />
      <Dato etiqueta="Fecha de ingreso" valor={fechaHora(contenido.fecha_ingreso)} />
      {contenido.orden_origen_id && (
        <Dato
          etiqueta="Garantía de la Orden"
          valor={`${contenido.orden_origen_id} · reclamo: ${contenido.detalles_reclamados
            .map((detalle) => `${detalle.detalle_id} ${detalle.nombre}`)
            .join(", ")}`}
        />
      )}
    </>
  );
}

const ETIQUETA_RECEPCION_FISICA: Record<string, string> = {
  PENDIENTE_CONFIRMACION: "Pendiente de confirmación",
  SIN_REGISTRO: "Sin registro",
  EN_CUSTODIA: "Confirmada: el equipo quedó en el local",
  ENTREGADO: "Entregado",
  DEVUELTO: "Devuelto",
  NO_RECIBIDO: "No recibido",
};

function CuerpoRecepcion({ contenido }: { contenido: ContenidoRecepcion }) {
  return (
    <>
      <Titulo>Recepción</Titulo>
      <Dato etiqueta="Falla declarada" valor={contenido.equipo.falla_reportada} />
      <Dato etiqueta="Estado físico" valor={contenido.estado_fisico ?? "No registrado"} />
      <Dato
        etiqueta="Accesorios recibidos"
        valor={contenido.accesorios.length ? contenido.accesorios.join(", ") : "Ninguno"}
      />
      <Dato etiqueta="Observaciones" valor={contenido.observaciones ?? "—"} />
      {contenido.notas.length > 0 && (
        <Dato etiqueta="Observaciones posteriores" valor={contenido.notas.join(" · ")} />
      )}
      <Dato
        etiqueta="Registró"
        valor={`${contenido.registrado_por?.nombre ?? "—"} · ${fechaHora(contenido.registrado_en)}`}
      />
      <Dato
        etiqueta="Recepción física"
        valor={`${ETIQUETA_RECEPCION_FISICA[contenido.recepcion_fisica] ?? contenido.recepcion_fisica}${
          contenido.confirmada_por
            ? ` (${contenido.confirmada_por.nombre}, ${fechaHora(contenido.confirmada_en)})`
            : ""
        }`}
      />
      <p
        style={{
          margin: "1rem 0 0",
          padding: "0.5rem 0.6rem",
          border: "1px solid #999",
          fontSize: "9pt",
        }}
      >
        {contenido.leyenda}
      </p>
      <Firmas izquierda="Recibió por la empresa" derecha="Cliente (firma y aclaración)" />
    </>
  );
}

/** Subtotal y descuento (si hay) y el total, al pie de los trabajos. */
function Totales({
  subtotal,
  descuento,
  total,
  etiquetaTotal,
}: {
  subtotal: string | null | undefined;
  descuento: DescuentoEnDocumento | null | undefined;
  total: string;
  etiquetaTotal: string;
}) {
  return (
    <>
      {descuento && (
        <>
          <Dato etiqueta="Subtotal" valor={importe(subtotal ?? total)} />
          <Dato
            etiqueta={`Descuento (${descuento.descripcion})`}
            valor={`− ${importe(descuento.importe)} · ${descuento.motivo}`}
          />
        </>
      )}
      <Dato etiqueta={etiquetaTotal} valor={<strong>{importe(total)}</strong>} />
    </>
  );
}

/**
 * Ingreso y autorización: cómo se recibió el equipo (nunca notas
 * internas) y lo autorizado con su precio. Sin firma: no registra que el
 * cliente lo recibió.
 */
function CuerpoIngreso({ contenido }: { contenido: ContenidoIngreso }) {
  return (
    <>
      <Titulo>Recepción del equipo</Titulo>
      <Dato etiqueta="Falla declarada" valor={contenido.equipo.falla_reportada} />
      <Dato etiqueta="Estado físico" valor={contenido.estado_fisico ?? "No registrado"} />
      <Dato
        etiqueta="Accesorios recibidos"
        valor={contenido.accesorios.length ? contenido.accesorios.join(", ") : "Ninguno"}
      />
      {contenido.checkin !== null && (
        <Dato
          etiqueta="Check-in"
          valor={contenido.checkin ? "Realizado" : "No realizado"}
        />
      )}
      <Dato etiqueta="Observaciones" valor={contenido.observaciones ?? "—"} />
      {contenido.notas.length > 0 && (
        <Dato etiqueta="Observaciones posteriores" valor={contenido.notas.join(" · ")} />
      )}
      <Dato
        etiqueta="Recibido"
        valor={`${fechaHora(contenido.confirmada_en)}${
          contenido.confirmada_por ? ` · ${contenido.confirmada_por.nombre}` : ""
        }`}
      />
      <Titulo>Trabajos autorizados por el cliente</Titulo>
      <Tabla
        columnas={["Trabajo", "Autorización", "Precio"]}
        filas={contenido.trabajos.map((trabajo) => [
          trabajo.nombre,
          `${fechaHora(trabajo.autorizado_en)} · ${etiqueta(CANAL, trabajo.canal)}`,
          importe(trabajo.precio),
        ])}
      />
      <Totales
        subtotal={contenido.subtotal}
        descuento={contenido.descuento}
        total={contenido.total}
        etiquetaTotal="Total autorizado"
      />
      <p
        style={{
          margin: "1rem 0 0",
          padding: "0.5rem 0.6rem",
          border: "1px solid #999",
          fontSize: "9pt",
        }}
      >
        <strong>No es un comprobante de pago.</strong> {contenido.leyenda}
      </p>
    </>
  );
}

/** Lo autorizado y su total: sin firma, no es un comprobante de pago. */
function CuerpoAutorizacion({
  contenido,
  reemplazaA,
  motivo,
}: {
  contenido: ContenidoAutorizacion;
  reemplazaA: string | null;
  motivo: string | null;
}) {
  return (
    <>
      <Dato etiqueta="Falla declarada" valor={contenido.equipo.falla_reportada} />
      <Titulo>Trabajos autorizados por el cliente</Titulo>
      <Tabla
        columnas={["Trabajo", "Autorización", "Precio"]}
        filas={contenido.trabajos.map((trabajo) => [
          trabajo.nombre,
          `${fechaHora(trabajo.autorizado_en)} · ${etiqueta(CANAL, trabajo.canal)}`,
          importe(trabajo.precio),
        ])}
      />
      <Totales
        subtotal={contenido.subtotal_autorizado}
        descuento={contenido.descuento}
        total={contenido.total_autorizado}
        etiquetaTotal="Total autorizado"
      />
      {reemplazaA && (
        <p style={{ margin: "0.6rem 0 0", fontSize: "9pt", color: "#555" }}>
          Esta versión reemplaza a {reemplazaA}, que se conserva sin cambios.
          {motivo ? ` ${motivo}` : ""}
        </p>
      )}
      <p
        style={{
          margin: "1rem 0 0",
          padding: "0.5rem 0.6rem",
          border: "1px solid #999",
          fontSize: "9pt",
        }}
      >
        <strong>No es un comprobante de pago.</strong> {contenido.leyenda}
      </p>
    </>
  );
}

function CuerpoEntrega({ contenido }: { contenido: ContenidoEntrega }) {
  const devolucion = contenido.tipo_entrega === "DEVOLUCION_SIN_REPARACION";
  return (
    <>
      <Titulo>{devolucion ? "Devolución" : "Entrega"}</Titulo>
      <Dato etiqueta="Resultado" valor={contenido.resultado} />
      <Dato
        etiqueta={devolucion ? "Fecha de devolución" : "Fecha de entrega"}
        valor={contenido.fecha_entrega ? fechaHora(contenido.fecha_entrega) : "Al registrar la entrega"}
      />
      <Dato
        etiqueta="Retira"
        valor={
          contenido.recibido_por
            ? `${contenido.recibido_por}${
                contenido.identificacion_receptor
                  ? ` · ${contenido.identificacion_receptor}`
                  : ""
              }`
            : "—"
        }
      />
      <Dato etiqueta="Entregó" valor={contenido.entregado_por?.nombre ?? "—"} />
      {contenido.observaciones_entrega && (
        <Dato etiqueta="Observaciones" valor={contenido.observaciones_entrega} />
      )}

      <Titulo>Trabajos realizados</Titulo>
      {contenido.trabajos_realizados.length ? (
        <Tabla
          columnas={contenido.cobrable ? ["Detalle", "Trabajo", "Importe"] : ["Detalle", "Trabajo"]}
          filas={contenido.trabajos_realizados.map((trabajo) => [
            trabajo.detalle_id,
            trabajo.nombre,
            ...(contenido.cobrable ? [importe(trabajo.precio ?? "0")] : []),
          ])}
        />
      ) : (
        <p style={{ margin: 0 }}>Ninguno: el equipo se devuelve sin reparar.</p>
      )}
      {contenido.trabajos_cancelados.length > 0 && (
        <>
          <Titulo>Trabajos cancelados (no realizados ni cobrados)</Titulo>
          <Tabla
            columnas={["Detalle", "Trabajo", "Motivo"]}
            filas={contenido.trabajos_cancelados.map((trabajo) => [
              trabajo.detalle_id,
              trabajo.nombre,
              trabajo.motivo ?? "—",
            ])}
          />
        </>
      )}

      <Titulo>Cobro</Titulo>
      {contenido.cobrable ? (
        <>
          <Totales
            subtotal={contenido.subtotal}
            descuento={contenido.descuento}
            total={contenido.total ?? "0"}
            etiquetaTotal="Total final"
          />
          {contenido.pagos.map((pago) => (
            <Dato
              key={pago.id}
              etiqueta={`Pago ${pago.tipo_pago.toLowerCase()}`}
              valor={`${importe(pago.monto)} · ${pago.medio} · ${fechaHora(pago.fecha)}${
                pago.referencia ? ` · ref. ${pago.referencia}` : ""
              }`}
            />
          ))}
          {contenido.devoluciones_dinero.map((devolucionDinero) => (
            <Dato
              key={devolucionDinero.id}
              etiqueta="Dinero devuelto"
              valor={`${importe(devolucionDinero.monto)} · ${devolucionDinero.medio} · ${fechaHora(devolucionDinero.fecha)} · ${devolucionDinero.motivo}`}
            />
          ))}
          <Dato
            etiqueta="Saldo final"
            valor={
              Number(contenido.saldo) < 0
                ? `${importe(String(-Number(contenido.saldo)))} a favor del cliente (pendiente de devolver)`
                : importe(contenido.saldo ?? "0")
            }
          />
        </>
      ) : (
        <p style={{ margin: 0 }}>
          Sin cargo para el cliente
          {contenido.orden_origen_id ? " (garantía)" : ""}.
        </p>
      )}
      <Firmas
        izquierda="Entregó por la empresa"
        derecha="Recibí conforme (firma y aclaración)"
      />
    </>
  );
}

function CuerpoGarantia({ contenido }: { contenido: ContenidoGarantia }) {
  return (
    <>
      <Titulo>Cobertura</Titulo>
      <Dato
        etiqueta="Inicio de la garantía"
        valor={
          contenido.fecha_inicio
            ? `${fechaHora(contenido.fecha_inicio)} (entrega del equipo)`
            : "Desde la entrega del equipo"
        }
      />
      <Tabla
        columnas={["Detalle", "Trabajo cubierto", "Plazo", "Vence"]}
        filas={contenido.coberturas.map((cobertura) => [
          cobertura.detalle_id,
          cobertura.nombre,
          cobertura.garantia_dias > 0 ? `${cobertura.garantia_dias} días` : "Sin garantía",
          cobertura.garantia_dias > 0
            ? cobertura.vence
              ? fechaDia(cobertura.vence)
              : "A contar desde la entrega"
            : "—",
        ])}
      />
      <p style={{ margin: "0.6rem 0 0", fontSize: "9pt" }}>
        Cubre únicamente los trabajos detallados, cada uno por su plazo,
        contado desde la entrega del equipo. Los trabajos cancelados o no
        realizados no tienen garantía.
      </p>
      {contenido.condiciones && (
        <>
          <Titulo>Condiciones</Titulo>
          <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{contenido.condiciones}</p>
        </>
      )}
      {contenido.observaciones_entrega && (
        <Dato etiqueta="Observaciones" valor={contenido.observaciones_entrega} />
      )}
    </>
  );
}

function Firmas({ izquierda, derecha }: { izquierda: string; derecha: string }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: "2rem",
        marginTop: "2.5rem",
        fontSize: "9pt",
      }}
    >
      {[izquierda, derecha].map((texto) => (
        <div key={texto} style={{ flex: 1, borderTop: "1px solid #111", paddingTop: "0.2rem" }}>
          {texto}
        </div>
      ))}
    </div>
  );
}
