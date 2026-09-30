/**
 * Contenedor de la feature: carga datos, ejecuta comandos y decide qué
 * pantalla mostrar (listado o una Orden).
 *
 * Es el único componente con estado de verdad. Toda la lógica de negocio
 * vive en el backend: acá solo se llama a la API y se muestra lo que
 * devuelve, incluidas las acciones disponibles.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/ordenes";
import { ApiError } from "../../api/client";
import { Boton, MensajeError, Panel, colores } from "../../components/ui";
import type {
  Estacion,
  Orden,
  OrdenResumen,
  TipoReparacion,
  Usuario,
} from "../../types/api";
import { AccionesOrden, type EjecutorAcciones } from "./AccionesOrden";
import {
  CabeceraOrden,
  DetallesOrden,
  HistorialOrden,
  ProgresoHappyPath,
  ResumenComercialOrden,
} from "./DetalleOrden";
import {
  FormularioNuevaOrden,
  FormularioNuevaOrdenRt,
  ListadoOrdenes,
  SelectorActor,
} from "./ListadoOrdenes";

export function PanelOrdenes() {
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [tipos, setTipos] = useState<TipoReparacion[]>([]);
  const [estaciones, setEstaciones] = useState<Estacion[]>([]);
  const [actorId, setActorId] = useState("");

  const [ordenes, setOrdenes] = useState<OrdenResumen[]>([]);
  const [orden, setOrden] = useState<Orden | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const actor = usuarios.find((usuario) => usuario.id === actorId) ?? null;

  const refrescarListado = useCallback(async () => {
    setOrdenes(await api.listarOrdenes());
  }, []);

  useEffect(() => {
    async function cargar() {
      try {
        const [listaUsuarios, listaTipos, listaEstaciones] =
          await Promise.all([
            api.listarUsuarios(),
            api.listarTiposReparacion(),
            api.listarEstaciones(),
          ]);
        setUsuarios(listaUsuarios);
        setTipos(listaTipos);
        setEstaciones(listaEstaciones);
        setActorId((actual) => actual || (listaUsuarios[0]?.id ?? ""));
        await refrescarListado();
      } catch (fallo) {
        setError(mensajeDe(fallo));
      }
    }
    void cargar();
  }, [refrescarListado]);

  /** Ejecuta un comando y deja la Orden devuelta como estado actual. */
  const ejecutarComando = useCallback(
    async (comando: () => Promise<Orden>) => {
      setOcupado(true);
      setError(null);
      try {
        const actualizada = await comando();
        setOrden(actualizada);
        await refrescarListado();
      } catch (fallo) {
        setError(mensajeDe(fallo));
      } finally {
        setOcupado(false);
      }
    },
    [refrescarListado],
  );

  const abrirOrden = useCallback(async (ordenId: string) => {
    setError(null);
    try {
      setOrden(await api.obtenerOrden(ordenId));
    } catch (fallo) {
      setError(mensajeDe(fallo));
    }
  }, []);

  const idActor = actor?.id ?? "";
  const idOrden = orden?.id ?? "";

  const ejecutor: EjecutorAcciones = {
    definirReparacion: (tipoId) =>
      void ejecutarComando(() =>
        api.definirReparacion(idOrden, idActor, tipoId),
      ),
    encolar: (prioridad) =>
      void ejecutarComando(() =>
        api.encolar(idOrden, idActor, prioridad),
      ),
    tomar: (estacionId) =>
      void ejecutarComando(() =>
        api.tomarOrden(idOrden, idActor, estacionId),
      ),
    iniciarDetalle: (detalleId) =>
      void ejecutarComando(() =>
        api.iniciarDetalle(idOrden, detalleId, idActor),
      ),
    completarEjecucion: (ejecucionId, insumosUtilizados, observaciones) =>
      void ejecutarComando(() =>
        api.completarEjecucion(
          idOrden,
          ejecucionId,
          idActor,
          insumosUtilizados,
          observaciones || null,
        ),
      ),
    aprobarControl: (observaciones) =>
      void ejecutarComando(() =>
        api.aprobarControl(idOrden, idActor, observaciones || null),
      ),
    notificar: () =>
      void ejecutarComando(() => api.notificar(idOrden, idActor)),
    registrarPago: (monto, metodo) =>
      void ejecutarComando(() =>
        api.registrarPago(idOrden, idActor, monto, metodo),
      ),
    entregar: () =>
      void ejecutarComando(() => api.entregar(idOrden, idActor)),
    informarRt: () => void ejecutarComando(() => api.informarRt(idOrden)),
    devolverRt: () =>
      void ejecutarComando(() => api.devolverRt(idOrden, idActor)),
  };

  return (
    <div style={{ maxWidth: 1040, margin: "0 auto", padding: "1.5rem" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "1rem",
          flexWrap: "wrap",
          marginBottom: "1.25rem",
        }}
      >
        <div>
          <h1 style={{ margin: 0, fontSize: "1.4rem" }}>Rosario Tecno</h1>
          <p style={{ margin: 0, color: colores.suave }}>
            RMA MVP · HP-REP-001 · HP-REP-002
          </p>
        </div>
        <SelectorActor
          usuarios={usuarios}
          actorId={actorId}
          onCambiar={setActorId}
        />
      </header>

      {error && <MensajeError mensaje={error} />}

      {orden ? (
        <>
          <div style={{ marginBottom: "0.75rem" }}>
            <Boton variante="secundario" onClick={() => setOrden(null)}>
              ← Volver al listado
            </Boton>
          </div>
          {/*
            Jerarquia vertical, cada bloque a ancho completo:
            Datos OR -> Detalles -> Accion -> Resumen comercial ->
            Progreso -> Historial. Detalles y Resumen ya no compiten
            horizontalmente.
          */}
          <div style={{ display: "grid", gap: "0.75rem" }}>
            <CabeceraOrden orden={orden} />
            <DetallesOrden orden={orden} />
            <AccionesOrden
              orden={orden}
              actor={actor}
              tipos={tipos}
              estaciones={estaciones}
              ocupado={ocupado}
              ejecutar={ejecutor}
            />
            <ResumenComercialOrden orden={orden} />
            <ProgresoHappyPath orden={orden} />
            <HistorialOrden orden={orden} />
          </div>
        </>
      ) : (
        <div
          style={{
            display: "grid",
            gap: "0.75rem",
            gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          }}
        >
          <ListadoOrdenes ordenes={ordenes} onAbrir={abrirOrden} />
          <FormularioNuevaOrden
            actor={actor}
            ocupado={ocupado}
            onCrear={(datos) =>
              void ejecutarComando(() => api.crearOrden(datos))
            }
          />
          <FormularioNuevaOrdenRt
            actor={actor}
            ocupado={ocupado}
            onCrear={(datos) =>
              void ejecutarComando(() => api.crearOrdenRt(datos))
            }
          />
        </div>
      )}

      {usuarios.length === 0 && !error && (
        <Panel>
          <p style={{ margin: 0, color: colores.suave }}>Cargando…</p>
        </Panel>
      )}
    </div>
  );
}

function mensajeDe(fallo: unknown): string {
  if (fallo instanceof ApiError) return fallo.message;
  return "Ocurrió un error inesperado.";
}
