/**
 * Contenedor de la feature: carga datos, ejecuta comandos y decide qué
 * pantalla mostrar (listado o una Orden).
 *
 * Es el único componente con estado de verdad. Toda la lógica de negocio
 * vive en el backend: acá solo se llama a la API y se muestra lo que
 * devuelve, incluidas las acciones disponibles y la situación operativa.
 *
 * La pantalla de una Orden sigue el trabajo del empleado: cabecera,
 * «Próximo paso», trabajos, situaciones especiales, información
 * complementaria (en el orden que más le sirve a cada rol) e historial.
 */

import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import * as api from "../../api/ordenes";
import { ApiError } from "../../api/client";
import { Boton, Panel, colores, importe } from "../../components/ui";
import type {
  Accion,
  Estacion,
  MedioPago,
  Orden,
  OrdenResumen,
  RolUsuario,
  TipoReparacion,
  Usuario,
} from "../../types/api";
import {
  AccionesOrden,
  CancelacionesOrden,
  type EjecutorAcciones,
} from "./AccionesOrden";
import { InventarioPanel } from "../inventario/Inventario";
import { AutorizacionClienteOrden } from "./AutorizacionCliente";
import { CustodiaOrden } from "./CustodiaOrden";
import {
  Bloque,
  CabeceraOrden,
  DatosTecnicos,
  EjecucionesOrden,
  HistorialOrden,
  ProgresoHappyPath,
  TrabajosOrden,
} from "./DetalleOrden";
import { DocumentosOrden } from "./DocumentosOrden";
import {
  CUSTODIA,
  ESTADO_PAGO,
  ESTADO_TRABAJO,
  NOMBRE_ACCION,
  etiqueta,
  mensajeLegible,
} from "./etiquetas";
import { PagosYMovimientos } from "./PagosOrden";
import {
  FormularioAltaOrden,
  ListadoOrdenes,
  SelectorActor,
} from "./ListadoOrdenes";
import {
  CODIGOS_ESPECIALES,
  type ErrorDeComando,
  LugarDeFormularios,
  MensajeDeComando,
  ProveedorPresentacion,
  SeccionPlegable,
  accionesDeLaOrden,
  claveDeAccion,
  puedeEjecutar,
} from "./presentacion";
import { ProximoPaso } from "./ProximoPaso";

type Complementaria = "cliente" | "cobros" | "documentos";

/** Lo que se oculta en pantallas angostas (sin una hoja de estilos aparte). */
const ESTILOS_RESPONSIVOS = `
@media (max-width: 520px) {
  .rt-solo-escritorio { display: none; }
}
`;

/** Orden de la información complementaria según lo que más usa cada rol. */
const COMPLEMENTARIAS: Record<RolUsuario, Complementaria[]> = {
  RECEPCION: ["cliente", "cobros", "documentos"],
  TECNICO: ["cliente", "documentos", "cobros"],
  COORDINADOR_RMA: ["cliente", "cobros", "documentos"],
  ADMINISTRADOR: ["cobros", "cliente", "documentos"],
};

/** Qué sección complementaria abre cada rol sin que la pida. */
const ABIERTA_POR_ROL: Partial<Record<RolUsuario, Complementaria>> = {
  ADMINISTRADOR: "cobros",
};

export function PanelOrdenes() {
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [tipos, setTipos] = useState<TipoReparacion[]>([]);
  const [estaciones, setEstaciones] = useState<Estacion[]>([]);
  const [medios, setMedios] = useState<MedioPago[]>([]);
  const [actorId, setActorId] = useState("");

  const [ordenes, setOrdenes] = useState<OrdenResumen[]>([]);
  const [orden, setOrden] = useState<Orden | null>(null);

  const [error, setError] = useState<ErrorDeComando | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [vista, setVista] = useState<"ordenes" | "inventario">("ordenes");

  // Lugares donde los paneles dibujan sus formularios con un portal.
  const [lugares, setLugares] = useState<Record<number, HTMLElement | null>>(
    {},
  );
  const [especiales, setEspeciales] = useState<HTMLElement | null>(null);
  const registradores = useRef(
    new Map<number, (elemento: HTMLElement | null) => void>(),
  );
  const registrarTarea = useCallback((indice: number) => {
    let registrar = registradores.current.get(indice);
    if (!registrar) {
      registrar = (elemento) =>
        setLugares((previos) =>
          previos[indice] === elemento
            ? previos
            : { ...previos, [indice]: elemento },
        );
      registradores.current.set(indice, registrar);
    }
    return registrar;
  }, []);

  const actor = usuarios.find((usuario) => usuario.id === actorId) ?? null;

  // La Orden en pantalla, para recargarla si un comando choca (409) y para
  // traducir los mensajes de error con los nombres de sus pasos.
  const ordenEnPantalla = useRef<Orden | null>(null);
  useEffect(() => {
    ordenEnPantalla.current = orden;
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
        setError(errorDe(fallo, null));
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
   * operando sobre datos viejos. El error se muestra junto al formulario
   * desde el que se envió el comando.
   */
  const ejecutarComando = useCallback(
    async (comando: () => Promise<Orden>) => {
      const activo = document.activeElement;
      const clave =
        activo instanceof HTMLElement
          ? (activo.closest("[data-accion]")?.getAttribute("data-accion") ??
            null)
          : null;
      setOcupado(true);
      setError(null);
      try {
        const actualizada = await comando();
        setOrden(actualizada);
        await refrescarListado();
      } catch (fallo) {
        const ordenId = ordenEnPantalla.current?.id ?? null;
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
        setError(errorDe(fallo, ordenEnPantalla.current, clave, recargada));
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
      setError(errorDe(fallo, null));
    }
  }, []);

  // A qué tarea de «Próximo paso» corresponde cada acción que el usuario
  // puede ejecutar (la lista la manda el backend en la situación).
  const tareaDeAccion = useMemo(() => {
    const mapa = new Map<string, { indice: number; unica: boolean }>();
    orden?.situacion?.tareas.forEach((tarea, indice) => {
      const propias = tarea.acciones.filter((accion) =>
        puedeEjecutar(accion, actor),
      );
      propias.forEach((accion) =>
        mapa.set(claveDeAccion(accion), {
          indice,
          unica: propias.length === 1,
        }),
      );
    });
    return mapa;
  }, [orden, actor]);

  const enProximoPaso = useCallback(
    (accion: Accion) => {
      const tarea = tareaDeAccion.get(claveDeAccion(accion));
      const lugar = tarea ? lugares[tarea.indice] : null;
      return tarea && lugar ? { lugar, unica: tarea.unica } : null;
    },
    [tareaDeAccion, lugares],
  );

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
    entregar: (retiro) =>
      void ejecutarComando(() => api.entregar(idOrden, idActor, retiro)),
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
    registrarDevolucion: (retiro) =>
      void ejecutarComando(() =>
        api.registrarDevolucion(idOrden, idActor, retiro),
      ),
    cancelarDetalle: (detalleId, motivo) =>
      void ejecutarComando(() =>
        api.cancelarDetalle(idOrden, detalleId, idActor, motivo),
      ),
    cancelarOrden: (motivo) =>
      void ejecutarComando(() => api.cancelarOrden(idOrden, idActor, motivo)),
  };

  const contexto = {
    actor,
    enProximoPaso,
    especiales,
    error,
  };

  return (
    <div style={{ maxWidth: 1040, margin: "0 auto", padding: "1rem" }}>
      <style>{ESTILOS_RESPONSIVOS}</style>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "0.75rem",
          flexWrap: "wrap",
          marginBottom: "1rem",
        }}
      >
        <div>
          <h1 style={{ margin: 0, fontSize: "1.4rem" }}>Rosario Tecno</h1>
          <p style={{ margin: 0, color: colores.suave }}>
            Gestión de reparaciones
          </p>
        </div>
        <SelectorActor
          usuarios={usuarios}
          actorId={actorId}
          onCambiar={setActorId}
        />
      </header>

      <nav
        aria-label="Secciones"
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.5rem",
          marginBottom: "0.75rem",
        }}
      >
        {(
          [
            ["ordenes", "Órdenes"],
            ["inventario", "Inventario"],
          ] as const
        ).map(([clave, nombre]) => (
          <Boton
            key={clave}
            variante={vista === clave ? "primario" : "secundario"}
            onClick={() => {
              setVista(clave);
              setError(null);
              if (clave === "ordenes") {
                void refrescarListado();
                if (orden) void abrirOrden(orden.id);
              }
            }}
          >
            {nombre}
          </Boton>
        ))}
        {vista === "ordenes" && orden && (
          <Boton variante="secundario" onClick={() => setOrden(null)}>
            ← Volver al listado
          </Boton>
        )}
      </nav>

      {error && (vista === "inventario" || !orden) && (
        <MensajeDeComando error={error} />
      )}

      {vista === "inventario" ? (
        <InventarioPanel actor={actor} usuarios={usuarios} />
      ) : orden ? (
        <ProveedorPresentacion value={contexto}>
          {/*
            Jerarquía vertical, cada bloque a ancho completo. minmax(0,
            1fr): ningún contenido ancho (por ejemplo el historial) ensancha
            la pantalla en el celular.
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
            <ProximoPaso
              orden={orden}
              actor={actor}
              usuarios={usuarios}
              registrarTarea={registrarTarea}
              errorGeneral={errorSinLugar(error, orden, actor)}
            />
            <SeccionPlegable
              key={`${orden.id}-trabajos`}
              titulo="Trabajos"
              resumen={resumenTrabajos(orden)}
              abierta
            >
              <TrabajosOrden orden={orden} usuarios={usuarios} />
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
              <div style={{ marginTop: "0.8rem" }}>
                <AccionesOrden
                  orden={orden}
                  actor={actor}
                  usuarios={usuarios}
                  tipos={tipos}
                  estaciones={estaciones}
                  ocupado={ocupado}
                  ejecutar={ejecutor}
                />
              </div>
            </SeccionPlegable>

            {especialesDe(orden, actor).length > 0 && (
              <SeccionPlegable
                key={`${orden.id}-${actorId}-especiales`}
                titulo="Otras acciones / Situaciones especiales"
                resumen={especialesDe(orden, actor).join(" · ")}
              >
                <p
                  style={{
                    margin: "0 0 0.8rem",
                    fontSize: "0.8rem",
                    color: colores.suave,
                  }}
                >
                  Situaciones excepcionales. Cancelar no borra nada: el trabajo
                  queda cancelado con su motivo y deja de cobrarse.
                </p>
                <LugarDeFormularios onElemento={setEspeciales} />
                <CancelacionesOrden
                  orden={orden}
                  actor={actor}
                  usuarios={usuarios}
                  tipos={tipos}
                  estaciones={estaciones}
                  ocupado={ocupado}
                  ejecutar={ejecutor}
                />
              </SeccionPlegable>
            )}

            {(actor ? COMPLEMENTARIAS[actor.rol] : COMPLEMENTARIAS.RECEPCION).map(
              (seccion) => {
                const abierta =
                  actor !== null && ABIERTA_POR_ROL[actor.rol] === seccion;
                const llave = `${orden.id}-${actorId}-${seccion}`;
                if (seccion === "cliente") {
                  return (
                    <SeccionPlegable
                      key={llave}
                      titulo="Cliente y equipo"
                      resumen={resumenCliente(orden)}
                      abierta={abierta}
                    >
                      <CustodiaOrden
                        orden={orden}
                        actor={actor}
                        usuarios={usuarios}
                        ocupado={ocupado}
                        onRegistrar={(datos, equipo) =>
                          void ejecutarComando(() =>
                            api.registrarRecepcion(
                              idOrden,
                              idActor,
                              datos,
                              equipo,
                            ),
                          )
                        }
                        onConfirmar={(observaciones) =>
                          void ejecutarComando(() =>
                            api.confirmarRecepcion(
                              idOrden,
                              idActor,
                              observaciones,
                            ),
                          )
                        }
                        onNoRecibido={(motivo) =>
                          void ejecutarComando(() =>
                            api.registrarEquipoNoRecibido(
                              idOrden,
                              idActor,
                              motivo,
                            ),
                          )
                        }
                        onObservar={(texto) =>
                          void ejecutarComando(() =>
                            api.agregarObservacionRecepcion(
                              idOrden,
                              idActor,
                              texto,
                            ),
                          )
                        }
                      />
                    </SeccionPlegable>
                  );
                }
                if (seccion === "cobros") {
                  return (
                    <SeccionPlegable
                      key={llave}
                      titulo="Cobros"
                      resumen={resumenCobros(orden)}
                      abierta={abierta}
                    >
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
                    </SeccionPlegable>
                  );
                }
                return (
                  <SeccionPlegable
                    key={llave}
                    titulo="Documentos"
                    resumen={resumenDocumentos(orden)}
                    abierta={abierta}
                  >
                    <DocumentosOrden
                      orden={orden}
                      actor={actor}
                      usuarios={usuarios}
                      ocupado={ocupado}
                      onEmitirRecepcion={(motivo) =>
                        void ejecutarComando(() =>
                          api.emitirComprobanteRecepcion(
                            idOrden,
                            idActor,
                            motivo,
                          ),
                        )
                      }
                    />
                  </SeccionPlegable>
                );
              },
            )}

            <SeccionPlegable
              key={`${orden.id}-historial`}
              titulo="Historial y datos técnicos"
              resumen={`${orden.historial.length} eventos registrados`}
            >
              <Bloque titulo="Datos técnicos">
                <DatosTecnicos orden={orden} />
              </Bloque>
              <Bloque titulo="Recorrido técnico del proceso">
                <ProgresoHappyPath orden={orden} />
              </Bloque>
              <Bloque titulo="Ejecuciones">
                <EjecucionesOrden orden={orden} />
              </Bloque>
              <Bloque titulo="Historial">
                <HistorialOrden orden={orden} />
              </Bloque>
            </SeccionPlegable>
          </div>
        </ProveedorPresentacion>
      ) : (
        <div
          style={{
            display: "grid",
            gap: "0.75rem",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))",
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

function errorDe(
  fallo: unknown,
  orden: Orden | null,
  clave: string | null = null,
  recargada = false,
): ErrorDeComando {
  if (!(fallo instanceof ApiError)) {
    return {
      mensaje: "Ocurrió un error inesperado.",
      tecnico: String(fallo),
      clave,
    };
  }
  const prefijo =
    fallo.codigo === "CONFLICTO_CONCURRENTE"
      ? "Otra operación modificó la Orden al mismo tiempo. "
      : "";
  const sufijo = recargada ? " Se recargó la Orden con su estado actual." : "";
  return {
    mensaje: `${prefijo}${mensajeLegible(fallo.message, orden)}${sufijo}`,
    tecnico: fallo.message,
    clave,
  };
}

/**
 * El error que no tiene un formulario visible al lado (por ejemplo, la
 * acción ya no corresponde tras recargar): lo muestra «Próximo paso».
 */
function errorSinLugar(
  error: ErrorDeComando | null,
  orden: Orden,
  actor: Usuario | null,
): ErrorDeComando | null {
  if (error === null) return null;
  if (error.clave === null) return error;
  const visible = accionesDeLaOrden(orden).some(
    (accion) =>
      claveDeAccion(accion) === error.clave && puedeEjecutar(accion, actor),
  );
  return visible ? null : error;
}

/** Nombres de las acciones excepcionales que el usuario puede usar. */
function especialesDe(orden: Orden, actor: Usuario | null): string[] {
  const principales = new Set(
    (orden.situacion?.tareas ?? []).flatMap((tarea) =>
      tarea.acciones.map(claveDeAccion),
    ),
  );
  const nombres = accionesDeLaOrden(orden)
    .filter(
      (accion) =>
        CODIGOS_ESPECIALES.has(accion.codigo) &&
        !principales.has(claveDeAccion(accion)) &&
        puedeEjecutar(accion, actor),
    )
    .map((accion) => NOMBRE_ACCION[accion.codigo] ?? accion.etiqueta);
  return [...new Set(nombres)];
}

function resumenTrabajos(orden: Orden): ReactNode {
  if (orden.reparaciones_detail.length === 0) {
    return orden.finalizada_sin_reparacion
      ? "Sin reparación"
      : "Todavía sin trabajos definidos";
  }
  return orden.reparaciones_detail
    .map(
      (detalle) =>
        `${detalle.tipo_reparacion_nombre} (${etiqueta(
          ESTADO_TRABAJO,
          detalle.estado,
        ).toLowerCase()})`,
    )
    .join(" · ");
}

function resumenCliente(orden: Orden): string {
  return [
    orden.cliente
      ? `${orden.cliente.nombre} · ${orden.cliente.telefono}`
      : `Equipo interno RT · ${orden.referencia_rt ?? "—"}`,
    `Equipo: ${etiqueta(CUSTODIA, orden.custodia.estado).toLowerCase()}`,
    orden.recepcion?.datos.estado_fisico,
  ]
    .filter(Boolean)
    .join(" · ");
}

function resumenCobros(orden: Orden): string {
  const { resumen } = orden;
  if (resumen.condicion_comercial !== "COBRABLE") {
    return "No se cobra al cliente";
  }
  const saldo = Number(resumen.saldo);
  return saldo < 0
    ? `Crédito a favor del cliente: ${importe(resumen.credito_a_favor)}`
    : `Saldo ${importe(resumen.saldo)} · pagado ${importe(resumen.pagado)} · ${etiqueta(
        ESTADO_PAGO,
        resumen.estado_pago,
      ).toLowerCase()}`;
}

function resumenDocumentos(orden: Orden): string {
  const cantidad = orden.documentos_emitidos.length;
  return cantidad === 0
    ? "Ningún documento emitido"
    : `${cantidad} documento${cantidad === 1 ? "" : "s"} emitido${cantidad === 1 ? "" : "s"}`;
}
