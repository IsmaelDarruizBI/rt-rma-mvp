/**
 * Contenedor de la feature: carga datos, ejecuta comandos y decide qué
 * pantalla mostrar (listado o una Orden).
 *
 * Es el único componente con estado de verdad. Toda la lógica de negocio
 * vive en el backend: acá solo se llama a la API y se muestra lo que
 * devuelve, incluidas las acciones disponibles.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import * as api from "../../api/ordenes";
import { ApiError } from "../../api/client";
import { Boton, MensajeError, Panel, colores } from "../../components/ui";
import type {
  Estacion,
  MedioPago,
  Orden,
  OrdenResumen,
  TipoReparacion,
  Usuario,
} from "../../types/api";
import {
  AccionesOrden,
  CancelacionesOrden,
  type EjecutorAcciones,
} from "./AccionesOrden";
import { AutorizacionClienteOrden } from "./AutorizacionCliente";
import {
  CabeceraOrden,
  DetallesOrden,
  EjecucionesOrden,
  HistorialOrden,
  ProgresoHappyPath,
} from "./DetalleOrden";
import { PagosYMovimientos } from "./PagosOrden";
import {
  FormularioAltaOrden,
  ListadoOrdenes,
  SelectorActor,
} from "./ListadoOrdenes";

export function PanelOrdenes() {
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [tipos, setTipos] = useState<TipoReparacion[]>([]);
  const [estaciones, setEstaciones] = useState<Estacion[]>([]);
  const [medios, setMedios] = useState<MedioPago[]>([]);
  const [actorId, setActorId] = useState("");

  const [ordenes, setOrdenes] = useState<OrdenResumen[]>([]);
  const [orden, setOrden] = useState<Orden | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const actor = usuarios.find((usuario) => usuario.id === actorId) ?? null;

  // La Orden en pantalla, para recargarla si un comando choca (409).
  const ordenEnPantalla = useRef<string | null>(null);
  useEffect(() => {
    ordenEnPantalla.current = orden?.id ?? null;
  }, [orden]);

  const refrescarListado = useCallback(async () => {
    setOrdenes(await api.listarOrdenes());
  }, []);

  useEffect(() => {
    async function cargar() {
      try {
        const [listaUsuarios, listaTipos, listaEstaciones, listaMedios] =
          await Promise.all([
            api.listarUsuarios(),
            api.listarTiposReparacion(),
            api.listarEstaciones(),
            api.listarMediosPago(),
          ]);
        setUsuarios(listaUsuarios);
        setTipos(listaTipos);
        setEstaciones(listaEstaciones);
        setMedios(listaMedios);
        setActorId((actual) => actual || (listaUsuarios[0]?.id ?? ""));
        await refrescarListado();
      } catch (fallo) {
        setError(mensajeDe(fallo));
      }
    }
    void cargar();
  }, [refrescarListado]);

  /**
   * Ejecuta un comando y deja la Orden devuelta como estado actual.
   *
   * Un 409 significa que la Orden no admitía el comando en su estado
   * REAL: otro usuario la cambió (CONFLICTO_CONCURRENTE), ya está cerrada
   * (ORDEN_CERRADA), la tiene otro técnico (TOMA_DE_OTRO_TECNICO), etc.
   * En todos los casos se recarga desde el backend para no seguir
   * operando sobre datos viejos.
   */
  const ejecutarComando = useCallback(
    async (comando: () => Promise<Orden>) => {
      setOcupado(true);
      setError(null);
      try {
        const actualizada = await comando();
        setOrden(actualizada);
        await refrescarListado();
      } catch (fallo) {
        const ordenId = ordenEnPantalla.current;
        const conflicto = fallo instanceof ApiError && fallo.status === 409;
        let recargada = false;
        if (conflicto && ordenId) {
          try {
            setOrden(await api.obtenerOrden(ordenId));
            await refrescarListado();
            recargada = true;
          } catch {
            // Si la recarga tambien falla, queda el mensaje original.
          }
        }
        setError(mensajeDe(fallo, recargada));
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
    agregarDetalle: (tipoId) =>
      void ejecutarComando(() =>
        api.definirReparacion(idOrden, idActor, tipoId),
      ),
    finalizarDefinicion: () =>
      void ejecutarComando(() => api.finalizarDefinicion(idOrden, idActor)),
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
    esperarRecursos: () =>
      void ejecutarComando(() => api.esperarRecursos(idOrden)),
    consultarImpactoOverride: (detalleId) =>
      api.obtenerImpactoOverride(idOrden, detalleId),
    // Solo se invoca tras la confirmación explícita del impacto (E3).
    overrideRecursos: (detalleId, motivo) =>
      void ejecutarComando(() =>
        api.overrideRecursos(idOrden, detalleId, idActor, motivo, true),
      ),
    revalidarRecursos: () =>
      void ejecutarComando(() => api.revalidarRecursos(idOrden)),
    interrumpirEjecucion: (ejecucionId, insumosUtilizados, observaciones) =>
      void ejecutarComando(() =>
        api.interrumpirEjecucion(
          idOrden,
          ejecucionId,
          idActor,
          insumosUtilizados,
          observaciones || null,
        ),
      ),
    requerirRedefinicion: (
      ejecucionId,
      insumosUtilizados,
      motivo,
      observaciones,
    ) =>
      void ejecutarComando(() =>
        api.requerirRedefinicion(
          idOrden,
          ejecucionId,
          idActor,
          insumosUtilizados,
          motivo,
          observaciones || null,
        ),
      ),
    revisarDetalle: (detalleId, resultado) =>
      void ejecutarComando(() =>
        api.revisarDetalle(idOrden, detalleId, idActor, resultado),
      ),
    redefinirDetalle: (detalleId, tipoId) =>
      void ejecutarComando(() =>
        api.redefinirDetalle(idOrden, detalleId, idActor, tipoId),
      ),
    aprobarControl: (detalleId, observaciones) =>
      void ejecutarComando(() =>
        api.aprobarControl(idOrden, idActor, detalleId, observaciones || null),
      ),
    liberarOrden: () =>
      void ejecutarComando(() => api.liberarOrden(idOrden, idActor)),
    notificar: () =>
      void ejecutarComando(() => api.notificar(idOrden, idActor)),
    entregar: () =>
      void ejecutarComando(() => api.entregar(idOrden, idActor)),
    informarRt: () => void ejecutarComando(() => api.informarRt(idOrden)),
    devolverRt: () =>
      void ejecutarComando(() => api.devolverRt(idOrden, idActor)),
    enviarARevision: () =>
      void ejecutarComando(() => api.enviarARevision(idOrden, idActor)),
    realizarRevision: (resultado) =>
      void ejecutarComando(() =>
        api.realizarRevision(idOrden, idActor, resultado),
      ),
    agregarDetalleDesdeRevision: (tipoId, detalleOrigenId) =>
      void ejecutarComando(() =>
        api.definirReparacionDesdeRevision(
          idOrden,
          idActor,
          tipoId,
          detalleOrigenId,
        ),
      ),
    finalizarSinReparacion: (motivo, observaciones) =>
      void ejecutarComando(() =>
        api.finalizarSinReparacion(
          idOrden,
          idActor,
          motivo,
          observaciones || null,
        ),
      ),
    // Devuelve la NUEVA Orden de garantía: queda abierta en pantalla.
    iniciarGarantiaRma: (detalleOrigenIds) =>
      void ejecutarComando(() =>
        api.iniciarGarantiaRma(idOrden, idActor, detalleOrigenIds),
      ),
    rechazarControl: (detalleId, motivo) =>
      void ejecutarComando(() =>
        api.rechazarControl(idOrden, idActor, detalleId, motivo),
      ),
    registrarDevolucion: (recibidoPor, observaciones) =>
      void ejecutarComando(() =>
        api.registrarDevolucion(
          idOrden,
          idActor,
          recibidoPor,
          observaciones || null,
        ),
      ),
    cancelarDetalle: (detalleId, motivo) =>
      void ejecutarComando(() =>
        api.cancelarDetalle(idOrden, detalleId, idActor, motivo),
      ),
    cancelarOrden: (motivo) =>
      void ejecutarComando(() => api.cancelarOrden(idOrden, idActor, motivo)),
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
            RMA MVP · HP-REP-001/002/003 · VAR-REP-001/002
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
            horizontalmente. minmax(0, 1fr): ningun contenido ancho (p. ej.
            el Historial) ensancha la pantalla en mobile.
          */}
          <div
            style={{
              display: "grid",
              gap: "0.75rem",
              gridTemplateColumns: "minmax(0, 1fr)",
            }}
          >
            <CabeceraOrden
              orden={orden}
              usuarios={usuarios}
              estaciones={estaciones}
            />
            <DetallesOrden orden={orden} />
            <AutorizacionClienteOrden
              orden={orden}
              actor={actor}
              usuarios={usuarios}
              ocupado={ocupado}
              onRegistrar={(canal, observaciones, decisiones) =>
                void ejecutarComando(() =>
                  api.registrarDecisionCliente(
                    idOrden,
                    idActor,
                    canal,
                    observaciones || null,
                    decisiones,
                  ),
                )
              }
              onDesistir={(detalleId, canal, motivo) =>
                void ejecutarComando(() =>
                  api.desistir(idOrden, detalleId, idActor, canal, motivo),
                )
              }
            />
            <EjecucionesOrden orden={orden} />
            <AccionesOrden
              orden={orden}
              actor={actor}
              usuarios={usuarios}
              tipos={tipos}
              estaciones={estaciones}
              ocupado={ocupado}
              ejecutar={ejecutor}
            />
            <CancelacionesOrden
              orden={orden}
              actor={actor}
              usuarios={usuarios}
              tipos={tipos}
              estaciones={estaciones}
              ocupado={ocupado}
              ejecutar={ejecutor}
            />
            <PagosYMovimientos
              orden={orden}
              actor={actor}
              usuarios={usuarios}
              medios={medios}
              ocupado={ocupado}
              onPagar={(monto, metodo, referencia, operacionId) =>
                void ejecutarComando(() =>
                  api.registrarPago(
                    idOrden,
                    idActor,
                    monto,
                    metodo,
                    referencia,
                    operacionId,
                  ),
                )
              }
              onAnular={(pagoId, motivo) =>
                void ejecutarComando(() =>
                  api.anularPago(idOrden, pagoId, idActor, motivo),
                )
              }
              onDevolver={(datos) =>
                void ejecutarComando(() =>
                  api.devolverDinero(idOrden, idActor, datos),
                )
              }
            />
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
          <FormularioAltaOrden
            actor={actor}
            ocupado={ocupado}
            onCrearClienteExterno={(datos) =>
              void ejecutarComando(() => api.crearOrden(datos))
            }
            onCrearRtInterno={(datos) =>
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

function mensajeDe(fallo: unknown, recargada = false): string {
  if (!(fallo instanceof ApiError)) return "Ocurrió un error inesperado.";
  const prefijo =
    fallo.codigo === "CONFLICTO_CONCURRENTE"
      ? "Otra operación modificó la Orden al mismo tiempo. "
      : "";
  const sufijo = recargada
    ? " Se recargó la Orden con su estado actual."
    : "";
  return `${prefijo}${fallo.message}${sufijo}`;
}
