/**
 * Motivos y parámetros operativos (DEC-MI-13, 14 y 15). Solo
 * Administración los cambia, y cada cambio queda auditado. Desactivar un
 * motivo no cambia lo registrado: cada cancelación o interrupción guardó
 * el texto del motivo de ese momento. En la persistencia JSON (demo) son
 * de solo lectura.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/operativa";
import type { MotivoOperativo, TipoMotivo } from "../../api/operativa";
import { Boton, Campo, colores, estiloInput } from "../../components/ui";
import type { Usuario } from "../../types/api";

const TIPOS: { valor: TipoMotivo; texto: string }[] = [
  { valor: "CANCELACION", texto: "Cancelación" },
  { valor: "INTERRUPCION", texto: "Interrupción" },
];

const PARAMETROS: Record<string, { texto: string; ayuda: string }> = {
  PLAZO_RETIRO_DIAS: {
    texto: "Plazo de retiro (días)",
    ayuda:
      "Días desde el aviso de equipo listo hasta marcar el retiro como " +
      "demorado. Nunca cierra la Orden.",
  },
};

const mensaje = (causa: unknown) =>
  causa instanceof Error ? causa.message : String(causa);

function useEstado() {
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const ejecutar = (accion: () => Promise<unknown>, exito: string, despues: () => void) => {
    setOcupado(true);
    setError(null);
    setAviso(null);
    accion()
      .then(() => {
        setAviso(exito);
        despues();
      })
      .catch((causa: unknown) => setError(mensaje(causa)))
      .finally(() => setOcupado(false));
  };
  return { error, setError, aviso, ocupado, ejecutar };
}

function Mensajes({ error, aviso }: { error: string | null; aviso: string | null }) {
  return (
    <>
      {error && (
        <p role="alert" style={{ color: colores.error, fontSize: "0.85rem" }}>
          {error}
        </p>
      )}
      {aviso && (
        <p role="status" style={{ color: colores.ok, fontSize: "0.85rem" }}>
          {aviso}
        </p>
      )}
    </>
  );
}

export function MotivosOperativos({ actor }: { actor: Usuario }) {
  const [datos, setDatos] = useState<api.MotivosAdmin | null>(null);
  const { error, setError, aviso, ocupado, ejecutar } = useEstado();
  const [nuevo, setNuevo] = useState<MotivoOperativo>({
    codigo: "",
    tipo: "CANCELACION",
    nombre: "",
    activo: true,
    requiere_descripcion: false,
  });

  const cargar = useCallback(() => {
    api
      .listarMotivosAdmin()
      .then(setDatos)
      .catch((causa: unknown) => setError(mensaje(causa)));
  }, [setError]);
  useEffect(cargar, [cargar]);

  if (!datos) return <Mensajes error={error} aviso={aviso} />;
  const bloqueado = ocupado || !datos.editable;

  const editar = (motivo: MotivoOperativo, cambio: Partial<MotivoOperativo>) =>
    ejecutar(
      () => api.editarMotivo(actor.id, { ...motivo, ...cambio }),
      `Se guardó el motivo ${motivo.codigo}.`,
      cargar,
    );

  return (
    <section>
      <h3 style={{ margin: "0 0 0.5rem" }}>Motivos de cancelación e interrupción</h3>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Cada catálogo es independiente. «Otro» exige una descripción. Desactivar
        un motivo no cambia lo ya registrado.
      </p>
      <Mensajes error={error} aviso={aviso} />
      {TIPOS.map((tipo) => (
        <div key={tipo.valor} style={{ margin: "0 0 0.8rem" }}>
          <h4 style={{ margin: "0 0 0.3rem" }}>{tipo.texto}</h4>
          <table style={{ borderCollapse: "collapse", fontSize: "0.85rem" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", paddingRight: "0.8rem" }}>Código</th>
                <th style={{ textAlign: "left", paddingRight: "0.8rem" }}>Nombre</th>
                <th style={{ paddingRight: "0.8rem" }}>Exige descripción</th>
                <th>Vigente</th>
              </tr>
            </thead>
            <tbody>
              {datos.motivos
                .filter((m) => m.tipo === tipo.valor)
                .map((motivo) => (
                  <tr key={motivo.codigo}>
                    <td style={{ paddingRight: "0.8rem" }}>{motivo.codigo}</td>
                    <td style={{ paddingRight: "0.8rem" }}>{motivo.nombre}</td>
                    <td style={{ textAlign: "center" }}>
                      <input
                        type="checkbox"
                        aria-label={`${motivo.nombre}: exige descripción`}
                        checked={motivo.requiere_descripcion}
                        disabled={bloqueado}
                        onChange={(evento) =>
                          editar(motivo, {
                            requiere_descripcion: evento.target.checked,
                          })
                        }
                      />
                    </td>
                    <td style={{ textAlign: "center" }}>
                      <input
                        type="checkbox"
                        aria-label={`${motivo.nombre}: vigente`}
                        checked={motivo.activo}
                        disabled={bloqueado}
                        onChange={(evento) =>
                          editar(motivo, { activo: evento.target.checked })
                        }
                      />
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      ))}
      {datos.editable && (
        <div style={{ maxWidth: 420 }}>
          <h4 style={{ margin: "0 0 0.3rem" }}>Nuevo motivo</h4>
          <Campo etiqueta="Catálogo">
            <select
              value={nuevo.tipo}
              onChange={(evento) =>
                setNuevo({ ...nuevo, tipo: evento.target.value as TipoMotivo })
              }
              disabled={bloqueado}
              style={estiloInput}
            >
              {TIPOS.map((tipo) => (
                <option key={tipo.valor} value={tipo.valor}>
                  {tipo.texto}
                </option>
              ))}
            </select>
          </Campo>
          <Campo etiqueta="Código">
            <input
              value={nuevo.codigo}
              onChange={(evento) => setNuevo({ ...nuevo, codigo: evento.target.value })}
              disabled={bloqueado}
              style={estiloInput}
            />
          </Campo>
          <Campo etiqueta="Nombre">
            <input
              value={nuevo.nombre}
              onChange={(evento) => setNuevo({ ...nuevo, nombre: evento.target.value })}
              disabled={bloqueado}
              style={estiloInput}
            />
          </Campo>
          <label style={{ display: "flex", gap: "0.4rem", margin: "0 0 0.6rem", fontSize: "0.85rem" }}>
            <input
              type="checkbox"
              checked={nuevo.requiere_descripcion}
              onChange={(evento) =>
                setNuevo({ ...nuevo, requiere_descripcion: evento.target.checked })
              }
              disabled={bloqueado}
            />
            Exige descripción
          </label>
          <Boton
            disabled={bloqueado || !nuevo.codigo.trim() || !nuevo.nombre.trim()}
            onClick={() =>
              ejecutar(
                () => api.crearMotivo(actor.id, nuevo),
                `Se agregó el motivo ${nuevo.codigo.trim().toUpperCase()}.`,
                () => {
                  setNuevo({ ...nuevo, codigo: "", nombre: "", requiere_descripcion: false });
                  cargar();
                },
              )
            }
          >
            Agregar motivo
          </Boton>
        </div>
      )}
    </section>
  );
}

export function ParametrosOperativos({ actor }: { actor: Usuario }) {
  const [datos, setDatos] = useState<api.ParametrosAdmin | null>(null);
  const [valores, setValores] = useState<Record<string, string>>({});
  const { error, setError, aviso, ocupado, ejecutar } = useEstado();

  const cargar = useCallback(() => {
    api
      .leerParametros()
      .then((leidos) => {
        setDatos(leidos);
        setValores(leidos.parametros);
      })
      .catch((causa: unknown) => setError(mensaje(causa)));
  }, [setError]);
  useEffect(cargar, [cargar]);

  if (!datos) return <Mensajes error={error} aviso={aviso} />;
  const bloqueado = ocupado || !datos.editable;

  return (
    <section style={{ maxWidth: 420 }}>
      <h3 style={{ margin: "0 0 0.5rem" }}>Parámetros</h3>
      <Mensajes error={error} aviso={aviso} />
      {Object.entries(datos.parametros).map(([clave, actual]) => (
        <div key={clave} style={{ margin: "0 0 0.6rem" }}>
          <Campo etiqueta={PARAMETROS[clave]?.texto ?? clave}>
            <input
              value={valores[clave] ?? ""}
              onChange={(evento) =>
                setValores({ ...valores, [clave]: evento.target.value })
              }
              disabled={bloqueado}
              style={estiloInput}
            />
          </Campo>
          {PARAMETROS[clave] && (
            <p style={{ margin: "0 0 0.4rem", fontSize: "0.8rem", color: colores.suave }}>
              {PARAMETROS[clave].ayuda}
            </p>
          )}
          <Boton
            disabled={bloqueado || (valores[clave] ?? "").trim() === actual}
            onClick={() =>
              ejecutar(
                () => api.guardarParametro(actor.id, clave, (valores[clave] ?? "").trim()),
                "Se guardó el parámetro.",
                cargar,
              )
            }
          >
            Guardar
          </Boton>
        </div>
      ))}
    </section>
  );
}
