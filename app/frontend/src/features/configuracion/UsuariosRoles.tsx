/**
 * Usuarios y roles (DC27A, DEC-MI-12): Administración asigna uno o varios
 * roles a cada usuario; sus permisos se suman. Cada cambio queda auditado y
 * ningún cambio deja el sistema sin un Administrador activo (lo valida la
 * API). En el modo JSON se consulta pero no se cambia.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/configuracion";
import { Boton, colores } from "../../components/ui";
import { rolesDe } from "../../lib/roles";
import type { RolUsuario, Usuario } from "../../types/api";
import { ROL } from "../ordenes-reparacion/etiquetas";
import { ROLES, alternarRol, mismosRoles, motivoParaNoGuardarRoles } from "./roles";

export function UsuariosRoles({
  actor,
  editable,
  onCambio,
}: {
  actor: Usuario;
  editable: boolean;
  onCambio: () => void;
}) {
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [elegidos, setElegidos] = useState<Record<string, RolUsuario[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(() => {
    api
      .listarUsuarios()
      .then((lista) => {
        setUsuarios(lista);
        setElegidos(Object.fromEntries(lista.map((u) => [u.id, rolesDe(u)])));
      })
      .catch((causa: unknown) =>
        setError(causa instanceof Error ? causa.message : String(causa)),
      );
  }, []);
  useEffect(cargar, [cargar]);

  const guardar = (usuario: Usuario) => {
    setOcupado(true);
    setError(null);
    setAviso(null);
    api
      .guardarRoles(actor.id, usuario.id, elegidos[usuario.id] ?? [])
      .then(() => {
        setAviso(`Se guardaron los roles de ${usuario.nombre}.`);
        cargar();
        onCambio();
      })
      .catch((causa: unknown) =>
        setError(causa instanceof Error ? causa.message : String(causa)),
      )
      .finally(() => setOcupado(false));
  };

  return (
    <section>
      <h3 style={{ margin: "0 0 0.5rem" }}>Usuarios y roles</h3>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Un usuario puede tener varios roles: tiene los permisos de todos. El
        rol que habilitó cada acción queda en el historial de la Orden.
      </p>
      {error && <p role="alert">{error}</p>}
      {aviso && <p role="status">{aviso}</p>}
      <div style={{ overflowX: "auto" }}>
      <table style={{ borderCollapse: "collapse", fontSize: "0.85rem" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left", padding: "0.25rem 0.5rem" }}>Usuario</th>
            {ROLES.map((rol) => (
              <th key={rol} style={{ padding: "0.25rem 0.5rem" }}>
                {ROL[rol]}
              </th>
            ))}
            <th />
          </tr>
        </thead>
        <tbody>
          {usuarios.map((usuario) => {
            const actuales = rolesDe(usuario);
            const propios = elegidos[usuario.id] ?? actuales;
            const cambiado = !mismosRoles(propios, actuales);
            const impedimento = cambiado
              ? motivoParaNoGuardarRoles(usuarios, usuario.id, propios)
              : null;
            return (
              <tr key={usuario.id}>
                <td style={{ padding: "0.25rem 0.5rem" }}>
                  {usuario.nombre} ({usuario.id})
                  {!usuario.activo && " · inactivo"}
                </td>
                {ROLES.map((rol) => (
                  <td key={rol} style={{ padding: "0.25rem 0.5rem", textAlign: "center" }}>
                    <input
                      type="checkbox"
                      aria-label={`${usuario.nombre}: ${ROL[rol]}`}
                      disabled={!editable || ocupado}
                      checked={propios.includes(rol)}
                      onChange={(e) =>
                        setElegidos({
                          ...elegidos,
                          [usuario.id]: alternarRol(propios, rol, e.target.checked),
                        })
                      }
                    />
                  </td>
                ))}
                <td style={{ padding: "0.25rem 0.5rem" }}>
                  <Boton
                    disabled={!editable || ocupado || !cambiado || impedimento !== null}
                    onClick={() => guardar(usuario)}
                  >
                    Guardar
                  </Boton>
                  {impedimento && (
                    <span role="note" style={{ marginLeft: "0.4rem", color: colores.suave }}>
                      {impedimento}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>
    </section>
  );
}
