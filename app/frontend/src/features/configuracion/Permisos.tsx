/**
 * Permisos por rol (DC08, DC27B; DEC-MI-12). Cada acción se habilita para
 * los roles elegidos; los predeterminados son los que el sistema traía. Un
 * permiso es necesario pero no suficiente: siguen valiendo las reglas de
 * cada caso (el técnico titular de la toma, el estado de la Orden...). Los
 * permisos de administración no se configuran. Cada cambio queda auditado.
 *
 * Configuración v2 (CFG-03): una acción puede requerir una consulta (crear
 * OC requiere ver Compras). Al habilitar la acción para un rol, primero se
 * habilita su consulta; quitar una consulta que otra acción del rol
 * necesita se impide, con el motivo. Después de guardar, la app vuelve a
 * leer los permisos del usuario (rigen desde el pedido siguiente).
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/configuracion";
import type { PermisoConfigurable } from "../../api/configuracion";
import { Boton, colores } from "../../components/ui";
import type { RolUsuario, Usuario } from "../../types/api";
import { ROL } from "../ordenes-reparacion/etiquetas";
import {
  ROLES,
  accionesQueLoRequieren,
  alternarRol,
  consultasAHabilitar,
  mismosRoles as igual,
  puedeGuardarPermiso,
} from "./roles";

export function Permisos({
  actor,
  editable,
  onCambio,
}: {
  actor: Usuario;
  editable: boolean;
  onCambio: () => void;
}) {
  const [permisos, setPermisos] = useState<PermisoConfigurable[]>([]);
  const [elegidos, setElegidos] = useState<Record<string, RolUsuario[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(() => {
    api
      .listarPermisos()
      .then((lista) => {
        setPermisos(lista);
        setElegidos(Object.fromEntries(lista.map((p) => [p.codigo, p.vigentes])));
      })
      .catch((causa: unknown) =>
        setError(causa instanceof Error ? causa.message : String(causa)),
      );
  }, []);
  useEffect(cargar, [cargar]);

  const guardar = (permiso: PermisoConfigurable, roles: RolUsuario[]) => {
    setOcupado(true);
    setError(null);
    setAviso(null);
    const previas = consultasAHabilitar(permiso, roles, permisos);
    (async () => {
      for (const consulta of previas) {
        await api.guardarPermiso(actor.id, consulta.codigo, consulta.roles);
      }
      await api.guardarPermiso(actor.id, permiso.codigo, roles);
    })()
      .then(() => {
        setAviso(
          `Se guardó «${permiso.descripcion}».` +
            (previas.length
              ? ` También se habilitó «${previas.map((c) => c.descripcion).join("», «")}», que lo requiere.`
              : ""),
        );
        cargar();
        onCambio();
      })
      .catch((causa: unknown) => {
        setError(causa instanceof Error ? causa.message : String(causa));
        // QA D, M1: una consulta requerida pudo guardarse antes del fallo.
        cargar();
        onCambio();
      })
      .finally(() => setOcupado(false));
  };

  const grupos = [...new Set(permisos.map((p) => p.grupo))];

  return (
    <section>
      <h3 style={{ margin: "0 0 0.5rem" }}>Permisos por rol</h3>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Un permiso habilita la acción, pero siguen valiendo las reglas de cada
        caso. Los de administración no se cambian.
      </p>
      {error && <p role="alert">{error}</p>}
      {aviso && <p role="status">{aviso}</p>}
      {grupos.map((grupo) => (
        <div key={grupo} style={{ marginBottom: "0.8rem" }}>
          <h4 style={{ margin: "0 0 0.3rem" }}>{grupo}</h4>
          <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", fontSize: "0.85rem" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: "0.2rem 0.5rem" }}>Acción</th>
                {ROLES.map((rol) => (
                  <th key={rol} style={{ padding: "0.2rem 0.5rem" }}>
                    {ROL[rol]}
                  </th>
                ))}
                <th />
              </tr>
            </thead>
            <tbody>
              {permisos
                .filter((p) => p.grupo === grupo)
                .map((permiso) => {
                  const propios = elegidos[permiso.codigo] ?? permiso.vigentes;
                  const bloqueado = !editable || ocupado || !permiso.configurable;
                  const distinto = !igual(permiso.vigentes, permiso.predeterminados);
                  const dependientes = accionesQueLoRequieren(permiso, propios, permisos);
                  const requeridas = (permiso.requiere ?? [])
                    .map((c) => permisos.find((p) => p.codigo === c)?.descripcion ?? c);
                  return (
                    <tr key={permiso.codigo}>
                      <td style={{ padding: "0.2rem 0.5rem" }}>
                        {permiso.descripcion}
                        {permiso.consulta && " (consulta)"}
                        {distinto && (
                          <span style={{ color: colores.suave }}> · cambiado</span>
                        )}
                        {requeridas.length > 0 && (
                          <div style={{ fontSize: "0.75rem", color: colores.suave }}>
                            Requiere: {requeridas.join(", ")}
                          </div>
                        )}
                        {dependientes.length > 0 && (
                          <div role="alert" style={{ fontSize: "0.75rem", color: colores.error }}>
                            Primero quitá ese rol de: {dependientes.join(", ")}
                          </div>
                        )}
                      </td>
                      {ROLES.map((rol) => (
                        <td key={rol} style={{ padding: "0.2rem 0.5rem", textAlign: "center" }}>
                          <input
                            type="checkbox"
                            aria-label={`${permiso.descripcion}: ${ROL[rol]}`}
                            disabled={bloqueado}
                            checked={propios.includes(rol)}
                            onChange={(e) =>
                              setElegidos({
                                ...elegidos,
                                [permiso.codigo]: alternarRol(propios, rol, e.target.checked),
                              })
                            }
                          />
                        </td>
                      ))}
                      <td style={{ padding: "0.2rem 0.5rem", whiteSpace: "nowrap" }}>
                        {permiso.configurable ? (
                          <>
                            <Boton
                              disabled={
                                bloqueado ||
                                !puedeGuardarPermiso(permiso, propios) ||
                                dependientes.length > 0
                              }
                              onClick={() => guardar(permiso, propios)}
                            >
                              Guardar
                            </Boton>{" "}
                            {distinto && (
                              <button
                                type="button"
                                disabled={
                                  bloqueado ||
                                  accionesQueLoRequieren(permiso, permiso.predeterminados, permisos)
                                    .length > 0
                                }
                                onClick={() => guardar(permiso, permiso.predeterminados)}
                              >
                                Restablecer
                              </button>
                            )}
                          </>
                        ) : (
                          <span style={{ color: colores.suave }}>fijo</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
          </div>
        </div>
      ))}
    </section>
  );
}
