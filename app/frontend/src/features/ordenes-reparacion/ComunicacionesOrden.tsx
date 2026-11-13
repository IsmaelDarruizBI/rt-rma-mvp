/**
 * Comunicaciones de la Orden (DEC-MI-08): WhatsApp asistido.
 *
 * 1. Se elige una plantilla y el sistema prepara el mensaje con los datos
 *    de la Orden. El usuario lo revisa y puede editarlo.
 * 2. «Abrir WhatsApp» registra el intento y abre WhatsApp con el mensaje.
 *    Abrir no es enviar.
 * 3. El usuario confirma a mano si lo envió o no. Nunca hay «entregado» ni
 *    «leído»: ningún proveedor lo prueba.
 *
 * También muestra y registra el consentimiento del cliente: lo comercial
 * exige un consentimiento expreso; la preferencia del cliente se respeta.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/comunicaciones";
import type {
  Consentimientos,
  Finalidad,
  MensajePreparado,
  PlantillaMensaje,
} from "../../api/comunicaciones";
import { Boton, Campo, colores, estiloInput, fechaCorta } from "../../components/ui";
import { puede } from "../../lib/roles";
import type { Orden, Usuario } from "../../types/api";
import { estadoDeComunicacion, textoConsentimiento } from "./comunicaciones";
import { nombreDeUsuario } from "./DetalleOrden";
import { enlaceWhatsapp, telefonoParaWhatsapp } from "./whatsapp";

const POR_DEFECTO = ["RECEPCION", "COORDINADOR_RMA", "ADMINISTRADOR"];

const mensajeDe = (causa: unknown) =>
  causa instanceof Error ? causa.message : String(causa);

export function ComunicacionesOrden({
  orden,
  actor,
  usuarios,
  ocupado,
  ejecutarComando,
}: {
  orden: Orden;
  actor: Usuario | null;
  usuarios: Usuario[];
  ocupado: boolean;
  /** Ejecuta un comando que devuelve la Orden y la refresca. */
  ejecutarComando: (comando: () => Promise<Orden>) => Promise<boolean>;
}) {
  const [plantillas, setPlantillas] = useState<PlantillaMensaje[]>([]);
  const [codigo, setCodigo] = useState("");
  const [preparado, setPreparado] = useState<MensajePreparado | null>(null);
  const [mensaje, setMensaje] = useState("");
  const [error, setError] = useState<string | null>(null);
  const habilitado = puede(actor, "COMUNICACION_ENVIAR", POR_DEFECTO);
  const idActor = actor?.id ?? "";

  useEffect(() => {
    api
      .listarPlantillas()
      .then((datos) => setPlantillas(datos.plantillas.filter((p) => p.activa)))
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, []);

  const preparar = (elegida: string) => {
    setCodigo(elegida);
    setPreparado(null);
    setError(null);
    if (!elegida) return;
    api
      .prepararMensaje(orden.id, elegida)
      .then((datos) => {
        setPreparado(datos);
        setMensaje(datos.mensaje);
      })
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  };

  const abrir = () => {
    if (!preparado) return;
    const texto = mensaje.trim();
    // La ventana se abre en el clic (si no, el navegador la bloquea) y
    // recibe la dirección cuando el intento quedó registrado.
    const ventana = window.open("", "_blank");
    if (ventana) ventana.opener = null;
    void ejecutarComando(() =>
      api.registrarIntento(
        orden.id,
        idActor,
        preparado.plantilla.codigo,
        texto,
        preparado.destinatario,
      ),
    ).then((registrado) => {
      if (!ventana) return;
      if (!registrado) {
        ventana.close();
        return;
      }
      ventana.location.href = enlaceWhatsapp(
        telefonoParaWhatsapp(preparado.destinatario),
        texto,
      );
      setCodigo("");
      setPreparado(null);
    });
  };

  const comunicaciones = orden.comunicaciones ?? [];
  const pendientes = /\{[a-z_]+\}/.test(mensaje);

  return (
    <div>
      {error && (
        <p role="alert" style={{ color: colores.error, fontSize: "0.85rem" }}>
          {error}
        </p>
      )}
      {comunicaciones.length === 0 ? (
        <p style={{ margin: "0 0 0.6rem", fontSize: "0.85rem", color: colores.suave }}>
          Todavía no se preparó ningún mensaje.
        </p>
      ) : (
        <ul style={{ margin: "0 0 0.8rem", paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
          {comunicaciones.map((comunicacion) => (
            <li key={comunicacion.id} style={{ marginBottom: "0.5rem" }}>
              <strong>{comunicacion.id}</strong> · {fechaCorta(comunicacion.fecha)} ·{" "}
              {nombreDeUsuario(usuarios, comunicacion.usuario_id)}
              {comunicacion.plantilla_codigo ? ` · ${comunicacion.plantilla_codigo}` : ""}
              <div style={{ whiteSpace: "pre-wrap", color: colores.suave }}>
                {comunicacion.mensaje}
              </div>
              <div>{estadoDeComunicacion(comunicacion)}</div>
              {comunicacion.confirmacion === null && habilitado && (
                <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.3rem" }}>
                  <Boton
                    disabled={ocupado}
                    onClick={() =>
                      void ejecutarComando(() =>
                        api.confirmarEnvio(orden.id, comunicacion.id, idActor, true, null),
                      )
                    }
                  >
                    Lo envié
                  </Boton>
                  <Boton
                    variante="secundario"
                    disabled={ocupado}
                    onClick={() =>
                      void ejecutarComando(() =>
                        api.confirmarEnvio(orden.id, comunicacion.id, idActor, false, null),
                      )
                    }
                  >
                    No se envió
                  </Boton>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {habilitado && orden.cliente && (
        <div style={{ maxWidth: 560 }}>
          <Campo etiqueta="Plantilla">
            <select
              value={codigo}
              onChange={(evento) => preparar(evento.target.value)}
              disabled={ocupado}
              style={estiloInput}
            >
              <option value="">Elegir…</option>
              {plantillas.map((plantilla) => (
                <option key={plantilla.codigo} value={plantilla.codigo}>
                  {plantilla.nombre}
                  {plantilla.finalidad === "COMERCIAL" ? " (comercial)" : ""}
                </option>
              ))}
            </select>
          </Campo>
          {preparado && (
            <>
              <Campo etiqueta="Mensaje (revisalo y editalo antes de abrir WhatsApp)">
                <textarea
                  value={mensaje}
                  onChange={(evento) => setMensaje(evento.target.value)}
                  rows={5}
                  disabled={ocupado}
                  style={{ ...estiloInput, fontFamily: "inherit" }}
                />
              </Campo>
              {preparado.faltantes.length > 0 && (
                <p role="status" style={{ color: colores.alerta, fontSize: "0.85rem" }}>
                  Sin dato para:{" "}
                  {preparado.faltantes.map((v) => `{${v}}`).join(", ")}. Completalo en el
                  mensaje.
                </p>
              )}
              {preparado.impedimento && (
                <p role="alert" style={{ color: colores.error, fontSize: "0.85rem" }}>
                  {preparado.impedimento}
                </p>
              )}
              <p style={{ fontSize: "0.8rem", color: colores.suave, margin: "0 0 0.5rem" }}>
                Destinatario: {preparado.destinatario ?? "sin teléfono"}. Abrir WhatsApp
                no es enviar: después confirmá si lo enviaste.
              </p>
              <Boton
                disabled={
                  ocupado ||
                  mensaje.trim() === "" ||
                  pendientes ||
                  preparado.impedimento !== null
                }
                onClick={abrir}
              >
                Abrir WhatsApp
              </Boton>
            </>
          )}
        </div>
      )}

      {orden.cliente && (
        <ConsentimientoCliente
          clienteId={orden.cliente.id}
          actor={actor}
          usuarios={usuarios}
        />
      )}
    </div>
  );
}

const FINALIDADES: { valor: Finalidad; texto: string }[] = [
  { valor: "OPERATIVA", texto: "Avisos de la Orden (operativos)" },
  { valor: "COMERCIAL", texto: "Mensajes comerciales (marketing)" },
];

export function ConsentimientoCliente({
  clienteId,
  actor,
  usuarios,
}: {
  clienteId: string;
  actor: Usuario | null;
  usuarios: Usuario[];
}) {
  const [estado, setEstado] = useState<Consentimientos | null>(null);
  const [finalidad, setFinalidad] = useState<Finalidad>("COMERCIAL");
  const [origen, setOrigen] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const habilitado = puede(actor, "CONSENTIMIENTO_REGISTRAR", POR_DEFECTO);

  const cargar = useCallback(() => {
    api
      .leerConsentimientos(clienteId)
      .then(setEstado)
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, [clienteId]);
  useEffect(cargar, [cargar]);

  const registrar = (otorgado: boolean) => {
    if (!actor) return;
    setOcupado(true);
    setError(null);
    api
      .registrarConsentimiento(clienteId, actor.id, finalidad, otorgado, origen.trim())
      .then((nuevo) => {
        setEstado(nuevo);
        setOrigen("");
      })
      .catch((causa: unknown) => setError(mensajeDe(causa)))
      .finally(() => setOcupado(false));
  };

  return (
    <section aria-label="Consentimiento del cliente" style={{ marginTop: "1rem" }}>
      <h4 style={{ margin: "0 0 0.4rem" }}>Consentimiento por WhatsApp</h4>
      {error && (
        <p role="alert" style={{ color: colores.error, fontSize: "0.85rem" }}>
          {error}
        </p>
      )}
      {estado && (
        <ul style={{ margin: "0 0 0.5rem", paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
          {FINALIDADES.map((f) => (
            <li key={f.valor}>
              {f.texto}: <strong>{textoConsentimiento(estado.vigentes[f.valor])}</strong>
            </li>
          ))}
        </ul>
      )}
      {estado && estado.historial.length > 0 && (
        <details style={{ fontSize: "0.8rem", marginBottom: "0.5rem" }}>
          <summary>Historial</summary>
          <ul style={{ paddingLeft: "1.1rem" }}>
            {estado.historial.map((registro, indice) => (
              <li key={`${registro.fecha}-${indice}`}>
                {fechaCorta(registro.fecha)} · {registro.finalidad} ·{" "}
                {registro.otorgado ? "otorgó" : "rechazó o revocó"} · {registro.origen} ·{" "}
                {nombreDeUsuario(usuarios, registro.usuario_id)}
              </li>
            ))}
          </ul>
        </details>
      )}
      {habilitado && (
        <div style={{ maxWidth: 420 }}>
          <Campo etiqueta="Finalidad">
            <select
              value={finalidad}
              onChange={(evento) => setFinalidad(evento.target.value as Finalidad)}
              disabled={ocupado}
              style={estiloInput}
            >
              {FINALIDADES.map((f) => (
                <option key={f.valor} value={f.valor}>
                  {f.texto}
                </option>
              ))}
            </select>
          </Campo>
          <Campo etiqueta="Origen (cómo se obtuvo, obligatorio)">
            <input
              value={origen}
              onChange={(evento) => setOrigen(evento.target.value)}
              disabled={ocupado}
              style={estiloInput}
            />
          </Campo>
          <div style={{ display: "flex", gap: "0.4rem" }}>
            <Boton disabled={ocupado || origen.trim() === ""} onClick={() => registrar(true)}>
              Registrar que lo otorga
            </Boton>
            <Boton
              variante="secundario"
              disabled={ocupado || origen.trim() === ""}
              onClick={() => registrar(false)}
            >
              Registrar que lo rechaza o revoca
            </Boton>
          </div>
        </div>
      )}
    </section>
  );
}
