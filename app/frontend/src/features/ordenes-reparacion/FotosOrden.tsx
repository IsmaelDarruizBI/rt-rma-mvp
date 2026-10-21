/**
 * Fotos del equipo (UAT-010/011): opcionales, una vez creada la Orden.
 * Desde el celular (cámara) o la galería (varias a la vez), hasta 10 por
 * Orden. Antes de subirlas se ven en una vista previa y cada una se acepta
 * o se descarta: solo se suben las aceptadas. Las guardadas se ven en
 * miniatura, se abren ampliadas y muestran quién las subió y cuándo. Las
 * ven Recepción y Taller. Se reducen en el navegador y se guardan en el
 * almacenamiento privado, nunca en la Orden.
 */

import { useEffect, useRef, useState } from "react";

import { urlFoto } from "../../api/ordenes";
import { Boton, colores, fechaCorta } from "../../components/ui";
import type { FotoOrden, Orden, RolUsuario, Usuario } from "../../types/api";
import { nombreDeUsuario } from "./DetalleOrden";
import {
  MAX_FOTOS,
  fotosQueCaben,
  motivoArchivoInvalido,
  reducirFoto,
} from "./fotos";

const ROLES_FOTOS: RolUsuario[] = [
  "RECEPCION",
  "TECNICO",
  "COORDINADOR_RMA",
  "ADMINISTRADOR",
];

export interface FotoParaSubir {
  archivo: Blob;
  nombre: string;
}

/** Una foto elegida que todavía no se subió. */
interface Pendiente extends FotoParaSubir {
  id: number;
  url: string;
  aceptada: boolean;
}

interface Ampliada {
  url: string;
  texto: string;
}

export function resumenFotos(orden: Orden): string {
  const cantidad = orden.fotos?.length ?? 0;
  if (cantidad === 0) return "Sin fotos";
  return `${cantidad} de ${MAX_FOTOS}`;
}

export function FotosOrden({
  orden,
  actor,
  usuarios,
  ocupado,
  onSubir,
}: {
  orden: Orden;
  actor: Usuario | null;
  usuarios: Usuario[];
  ocupado: boolean;
  /** Sube las fotos en orden; devuelve cuántas quedaron guardadas. */
  onSubir: (fotos: FotoParaSubir[]) => Promise<number>;
}) {
  const [pendientes, setPendientes] = useState<Pendiente[]>([]);
  const [preparando, setPreparando] = useState(false);
  const [subiendo, setSubiendo] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ampliada, setAmpliada] = useState<Ampliada | null>(null);
  const siguienteId = useRef(1);
  const urls = useRef(new Set<string>());

  // Las vistas previas son URLs del navegador: se liberan al salir.
  useEffect(() => {
    const vivas = urls.current;
    return () => vivas.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  const guardadas = orden.fotos ?? [];
  const habilitadas = orden.fotos_habilitadas ?? false;
  const puedeSubir =
    habilitadas &&
    !orden.cerrada &&
    actor !== null &&
    actor.activo &&
    ROLES_FOTOS.includes(actor.rol);
  const lugar = MAX_FOTOS - guardadas.length - pendientes.length;
  const aceptadas = pendientes.filter((pendiente) => pendiente.aceptada);
  const ocupada = ocupado || preparando || subiendo;

  function liberar(url: string) {
    URL.revokeObjectURL(url);
    urls.current.delete(url);
  }

  async function elegidas(lista: FileList | null) {
    if (!lista || lista.length === 0) return;
    setAviso(null);
    const archivos = Array.from(lista);
    const caben = fotosQueCaben(guardadas.length, pendientes.length, archivos.length);
    const avisos: string[] = [];
    if (caben < archivos.length) {
      avisos.push(
        `Máximo ${MAX_FOTOS} fotos por Orden: ${archivos.length - caben} quedaron afuera`,
      );
    }
    setPreparando(true);
    const nuevas: Pendiente[] = [];
    try {
      for (const archivo of archivos.slice(0, caben)) {
        const motivo = motivoArchivoInvalido(archivo.type, archivo.size);
        if (motivo && motivo !== "pesa más de 8 MB") {
          avisos.push(`${archivo.name}: ${motivo}`);
          continue;
        }
        // Una foto grande se reduce; si igual pasa del tope, se avisa.
        const reducida = await reducirFoto(archivo);
        const despues = motivoArchivoInvalido(reducida.type || archivo.type, reducida.size);
        if (despues) {
          avisos.push(`${archivo.name}: ${despues}`);
          continue;
        }
        const url = URL.createObjectURL(reducida);
        urls.current.add(url);
        nuevas.push({
          id: siguienteId.current++,
          archivo: reducida,
          nombre: archivo.name,
          url,
          aceptada: false,
        });
      }
    } finally {
      setPreparando(false);
    }
    if (avisos.length > 0) setAviso(`${avisos.join(" · ")}.`);
    if (nuevas.length > 0) setPendientes((actuales) => [...actuales, ...nuevas]);
  }

  function aceptar(id: number) {
    setPendientes((actuales) =>
      actuales.map((pendiente) =>
        pendiente.id === id ? { ...pendiente, aceptada: true } : pendiente,
      ),
    );
  }

  function descartar(id: number) {
    const quitada = pendientes.find((pendiente) => pendiente.id === id);
    if (quitada) liberar(quitada.url);
    setPendientes((actuales) => actuales.filter((pendiente) => pendiente.id !== id));
  }

  async function subirAceptadas() {
    const lote = aceptadas;
    if (lote.length === 0) return;
    setSubiendo(true);
    try {
      const subidas = await onSubir(
        lote.map(({ archivo, nombre }) => ({ archivo, nombre })),
      );
      // Las que se guardaron salen de la revisión; si una falló, ella y las
      // siguientes quedan para reintentar.
      const hechas = lote.slice(0, subidas);
      hechas.forEach((pendiente) => liberar(pendiente.url));
      const ids = new Set(hechas.map((pendiente) => pendiente.id));
      setPendientes((actuales) => actuales.filter((pendiente) => !ids.has(pendiente.id)));
    } finally {
      setSubiendo(false);
    }
  }

  return (
    <div>
      <p
        aria-label="Cantidad de fotos"
        style={{ margin: "0 0 0.5rem", fontSize: "0.85rem", fontWeight: 600 }}
      >
        {guardadas.length} de {MAX_FOTOS} fotos
        {pendientes.length > 0 && (
          <span style={{ fontWeight: 400, color: colores.suave }}>
            {" "}
            · {pendientes.length} para revisar
          </span>
        )}
      </p>
      {!habilitadas && (
        <p style={{ margin: "0 0 0.6rem", fontSize: "0.85rem", color: colores.suave }}>
          Las fotos no están disponibles en este entorno: falta configurar
          su almacenamiento.
        </p>
      )}
      {guardadas.length === 0 && habilitadas && (
        <p style={{ margin: "0 0 0.6rem", fontSize: "0.85rem", color: colores.suave }}>
          Sin fotos. Son opcionales.
        </p>
      )}
      {guardadas.length > 0 && (
        <ul aria-label="Fotos del equipo" style={estiloGrilla}>
          {guardadas.map((foto) => (
            <MiniaturaFoto
              key={foto.id}
              orden={orden}
              foto={foto}
              usuarios={usuarios}
              onAmpliar={setAmpliada}
            />
          ))}
        </ul>
      )}

      {pendientes.length > 0 && (
        <section
          aria-label="Fotos para revisar"
          style={{
            border: `1px dashed ${colores.borde}`,
            borderRadius: 6,
            padding: "0.5rem 0.6rem",
            margin: "0 0 0.6rem",
          }}
        >
          <p style={{ margin: "0 0 0.4rem", fontSize: "0.85rem" }}>
            Revisá cada foto: solo se suben las aceptadas.
          </p>
          <ul style={estiloGrilla}>
            {pendientes.map((pendiente) => (
              <li key={pendiente.id} data-pendiente={pendiente.aceptada ? "aceptada" : "pendiente"} style={{ fontSize: "0.75rem" }}>
                <button
                  type="button"
                  onClick={() => setAmpliada({ url: pendiente.url, texto: pendiente.nombre })}
                  style={estiloBotonImagen}
                  title="Ver ampliada"
                >
                  <img
                    src={pendiente.url}
                    alt={`Vista previa de ${pendiente.nombre}`}
                    style={{
                      ...estiloMiniatura,
                      outline: pendiente.aceptada ? `3px solid ${colores.ok}` : "none",
                    }}
                  />
                </button>
                <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap", marginTop: "0.3rem" }}>
                  {pendiente.aceptada ? (
                    <span style={{ color: colores.ok, fontWeight: 600 }}>✓ Aceptada</span>
                  ) : (
                    <Boton variante="secundario" disabled={ocupada} onClick={() => aceptar(pendiente.id)}>
                      Aceptar
                    </Boton>
                  )}
                  <Boton variante="secundario" disabled={ocupada} onClick={() => descartar(pendiente.id)}>
                    Descartar
                  </Boton>
                </div>
              </li>
            ))}
          </ul>
          <Boton disabled={ocupada || aceptadas.length === 0} onClick={() => void subirAceptadas()}>
            {aceptadas.length === 1
              ? "Subir 1 foto aceptada"
              : `Subir ${aceptadas.length} fotos aceptadas`}
          </Boton>
        </section>
      )}

      {puedeSubir && lugar > 0 && (
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <ElegirFotos texto="Tomar foto" camara deshabilitado={ocupada} onElegir={elegidas} />
          <ElegirFotos texto="Elegir fotos" deshabilitado={ocupada} onElegir={elegidas} />
        </div>
      )}
      {puedeSubir && lugar <= 0 && (
        <p style={{ margin: 0, fontSize: "0.85rem", color: colores.suave }}>
          Ya hay {MAX_FOTOS} fotos entre las guardadas y las que esperan
          revisión: es el máximo por Orden.
        </p>
      )}
      {(preparando || subiendo) && (
        <p role="status" style={{ margin: "0.5rem 0 0", fontSize: "0.85rem" }}>
          {preparando ? "Preparando la vista previa…" : "Subiendo…"}
        </p>
      )}
      {aviso && (
        <p role="alert" style={{ margin: "0.5rem 0 0", fontSize: "0.85rem", color: colores.alerta }}>
          {aviso}
        </p>
      )}
      {ampliada && <FotoAmpliada foto={ampliada} onCerrar={() => setAmpliada(null)} />}
    </div>
  );
}

const estiloGrilla = {
  listStyle: "none",
  margin: "0 0 0.6rem",
  padding: 0,
  display: "grid",
  gap: "0.6rem",
  gridTemplateColumns: "repeat(auto-fill, minmax(104px, 1fr))",
} as const;

const estiloMiniatura = {
  display: "block",
  width: "100%",
  aspectRatio: "1 / 1",
  objectFit: "cover",
  borderRadius: 6,
  border: `1px solid ${colores.borde}`,
  background: colores.fondo,
} as const;

const estiloBotonImagen = {
  display: "block",
  width: "100%",
  padding: 0,
  border: 0,
  background: "none",
  cursor: "zoom-in",
} as const;

/**
 * Un botón que abre la cámara (`capture`) o la galería (varias a la vez).
 * El input queda oculto y se reinicia: elegir la misma foto dos veces
 * vuelve a dispararlo.
 */
function ElegirFotos({
  texto,
  camara = false,
  deshabilitado,
  onElegir,
}: {
  texto: string;
  camara?: boolean;
  deshabilitado: boolean;
  onElegir: (lista: FileList | null) => void;
}) {
  return (
    <label
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "0.45rem 0.9rem",
        borderRadius: 6,
        border: `1px solid ${colores.acento}`,
        color: deshabilitado ? colores.suave : colores.acento,
        background: "#fff",
        cursor: deshabilitado ? "not-allowed" : "pointer",
        fontSize: "0.9rem",
        opacity: deshabilitado ? 0.6 : 1,
      }}
    >
      {texto}
      <input
        type="file"
        accept="image/*"
        multiple={!camara}
        {...(camara ? { capture: "environment" as const } : {})}
        disabled={deshabilitado}
        style={{ display: "none" }}
        onChange={(evento) => {
          const lista = evento.target.files;
          void onElegir(lista);
          evento.target.value = "";
        }}
      />
    </label>
  );
}

function MiniaturaFoto({
  orden,
  foto,
  usuarios,
  onAmpliar,
}: {
  orden: Orden;
  foto: FotoOrden;
  usuarios: Usuario[];
  onAmpliar: (foto: Ampliada) => void;
}) {
  const url = urlFoto(orden.id, foto.id);
  const quien = `${nombreDeUsuario(usuarios, foto.usuario_id)} · ${fechaCorta(foto.fecha)}`;
  return (
    <li style={{ fontSize: "0.75rem", color: colores.suave }}>
      <button
        type="button"
        onClick={() => onAmpliar({ url, texto: quien })}
        style={estiloBotonImagen}
        title="Ver ampliada"
      >
        <img
          src={url}
          alt={`Foto del equipo subida por ${nombreDeUsuario(usuarios, foto.usuario_id)}`}
          loading="lazy"
          style={estiloMiniatura}
        />
      </button>
      <span style={{ display: "block", marginTop: "0.2rem" }}>{quien}</span>
    </li>
  );
}

/** La foto ampliada sobre la pantalla; se cierra con «Cerrar» o Escape. */
function FotoAmpliada({ foto, onCerrar }: { foto: Ampliada; onCerrar: () => void }) {
  useEffect(() => {
    const alPresionar = (evento: KeyboardEvent) => {
      if (evento.key === "Escape") onCerrar();
    };
    window.addEventListener("keydown", alPresionar);
    return () => window.removeEventListener("keydown", alPresionar);
  }, [onCerrar]);
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Foto ampliada"
      onClick={onCerrar}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        background: "rgba(20, 20, 20, 0.85)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "0.6rem",
        padding: "1rem",
        boxSizing: "border-box",
      }}
    >
      <img
        src={foto.url}
        alt={foto.texto}
        onClick={(evento) => evento.stopPropagation()}
        style={{ maxWidth: "100%", maxHeight: "80vh", borderRadius: 6, background: "#fff" }}
      />
      <span style={{ color: "#fff", fontSize: "0.85rem" }}>{foto.texto}</span>
      <Boton variante="secundario" onClick={onCerrar}>
        Cerrar
      </Boton>
    </div>
  );
}
