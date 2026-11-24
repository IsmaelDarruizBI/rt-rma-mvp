/**
 * Tipos de reparación y Mesas de trabajo (DC23, BR-REP-040; Configuración
 * v2, CFG-03 a CFG-06).
 *
 * - Alta y edición en una ventana, sin campo de código: la API lo genera
 *   (TR-NNN) y la confirmación lo informa.
 * - El precio exige PRECIOS_GESTIONAR (D3): sin él se ve pero no se edita,
 *   y el alta (que fija precio) no se ofrece.
 * - Garantías (CFG-06): solo los plazos con y sin check-in. El plazo
 *   genérico y la política RMA no se muestran ni se envían: la API los
 *   conserva.
 * - El listado se actualiza con lo que devuelve la API, sin recargar.
 * - DEC-AJ-14: «Insumos necesarios» de cada Tipo (previstos concretos y
 *   requisitos por categoría), en su ventana.
 * Lo ya registrado en las Órdenes no cambia: cada trabajo guardó su copia.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/configuracion";
import type {
  CatalogoConfigurable,
  DatosTipo,
  InsumosNecesariosAdmin,
  ModeloAdmin,
} from "../../api/configuracion";
import { TIPO_REPARACION_OTROS } from "../../api/ordenes";
import {
  EncabezadoListado,
  FormularioModal,
  Mensajes,
  mensajeDe,
  useComando,
} from "../../components/FormularioModal";
import { Boton, Campo, colores, estiloInput, importe } from "../../components/ui";
import { puede } from "../../lib/roles";
import type { TipoReparacion, Usuario } from "../../types/api";
import { cambiosDePrecios } from "../ordenes-reparacion/precioModelo";
import { VentanaInsumosNecesarios } from "./VentanaInsumosNecesarios";
import { conInsumosDelTipo, resumenInsumosNecesarios } from "./insumosNecesarios";
import { conElemento, precioValido, textoGarantias } from "./listados";

const SOLO_ADMINISTRACION = ["ADMINISTRADOR"];

function datosDe(tipo: TipoReparacion): DatosTipo {
  return {
    nombre: tipo.nombre,
    precio: String(tipo.precio),
    puntaje: tipo.puntaje,
    activo: tipo.activo ?? true,
    garantia_con_checkin: tipo.garantia_con_checkin ?? 90,
    garantia_sin_checkin: tipo.garantia_sin_checkin ?? 30,
    precio_por_modelo: tipo.precio_por_modelo ?? false,
  };
}

const NUEVO: DatosTipo = {
  nombre: "",
  precio: "",
  puntaje: 0,
  activo: true,
  garantia_con_checkin: 90,
  garantia_sin_checkin: 30,
  precio_por_modelo: false,
};

/** DEC-AJ-12: «Por modelo (12 modelos)» en lugar del precio único. */
function textoPrecioDeTipo(tipo: TipoReparacion): string {
  if (!tipo.precio_por_modelo) return importe(String(tipo.precio));
  const cantidad = Object.keys(tipo.precios_modelo ?? {}).length;
  return `Por modelo (${cantidad} ${cantidad === 1 ? "modelo" : "modelos"})`;
}

function CamposTipo({
  datos,
  onCambio,
  editaPrecio,
}: {
  datos: DatosTipo;
  onCambio: (datos: DatosTipo) => void;
  editaPrecio: boolean;
}) {
  const numero = (campo: keyof DatosTipo, etiqueta: string) => (
    <Campo etiqueta={etiqueta}>
      <input
        type="number"
        min={0}
        value={datos[campo] as number}
        onChange={(e) => onCambio({ ...datos, [campo]: Number(e.target.value) })}
        style={estiloInput}
      />
    </Campo>
  );
  return (
    <>
      <Campo etiqueta="Nombre">
        <input
          value={datos.nombre}
          onChange={(e) => onCambio({ ...datos, nombre: e.target.value })}
          style={estiloInput}
        />
      </Campo>
      <label style={{ display: "flex", gap: "0.4rem", alignItems: "center", margin: "0 0 0.6rem" }}>
        <input
          type="checkbox"
          checked={datos.precio_por_modelo}
          disabled={!editaPrecio}
          onChange={(e) => onCambio({ ...datos, precio_por_modelo: e.target.checked })}
        />
        Precio por modelo
      </label>
      {datos.precio_por_modelo ? (
        <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.suave }}>
          El precio sale de la grilla de precios por modelo. Un modelo sin precio no usa
          ningún precio de respaldo: el trabajo lleva un precio manual autorizado o queda
          pendiente.
        </p>
      ) : (
        <Campo etiqueta={editaPrecio ? "Precio" : "Precio (lo cambia quien gestiona precios)"}>
          <input
            inputMode="decimal"
            value={datos.precio}
            readOnly={!editaPrecio}
            aria-readonly={!editaPrecio}
            onChange={(e) => onCambio({ ...datos, precio: e.target.value })}
            style={{ ...estiloInput, background: editaPrecio ? "#fff" : colores.fondo }}
          />
        </Campo>
      )}
      {numero("puntaje", "Puntaje")}
      {numero("garantia_con_checkin", "Garantía con check-in (días)")}
      {numero("garantia_sin_checkin", "Garantía sin check-in (días)")}
    </>
  );
}

export function TiposReparacion({
  actor,
  onCambio,
}: {
  actor: Usuario;
  /** Los tipos cambiaron (el alta de Órdenes los ofrece). */
  onCambio?: () => void;
}) {
  const [catalogo, setCatalogo] = useState<CatalogoConfigurable | null>(null);
  const [ventana, setVentana] = useState<{ tipo: TipoReparacion | null; datos: DatosTipo } | null>(
    null,
  );
  const [resaltado, setResaltado] = useState<string | null>(null);
  const [grilla, setGrilla] = useState<TipoReparacion | null>(null);
  // DEC-AJ-14: sin la lectura (backend anterior) la columna no se muestra.
  const [necesarios, setNecesarios] = useState<InsumosNecesariosAdmin | null>(null);
  const [insumosDe, setInsumosDe] = useState<TipoReparacion | null>(null);
  const { error, setError, aviso, setAviso, ocupado, ejecutar } = useComando();
  const editaPrecio = puede(actor, "PRECIOS_GESTIONAR", SOLO_ADMINISTRACION);

  const cargar = useCallback(() => {
    api.obtenerCatalogo().then(setCatalogo).catch((causa: unknown) => setError(mensajeDe(causa)));
    api
      .obtenerInsumosNecesarios()
      .then(setNecesarios)
      .catch(() => setNecesarios(null));
  }, [setError]);
  useEffect(cargar, [cargar]);

  if (!catalogo) return <Mensajes error={error} aviso={aviso} />;
  const editable = catalogo.editable;

  const guardado = (tipo: TipoReparacion, texto: string) => {
    setCatalogo({ ...catalogo, tipos: conElemento(catalogo.tipos, tipo, (t) => t.id) });
    setResaltado(tipo.id);
    setError(null);
    setAviso(texto);
    onCambio?.();
  };

  // Con precio por modelo, el precio único no se pide (se envía el que
  // tenía o 0 en un alta: no se usa).
  const listo =
    ventana !== null &&
    ventana.datos.nombre.trim() !== "" &&
    (ventana.datos.precio_por_modelo || precioValido(ventana.datos.precio));

  return (
    <section>
      <EncabezadoListado
        titulo="Tipos de reparación"
        nuevo={editable && editaPrecio ? "Nuevo tipo" : undefined}
        onNuevo={() => setVentana({ tipo: null, datos: NUEVO })}
      />
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Un cambio de precio, puntaje o garantía vale para los trabajos nuevos:
        los ya cargados conservan lo que se les aplicó.
        {!editable && " En este entorno (modo JSON) son de solo lectura."}
      </p>
      <Mensajes error={error} aviso={aviso} />
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: "0.85rem", minWidth: 560 }}>
          <thead>
            <tr>
              {[
                "Código",
                "Nombre",
                "Precio",
                "Puntaje",
                "Garantía (días)",
                ...(necesarios ? ["Insumos necesarios"] : []),
                "Vigente",
                "",
              ].map((t) => (
                <th key={t} style={{ textAlign: "left", padding: "0.25rem 0.5rem" }}>
                  {t}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {catalogo.tipos.map((tipo) => (
              <tr
                key={tipo.id}
                style={{ background: resaltado === tipo.id ? "#eff6ff" : undefined }}
              >
                <td style={{ padding: "0.25rem 0.5rem" }}>{tipo.id}</td>
                <td style={{ padding: "0.25rem 0.5rem" }}>{tipo.nombre}</td>
                <td style={{ padding: "0.25rem 0.5rem" }}>
                  {textoPrecioDeTipo(tipo)}
                  {tipo.precio_por_modelo && (
                    <>
                      {" "}
                      <Boton variante="secundario" disabled={ocupado} onClick={() => setGrilla(tipo)}>
                        {editable && editaPrecio ? "Editar precios" : "Ver precios"}
                      </Boton>
                    </>
                  )}
                </td>
                <td style={{ padding: "0.25rem 0.5rem" }}>{tipo.puntaje}</td>
                <td style={{ padding: "0.25rem 0.5rem" }}>{textoGarantias(tipo)}</td>
                {necesarios && (
                  <td style={{ padding: "0.25rem 0.5rem" }}>
                    {tipo.id === TIPO_REPARACION_OTROS ? (
                      <span style={{ color: colores.suave }}>No corresponde</span>
                    ) : (
                      <>
                        {resumenInsumosNecesarios(necesarios, tipo.id)}{" "}
                        <Boton
                          variante="secundario"
                          disabled={ocupado}
                          onClick={() => setInsumosDe(tipo)}
                        >
                          {necesarios.editable ? "Editar insumos" : "Ver insumos"}
                        </Boton>
                      </>
                    )}
                  </td>
                )}
                <td style={{ padding: "0.25rem 0.5rem", textAlign: "center" }}>
                  <input
                    type="checkbox"
                    aria-label={`${tipo.nombre}: vigente`}
                    checked={tipo.activo !== false}
                    disabled={!editable || ocupado}
                    onChange={(e) =>
                      void ejecutar(
                        () =>
                          api.editarTipo(actor.id, tipo.id, {
                            ...datosDe(tipo),
                            activo: e.target.checked,
                          }),
                        `Se guardó ${tipo.id}.`,
                      ).then((t) => t && guardado(t, `Se guardó ${t.id}.`))
                    }
                  />
                </td>
                <td style={{ padding: "0.25rem 0.5rem" }}>
                  {editable && (
                    <Boton
                      variante="secundario"
                      disabled={ocupado}
                      onClick={() => setVentana({ tipo, datos: datosDe(tipo) })}
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
      {ventana && (
        <FormularioModal
          titulo={ventana.tipo ? `Editar ${ventana.tipo.id}` : "Nuevo tipo de reparación"}
          textoConfirmar={ventana.tipo ? "Guardar" : "Crear tipo"}
          listo={listo}
          onCerrar={() => setVentana(null)}
          onConfirmar={async () => {
            const { tipo, datos } = ventana;
            const precio = datos.precio.trim();
            const limpio = {
              ...datos,
              nombre: datos.nombre.trim(),
              precio: datos.precio_por_modelo && !precioValido(precio) ? "0" : precio,
            };
            const resultado = tipo
              ? await api.editarTipo(actor.id, tipo.id, limpio)
              : await api.crearTipo(actor.id, limpio);
            guardado(
              resultado,
              tipo ? `Se guardó ${resultado.id}.` : `Se creó ${resultado.id} ${resultado.nombre}.`,
            );
          }}
        >
          <CamposTipo
            datos={ventana.datos}
            editaPrecio={editaPrecio}
            onCambio={(datos) => setVentana({ ...ventana, datos })}
          />
          {!ventana.tipo && (
            <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.suave }}>
              El código se asigna al guardar.
            </p>
          )}
        </FormularioModal>
      )}
      {insumosDe && necesarios && (
        <VentanaInsumosNecesarios
          actor={actor}
          tipo={insumosDe}
          datos={necesarios}
          editable={necesarios.editable}
          onCerrar={() => setInsumosDe(null)}
          onGuardado={(previstos, requisitos, cambios) => {
            setNecesarios(conInsumosDelTipo(necesarios, insumosDe.id, previstos, requisitos));
            setResaltado(insumosDe.id);
            setError(null);
            setAviso(
              `Se guardaron los insumos necesarios de ${insumosDe.id} (${cambios} ${
                cambios === 1 ? "cambio" : "cambios"
              }).`,
            );
          }}
        />
      )}
      {grilla && (
        <PreciosPorModelo
          actor={actor}
          tipo={grilla}
          editable={editable && editaPrecio}
          onCerrar={() => setGrilla(null)}
          onGuardado={(tipo, cantidad) => {
            guardado(tipo, `Se guardaron ${cantidad} precios de ${tipo.id}.`);
            setGrilla(null);
          }}
        />
      )}
    </section>
  );
}

/**
 * DEC-AJ-12: la grilla de precios de un Tipo por modelo (edición
 * individual). Una celda vacía retira el precio de ese modelo; se envían
 * solo los cambios, todos juntos (todo o nada), con auditoría.
 */
function PreciosPorModelo({
  actor,
  tipo,
  editable,
  onCerrar,
  onGuardado,
}: {
  actor: Usuario;
  tipo: TipoReparacion;
  editable: boolean;
  onCerrar: () => void;
  onGuardado: (tipo: TipoReparacion, cantidad: number) => void;
}) {
  const vigentes = tipo.precios_modelo ?? {};
  const [modelos, setModelos] = useState<ModeloAdmin[] | null>(null);
  const [editados, setEditados] = useState<Record<string, string>>(() => ({ ...vigentes }));
  const [filtro, setFiltro] = useState("");
  const [errorCarga, setErrorCarga] = useState<string | null>(null);
  useEffect(() => {
    api
      .obtenerModelosAdmin()
      .then((datos) => setModelos(datos.modelos))
      .catch((causa: unknown) => setErrorCarga(mensajeDe(causa)));
  }, []);
  const { cambios, invalidos } = cambiosDePrecios(vigentes, editados);
  const visibles = (modelos ?? []).filter(
    (m) =>
      (m.activo || vigentes[m.id] !== undefined) &&
      m.nombre.toLowerCase().includes(filtro.trim().toLowerCase()),
  );
  return (
    <FormularioModal
      amplio
      titulo={`Precios por modelo · ${tipo.id} ${tipo.nombre}`}
      textoConfirmar={editable ? `Guardar ${cambios.length} cambios` : "Cerrar"}
      listo={!editable || (cambios.length > 0 && invalidos.length === 0)}
      onCerrar={onCerrar}
      onConfirmar={async () => {
        if (!editable) return onCerrar();
        const resultado = await api.guardarPreciosModelo(actor.id, tipo.id, cambios);
        onGuardado(resultado.tipo, resultado.cambios.length);
      }}
    >
      {errorCarga && <p role="alert">{errorCarga}</p>}
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Vacío: sin precio de catálogo para ese modelo (el trabajo lleva un precio manual
        autorizado o queda pendiente). Los trabajos ya cargados conservan su precio.
      </p>
      <Campo etiqueta="Buscar modelo">
        <input value={filtro} onChange={(e) => setFiltro(e.target.value)} style={estiloInput} />
      </Campo>
      <div style={{ maxHeight: "50vh", overflowY: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: "0.85rem", width: "100%" }}>
          <tbody>
            {visibles.map((modelo) => (
              <tr key={modelo.id}>
                <td style={{ padding: "0.2rem 0.4rem", color: colores.suave }}>{modelo.id}</td>
                <td style={{ padding: "0.2rem 0.4rem" }}>
                  {modelo.nombre}
                  {!modelo.activo && " (no vigente)"}
                </td>
                <td style={{ padding: "0.2rem 0.4rem" }}>
                  <input
                    aria-label={`Precio para ${modelo.nombre}`}
                    inputMode="decimal"
                    value={editados[modelo.id] ?? ""}
                    readOnly={!editable}
                    onChange={(e) => setEditados({ ...editados, [modelo.id]: e.target.value })}
                    style={{
                      ...estiloInput,
                      borderColor: invalidos.includes(modelo.id) ? colores.error : undefined,
                    }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {invalidos.length > 0 && (
        <p style={{ margin: "0.4rem 0 0", color: colores.error, fontSize: "0.8rem" }}>
          Precio inválido en {invalidos.join(", ")} (hasta dos decimales).
        </p>
      )}
    </FormularioModal>
  );
}

/** Tipos de reparación habilitados en cada Mesa de trabajo (BR-REP-011). */
export function MesasTrabajo({ actor }: { actor: Usuario }) {
  const [catalogo, setCatalogo] = useState<CatalogoConfigurable | null>(null);
  const [mesas, setMesas] = useState<Record<string, string[]>>({});
  const { error, setError, aviso, ocupado, ejecutar } = useComando();

  const cargar = useCallback(() => {
    api
      .obtenerCatalogo()
      .then((datos) => {
        setCatalogo(datos);
        setMesas(Object.fromEntries(datos.mesas.map((m) => [m.id, m.tipos])));
      })
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, [setError]);
  useEffect(cargar, [cargar]);

  if (!catalogo) return <Mensajes error={error} aviso={aviso} />;
  const bloqueado = ocupado || !catalogo.editable;

  return (
    <section>
      <h3 style={{ margin: "0 0 0.5rem" }}>Mesas de trabajo</h3>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Los tipos de reparación que cada Mesa puede trabajar.
      </p>
      <Mensajes error={error} aviso={aviso} />
      {catalogo.mesas.map((mesa) => (
        <div key={mesa.id} style={{ marginBottom: "0.8rem" }}>
          <strong>
            {mesa.nombre} ({mesa.id})
          </strong>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.6rem", margin: "0.3rem 0" }}>
            {catalogo.tipos.map((tipo) => (
              <label key={tipo.id} style={{ fontSize: "0.85rem" }}>
                <input
                  type="checkbox"
                  disabled={bloqueado}
                  checked={(mesas[mesa.id] ?? []).includes(tipo.id)}
                  onChange={(e) =>
                    setMesas({
                      ...mesas,
                      [mesa.id]: e.target.checked
                        ? [...(mesas[mesa.id] ?? []), tipo.id]
                        : (mesas[mesa.id] ?? []).filter((t) => t !== tipo.id),
                    })
                  }
                />{" "}
                {tipo.nombre}
              </label>
            ))}
          </div>
          <Boton
            disabled={bloqueado}
            onClick={() =>
              void ejecutar(
                () => api.guardarTiposDeMesa(actor.id, mesa.id, mesas[mesa.id] ?? []),
                `Se guardaron los tipos de ${mesa.nombre}.`,
              )
            }
          >
            Guardar tipos de la Mesa
          </Boton>
        </div>
      ))}
    </section>
  );
}
