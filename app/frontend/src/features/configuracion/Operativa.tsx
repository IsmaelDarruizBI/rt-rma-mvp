/**
 * Motivos de cancelación e interrupción y recargos por medio de pago
 * (DEC-MI-13 y 15; UX-08). Cada cambio queda auditado. Desactivar un motivo
 * no cambia lo registrado: cada cancelación o interrupción guardó el texto
 * del motivo de ese momento. En la persistencia JSON (demo) son de solo
 * lectura.
 *
 * Configuración v2: el alta y la edición de motivos van en una ventana y
 * el código lo genera la API (CANC-NNN o INT-NNN, CFG-01 y CFG-04). El
 * plazo de retiro ya no se muestra (CFG-07): sigue rigiendo en el backend
 * con su valor.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/operativa";
import type { MotivoOperativo, TipoMotivo } from "../../api/operativa";
import {
  EncabezadoListado,
  FormularioModal,
  Mensajes,
  mensajeDe,
  useComando,
} from "../../components/FormularioModal";
import { Boton, Campo, colores, estiloInput } from "../../components/ui";
import type { Usuario } from "../../types/api";
import { conElemento } from "./listados";

const TIPOS: { valor: TipoMotivo; texto: string }[] = [
  { valor: "CANCELACION", texto: "Cancelación" },
  { valor: "INTERRUPCION", texto: "Interrupción" },
];

type Ventana = { motivo: MotivoOperativo | null; datos: Omit<MotivoOperativo, "codigo"> };

export function MotivosOperativos({ actor }: { actor: Usuario }) {
  const [datos, setDatos] = useState<api.MotivosAdmin | null>(null);
  const [ventana, setVentana] = useState<Ventana | null>(null);
  const [resaltado, setResaltado] = useState<string | null>(null);
  const { error, setError, aviso, setAviso, ocupado, ejecutar } = useComando();

  const cargar = useCallback(() => {
    api
      .listarMotivosAdmin()
      .then(setDatos)
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, [setError]);
  useEffect(cargar, [cargar]);

  if (!datos) return <Mensajes error={error} aviso={aviso} />;
  const bloqueado = ocupado || !datos.editable;

  const guardado = (motivo: MotivoOperativo, texto: string) => {
    setDatos({ ...datos, motivos: conElemento(datos.motivos, motivo, (m) => m.codigo) });
    setResaltado(motivo.codigo);
    setError(null);
    setAviso(texto);
  };

  const editar = (motivo: MotivoOperativo, cambio: Partial<MotivoOperativo>) =>
    void ejecutar(
      () => api.editarMotivo(actor.id, { ...motivo, ...cambio }),
      `Se guardó el motivo ${motivo.codigo}.`,
    ).then((m) => m && guardado(m, `Se guardó el motivo ${m.codigo}.`));

  return (
    <section>
      <EncabezadoListado
        titulo="Motivos de cancelación e interrupción"
        nuevo={datos.editable ? "Nuevo motivo" : undefined}
        onNuevo={() =>
          setVentana({
            motivo: null,
            datos: { tipo: "CANCELACION", nombre: "", activo: true, requiere_descripcion: false },
          })
        }
      />
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Cada catálogo es independiente. «Otro» exige una descripción. Desactivar
        un motivo no cambia lo ya registrado.
      </p>
      <Mensajes error={error} aviso={aviso} />
      {TIPOS.map((tipo) => (
        <div key={tipo.valor} style={{ margin: "0 0 0.8rem", overflowX: "auto" }}>
          <h4 style={{ margin: "0 0 0.3rem" }}>{tipo.texto}</h4>
          <table style={{ borderCollapse: "collapse", fontSize: "0.85rem" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", paddingRight: "0.8rem" }}>Código</th>
                <th style={{ textAlign: "left", paddingRight: "0.8rem" }}>Nombre</th>
                <th style={{ paddingRight: "0.8rem" }}>Exige descripción</th>
                <th style={{ paddingRight: "0.8rem" }}>Vigente</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {datos.motivos
                .filter((m) => m.tipo === tipo.valor)
                .map((motivo) => (
                  <tr
                    key={motivo.codigo}
                    style={{ background: resaltado === motivo.codigo ? "#eff6ff" : undefined }}
                  >
                    <td style={{ paddingRight: "0.8rem" }}>{motivo.codigo}</td>
                    <td style={{ paddingRight: "0.8rem" }}>{motivo.nombre}</td>
                    <td style={{ textAlign: "center" }}>
                      <input
                        type="checkbox"
                        aria-label={`${motivo.nombre}: exige descripción`}
                        checked={motivo.requiere_descripcion}
                        disabled={bloqueado}
                        onChange={(evento) =>
                          editar(motivo, { requiere_descripcion: evento.target.checked })
                        }
                      />
                    </td>
                    <td style={{ textAlign: "center" }}>
                      <input
                        type="checkbox"
                        aria-label={`${motivo.nombre}: vigente`}
                        checked={motivo.activo}
                        disabled={bloqueado}
                        onChange={(evento) => editar(motivo, { activo: evento.target.checked })}
                      />
                    </td>
                    <td style={{ paddingLeft: "0.6rem" }}>
                      {datos.editable && (
                        <Boton
                          variante="secundario"
                          disabled={bloqueado}
                          onClick={() => {
                            const { codigo: _codigo, ...resto } = motivo;
                            setVentana({ motivo, datos: resto });
                          }}
                        >
                          Editar
                        </Boton>
                      )}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      ))}
      {ventana && (
        <FormularioModal
          titulo={ventana.motivo ? `Editar ${ventana.motivo.codigo}` : "Nuevo motivo"}
          textoConfirmar={ventana.motivo ? "Guardar" : "Crear motivo"}
          listo={ventana.datos.nombre.trim() !== ""}
          onCerrar={() => setVentana(null)}
          onConfirmar={async () => {
            const limpio = { ...ventana.datos, nombre: ventana.datos.nombre.trim() };
            const motivo = ventana.motivo
              ? await api.editarMotivo(actor.id, { ...limpio, codigo: ventana.motivo.codigo })
              : await api.crearMotivo(actor.id, limpio);
            guardado(
              motivo,
              ventana.motivo
                ? `Se guardó el motivo ${motivo.codigo}.`
                : `Se creó el motivo ${motivo.codigo} «${motivo.nombre}».`,
            );
          }}
        >
          <Campo etiqueta="Catálogo">
            <select
              value={ventana.datos.tipo}
              disabled={ventana.motivo !== null}
              onChange={(evento) =>
                setVentana({
                  ...ventana,
                  datos: { ...ventana.datos, tipo: evento.target.value as TipoMotivo },
                })
              }
              style={estiloInput}
            >
              {TIPOS.map((tipo) => (
                <option key={tipo.valor} value={tipo.valor}>
                  {tipo.texto}
                </option>
              ))}
            </select>
          </Campo>
          <Campo etiqueta="Nombre">
            <input
              value={ventana.datos.nombre}
              onChange={(evento) =>
                setVentana({ ...ventana, datos: { ...ventana.datos, nombre: evento.target.value } })
              }
              style={estiloInput}
            />
          </Campo>
          <label style={{ display: "flex", gap: "0.4rem", margin: "0 0 0.6rem", fontSize: "0.85rem" }}>
            <input
              type="checkbox"
              checked={ventana.datos.requiere_descripcion}
              onChange={(evento) =>
                setVentana({
                  ...ventana,
                  datos: { ...ventana.datos, requiere_descripcion: evento.target.checked },
                })
              }
            />
            Exige descripción
          </label>
          {!ventana.motivo && (
            <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.suave }}>
              El código se asigna al guardar.
            </p>
          )}
        </FormularioModal>
      )}
    </section>
  );
}

/**
 * UX-08: recargo porcentual por medio de pago. Se suma a cada cobro con
 * ese medio y queda como copia en el pago; cambiarlo no recalcula pagos ya
 * registrados. Cada cambio queda en la auditoría.
 */
export function RecargosMedioPago({ actor }: { actor: Usuario }) {
  const [datos, setDatos] = useState<api.MediosPagoAdmin | null>(null);
  const [valores, setValores] = useState<Record<string, string>>({});
  const { error, setError, aviso, ocupado, ejecutar: ejecutarComando } = useComando();
  const ejecutar = (accion: () => Promise<unknown>, exito: string, despues: () => void) =>
    void ejecutarComando(accion, exito).then((r) => r !== undefined && despues());

  const cargar = useCallback(() => {
    api
      .leerMediosPago()
      .then((leidos) => {
        setDatos(leidos);
        setValores(
          Object.fromEntries(
            leidos.medios.map((m) => [m.id, m.recargo_porcentaje ?? "0"]),
          ),
        );
      })
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, [setError]);
  useEffect(cargar, [cargar]);

  if (!datos) return <Mensajes error={error} aviso={aviso} />;
  const bloqueado = ocupado || !datos.editable;

  return (
    <section style={{ maxWidth: 420 }}>
      <h3 style={{ margin: "0 0 0.3rem" }}>Recargo por medio de pago</h3>
      <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.suave }}>
        Porcentaje que se suma a cada cobro con ese medio. Al saldo de la
        Orden se imputa el importe; el recargo se cobra aparte. Los pagos ya
        registrados no cambian.
      </p>
      <Mensajes error={error} aviso={aviso} />
      {datos.medios.map((medio) => {
        const actual = medio.recargo_porcentaje ?? "0";
        const valor = valores[medio.id] ?? "";
        return (
          <div
            key={medio.id}
            style={{ display: "flex", alignItems: "flex-end", gap: "0.5rem" }}
          >
            <div style={{ flex: 1 }}>
              <Campo etiqueta={`${medio.nombre} (%)`}>
                <input
                  value={valor}
                  inputMode="decimal"
                  onChange={(evento) =>
                    setValores({ ...valores, [medio.id]: evento.target.value })
                  }
                  disabled={bloqueado}
                  style={estiloInput}
                />
              </Campo>
            </div>
            <div style={{ marginBottom: "0.6rem" }}>
              <Boton
                disabled={bloqueado || Number(valor) === Number(actual) || valor.trim() === ""}
                onClick={() =>
                  ejecutar(
                    () => api.guardarRecargo(actor.id, medio.id, valor.trim()),
                    `Se guardó el recargo de ${medio.nombre}.`,
                    cargar,
                  )
                }
              >
                Guardar
              </Boton>
            </div>
          </div>
        );
      })}
      {!datos.editable && (
        <p style={{ fontSize: "0.8rem", color: colores.suave }}>
          Se configura sobre la base PostgreSQL.
        </p>
      )}
    </section>
  );
}
