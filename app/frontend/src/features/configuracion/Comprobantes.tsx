/**
 * Comprobantes (DEC-AJ-09, BF-19): «Datos de la empresa» y «Términos y
 * condiciones». Solo Administración (permiso no configurable de parámetros
 * del sistema); cada cambio queda en la auditoría.
 *
 * - Los datos de la empresa salen en los comprobantes que se emitan
 *   después; los ya emitidos conservan su copia.
 * - Los términos se publican como una versión nueva y completa, vigente
 *   desde ese momento. Las versiones publicadas no se editan ni se borran:
 *   cada comprobante de entrega y garantía imprime la que usó.
 *
 * En la persistencia JSON (demo) son de solo lectura.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/configuracion";
import { Mensajes, mensajeDe, useComando } from "../../components/FormularioModal";
import { Boton, Campo, colores, estiloInput } from "../../components/ui";
import type { TextoLegal, Usuario } from "../../types/api";
import {
  type BorradorTerminos,
  CAMPOS_EMPRESA,
  type FormularioEmpresa,
  borradorDe,
  contenidoDelBorrador,
  datosDeEmpresa,
  empresaCambio,
  faltantesDelBorrador,
  formularioDeEmpresa,
  igualAVigente,
} from "./reglasComprobantes";

const SOLO_LECTURA = "Se configura sobre la base PostgreSQL.";

export function DatosEmpresaAdmin({ actor }: { actor: Usuario }) {
  const [datos, setDatos] = useState<api.EmpresaAdmin | null>(null);
  const [formulario, setFormulario] = useState<FormularioEmpresa | null>(null);
  const { error, setError, aviso, ocupado, ejecutar } = useComando();

  const cargar = useCallback(() => {
    api
      .leerEmpresa()
      .then((leidos) => {
        setDatos(leidos);
        setFormulario(formularioDeEmpresa(leidos.empresa));
      })
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, [setError]);
  useEffect(cargar, [cargar]);

  if (!datos || !formulario) return <Mensajes error={error} aviso={aviso} />;
  const bloqueado = ocupado || !datos.editable;
  const cambio = empresaCambio(datos.empresa, formulario);

  return (
    <section style={{ maxWidth: 560 }}>
      <h3 style={{ margin: "0 0 0.3rem" }}>Datos de la empresa</h3>
      <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.suave }}>
        Salen en los comprobantes que se emitan desde ahora. Los ya emitidos
        conservan los datos con que se entregaron.
      </p>
      <Mensajes error={error} aviso={aviso} />
      {CAMPOS_EMPRESA.map(({ campo, etiqueta, largo }) => (
        <Campo key={campo} etiqueta={campo === "nombre" ? `${etiqueta} *` : etiqueta}>
          {largo ? (
            <textarea
              value={formulario[campo]}
              rows={3}
              onChange={(evento) => setFormulario({ ...formulario, [campo]: evento.target.value })}
              disabled={bloqueado}
              style={{ ...estiloInput, resize: "vertical" }}
            />
          ) : (
            <input
              value={formulario[campo]}
              onChange={(evento) => setFormulario({ ...formulario, [campo]: evento.target.value })}
              disabled={bloqueado}
              style={estiloInput}
            />
          )}
        </Campo>
      ))}
      <Boton
        disabled={bloqueado || !cambio || !formulario.nombre.trim()}
        onClick={() =>
          void ejecutar(
            () => api.guardarEmpresa(actor.id, datosDeEmpresa(formulario)),
            "Se guardaron los datos de la empresa.",
          ).then((guardada) => {
            if (guardada !== undefined) cargar();
          })
        }
      >
        Guardar
      </Boton>
      {!datos.editable && (
        <p style={{ fontSize: "0.8rem", color: colores.suave }}>{SOLO_LECTURA}</p>
      )}
    </section>
  );
}

function fecha(iso: string): string {
  return new Date(iso).toLocaleString("es-AR");
}

export function TerminosCondicionesAdmin({ actor }: { actor: Usuario }) {
  const [datos, setDatos] = useState<api.TerminosAdmin | null>(null);
  const [borrador, setBorrador] = useState<BorradorTerminos | null>(null);
  const [verVersion, setVerVersion] = useState<TextoLegal | null>(null);
  const { error, setError, aviso, ocupado, ejecutar } = useComando();

  const cargar = useCallback(() => {
    api
      .leerTerminos()
      .then((leidos) => {
        setDatos(leidos);
        setBorrador(leidos.vigente ? borradorDe(leidos.vigente) : null);
      })
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, [setError]);
  useEffect(cargar, [cargar]);

  if (!datos) return <Mensajes error={error} aviso={aviso} />;
  const bloqueado = ocupado || !datos.editable;
  const faltantes = borrador ? faltantesDelBorrador(borrador) : [];
  const sinCambios = borrador ? igualAVigente(borrador, datos.vigente) : true;
  const actualizar = (cambios: Partial<BorradorTerminos>) =>
    borrador && setBorrador({ ...borrador, ...cambios });
  const apartado = (indice: number, cambios: Partial<BorradorTerminos["apartados"][number]>) =>
    borrador &&
    actualizar({
      apartados: borrador.apartados.map((a, i) => (i === indice ? { ...a, ...cambios } : a)),
    });

  return (
    <section style={{ display: "grid", gap: "0.8rem", maxWidth: 760 }}>
      <div>
        <h3 style={{ margin: "0 0 0.3rem" }}>Términos y condiciones</h3>
        <p style={{ margin: 0, fontSize: "0.8rem", color: colores.suave }}>
          Se imprimen con el comprobante de entrega y garantía. Cada comprobante
          guarda la versión vigente al emitirlo y la imprime siempre igual. Publicar
          crea una versión nueva: las anteriores no se modifican.
        </p>
      </div>
      <Mensajes error={error} aviso={aviso} />

      <div>
        <h4 style={{ margin: "0 0 0.3rem", fontSize: "0.9rem" }}>Versiones</h4>
        <ul style={{ margin: 0, paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
          {[...datos.versiones].reverse().map((version) => (
            <li key={version.version}>
              Versión {version.version}
              {datos.vigente?.version === version.version && <strong> · vigente</strong>} · desde{" "}
              {fecha(version.vigente_desde)}
              {version.publicado_por ? ` · ${version.publicado_por}` : " · carga inicial"} ·{" "}
              <button
                type="button"
                className="rt-link"
                onClick={() => setVerVersion(verVersion?.version === version.version ? null : version)}
                style={{ background: "none", border: 0, padding: 0, color: colores.acento, cursor: "pointer" }}
              >
                {verVersion?.version === version.version ? "ocultar" : "ver"}
              </button>
            </li>
          ))}
        </ul>
        {verVersion && (
          <ol style={{ fontSize: "0.8rem", margin: "0.5rem 0 0", paddingLeft: "1.3rem" }}>
            {verVersion.contenido.apartados.map((a) => (
              <li key={a.numero} style={{ fontWeight: a.destacado ? 700 : undefined }}>
                {a.lineas.join(" / ")}
              </li>
            ))}
          </ol>
        )}
      </div>

      {borrador && (
        <div style={{ display: "grid", gap: "0.4rem" }}>
          <h4 style={{ margin: 0, fontSize: "0.9rem" }}>
            Nueva versión (a partir de la versión {datos.vigente?.version})
          </h4>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 200px" }}>
              <Campo etiqueta="Marca">
                <input
                  value={borrador.marca}
                  onChange={(e) => actualizar({ marca: e.target.value })}
                  disabled={bloqueado}
                  style={estiloInput}
                />
              </Campo>
            </div>
            <div style={{ flex: "1 1 200px" }}>
              <Campo etiqueta="Título *">
                <input
                  value={borrador.titulo}
                  onChange={(e) => actualizar({ titulo: e.target.value })}
                  disabled={bloqueado}
                  style={estiloInput}
                />
              </Campo>
            </div>
            <div style={{ flex: "1 1 200px" }}>
              <Campo etiqueta="Subtítulo">
                <input
                  value={borrador.subtitulo}
                  onChange={(e) => actualizar({ subtitulo: e.target.value })}
                  disabled={bloqueado}
                  style={estiloInput}
                />
              </Campo>
            </div>
          </div>
          {borrador.apartados.map((a, indice) => (
            <div
              key={indice}
              style={{
                border: `1px solid ${colores.borde}`,
                borderRadius: 6,
                padding: "0.5rem",
                background: a.destacado ? "#fff8d6" : undefined,
              }}
            >
              <Campo etiqueta={`Apartado ${indice + 1} (una línea por renglón)`}>
                <textarea
                  value={a.texto}
                  rows={Math.min(6, Math.max(2, a.texto.split("\n").length + 1))}
                  onChange={(e) => apartado(indice, { texto: e.target.value })}
                  disabled={bloqueado}
                  style={{ ...estiloInput, resize: "vertical" }}
                />
              </Campo>
              <div style={{ display: "flex", gap: "0.8rem", alignItems: "center", flexWrap: "wrap" }}>
                <label style={{ fontSize: "0.8rem" }}>
                  <input
                    type="checkbox"
                    checked={a.destacado}
                    onChange={(e) => apartado(indice, { destacado: e.target.checked })}
                    disabled={bloqueado}
                  />{" "}
                  Resaltado
                </label>
                <Boton
                  variante="secundario"
                  disabled={bloqueado}
                  onClick={() =>
                    actualizar({ apartados: borrador.apartados.filter((_, i) => i !== indice) })
                  }
                >
                  Quitar
                </Boton>
              </div>
            </div>
          ))}
          <div>
            <Boton
              variante="secundario"
              disabled={bloqueado}
              onClick={() =>
                actualizar({ apartados: [...borrador.apartados, { texto: "", destacado: false }] })
              }
            >
              + Agregar apartado
            </Boton>
          </div>
          <Campo etiqueta="Pie (una línea por espacio para completar a mano)">
            <textarea
              value={borrador.pie}
              rows={3}
              onChange={(e) => actualizar({ pie: e.target.value })}
              disabled={bloqueado}
              style={{ ...estiloInput, resize: "vertical" }}
            />
          </Campo>
          {faltantes.length > 0 && (
            <p style={{ margin: 0, fontSize: "0.8rem", color: colores.error }}>
              Falta {faltantes.join(", ")}.
            </p>
          )}
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <Boton
              disabled={bloqueado || faltantes.length > 0 || sinCambios}
              onClick={() => {
                const { titulo, contenido } = contenidoDelBorrador(borrador);
                void ejecutar(
                  () => api.publicarTerminos(actor.id, titulo, contenido),
                  (publicada) =>
                    `Se publicó la versión ${publicada.version}: rige para los comprobantes que se emitan desde ahora.`,
                ).then((publicada) => {
                  if (publicada !== undefined) cargar();
                });
              }}
            >
              Publicar versión nueva
            </Boton>
            <Boton
              variante="secundario"
              disabled={bloqueado || sinCambios}
              onClick={() => datos.vigente && setBorrador(borradorDe(datos.vigente))}
            >
              Descartar cambios
            </Boton>
          </div>
        </div>
      )}
      {!datos.editable && (
        <p style={{ fontSize: "0.8rem", color: colores.suave }}>{SOLO_LECTURA}</p>
      )}
    </section>
  );
}
