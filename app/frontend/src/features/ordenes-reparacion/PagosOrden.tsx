/**
 * Pagos y movimientos de la Orden (FEAT-REP-007, BR-REP-017/038).
 *
 * Muestra la cuenta -Subtotal y ajustes comerciales (si hay), Total,
 * Pagado válido, Devuelto y Saldo o crédito a favor-, el historial de los
 * ajustes (DEC-AJ-10) y la lista cronológica de pagos, anulaciones y
 * devoluciones de dinero. Un ajuste no cambia el precio de ningún trabajo
 * ni los pagos. Los formularios aparecen solo si el backend los ofrece en
 * `acciones_financieras`; el backend vuelve a validar todo (rol, importe,
 * saldo, duplicados) igual.
 */

import { type ReactNode, useEffect, useState } from "react";

import type { DatosDevolucionDinero } from "../../api/ordenes";
import {
  Boton,
  Campo,
  Etiqueta,
  colores,
  estiloInput,
  fechaCorta,
  importe,
} from "../../components/ui";
import type {
  Accion,
  ClaseAjuste,
  MedioPago,
  Orden,
  RegistroDescuento,
  SituacionFinanciera,
  TipoDescuento,
  Usuario,
} from "../../types/api";
import {
  ETIQUETA_OPERACION,
  PERMISO_DE_CLASE,
  ROLES_AJUSTE,
  ROLES_REVERTIR,
  baseDelDestino,
  etiquetaClase,
  historialDeAjustes,
  vigenteDelDestino,
  vistaPrevia,
} from "./ajusteComercial";
import { nombreDeUsuario } from "./DetalleOrden";
import { ESTADO_PAGO, etiqueta } from "./etiquetas";
import { TituloAccion, UbicacionAccion } from "./presentacion";
import { recargoADevolver, recargoDe } from "./recepcionUx";
import { puede, tieneAlguno } from "../../lib/roles";

interface Props {
  orden: Orden;
  actor: Usuario | null;
  usuarios: Usuario[];
  medios: MedioPago[];
  ocupado: boolean;
  onPagar: (
    monto: string,
    metodo: string,
    referencia: string | null,
    operacionId: string,
  ) => void;
  onAnular: (pagoId: string, motivo: string) => void;
  onDevolver: (datos: DatosDevolucionDinero) => void;
  /** `tipo: null` quita el ajuste vigente (descuento o cortesía). */
  onDescontar: (
    tipo: TipoDescuento | null,
    valor: string | null,
    motivo: string,
    clase: ClaseAjuste,
    /** DEC-MI-03: el trabajo del ajuste; sin valor, la Orden. */
    detalleId?: string | null,
  ) => void;
  /** DEC-AJ-10: revertir el ajuste vigente de un destino. */
  onRevertirAjuste?: (ajusteId: string, motivo: string) => void;
  /** DEC-AJ-10: revertirlo y registrar el correcto, enlazados. */
  onCorregirAjuste?: (
    ajusteId: string,
    tipo: TipoDescuento,
    valor: string,
    clase: ClaseAjuste,
    motivo: string,
  ) => void;
}

const ETIQUETA_CONDICION_COMERCIAL: Record<string, string> = {
  COBRABLE: "Cobrable al cliente",
  NO_COBRABLE_AL_CLIENTE: "No cobrable (equipo RT interno)",
  NO_COBRABLE: "No cobrable (garantía)",
};

const AVISO: Record<
  SituacionFinanciera,
  { texto: (orden: Orden) => string; color: string } | null
> = {
  SALDO_PENDIENTE: {
    texto: (orden) =>
      `Saldo pendiente de cobro: ${importe(orden.resumen.saldo)}`,
    color: colores.alerta,
  },
  SALDO_A_FAVOR: {
    texto: (orden) =>
      `Saldo a favor del cliente: ${importe(orden.resumen.credito_a_favor)} · Devolución pendiente`,
    color: colores.error,
  },
  SALDADA: { texto: () => "Cuenta saldada", color: colores.ok },
  SIN_MOVIMIENTOS: null,
  NO_COBRABLE: null,
};

/** Clave del envío: un reintento del mismo formulario no duplica nada. */
function nuevaOperacion(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `op-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function nombreDeMedio(medios: MedioPago[], medioId: string | null): string {
  if (!medioId) return "—";
  return medios.find((medio) => medio.id === medioId)?.nombre ?? medioId;
}

export function habilitada(accion: Accion, actor: Usuario | null): boolean {
  return (
    actor !== null &&
    (accion.roles.length === 0 || tieneAlguno(actor, accion.roles))
  );
}

export function PagosYMovimientos(props: Props) {
  const { orden, medios, usuarios } = props;
  const { resumen } = orden;
  const cobrable = resumen.condicion_comercial === "COBRABLE";
  const saldo = Number(resumen.saldo);
  const descuento = resumen.descuento;
  const ajustesDetalle = resumen.ajustes_detalle ?? [];
  const filas: [string, string][] = [
    ...(descuento || ajustesDetalle.length > 0
      ? ([["Subtotal", importe(resumen.subtotal)]] as [string, string][])
      : []),
    ...ajustesDetalle.map(
      (a) =>
        [
          `${a.clase === "CORTESIA" ? "Cortesía" : "Descuento"} ${a.detalle_id} (${a.descripcion})`,
          `−${importe(a.importe)}`,
        ] as [string, string],
    ),
    ...(descuento
      ? ([
          [
            `${descuento.clase === "CORTESIA" ? "Cortesía" : "Descuento"}${ajustesDetalle.length > 0 ? " de la Orden" : ""} (${descuento.descripcion})`,
            `−${importe(descuento.importe)}`,
          ],
        ] as [string, string][])
      : []),
    [cobrable ? "Total" : "Total (nominal)", importe(resumen.total)],
    ["Pagado válido", importe(resumen.pagado)],
    ["Devuelto", importe(resumen.devuelto)],
    [
      !cobrable
        ? "Saldo (nominal)"
        : saldo < 0
          ? "Crédito a favor del cliente"
          : "Saldo pendiente",
      importe(saldo < 0 ? resumen.credito_a_favor : resumen.saldo),
    ],
    ["Estado de pago", etiqueta(ESTADO_PAGO, resumen.estado_pago)],
  ];
  const aviso = AVISO[resumen.situacion_financiera];
  const acciones = orden.acciones_financieras;
  const cobro = acciones.find((a) => a.codigo === "REGISTRAR_PAGO");
  const devolucion = acciones.find(
    (a) => a.codigo === "REGISTRAR_DEVOLUCION_DINERO",
  );
  const anulaciones = acciones.filter((a) => a.codigo === "ANULAR_PAGO");
  const descontar = acciones.find((a) => a.codigo === "APLICAR_DESCUENTO");
  const cortesia = acciones.find((a) => a.codigo === "OTORGAR_CORTESIA");

  return (
    <div>
      <p
        style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.suave }}
      >
        {ETIQUETA_CONDICION_COMERCIAL[resumen.condicion_comercial] ??
          resumen.condicion_comercial}
        {!cobrable && ": el total/saldo son nominales, no una deuda a cobrar."}
      </p>
      {aviso && (
        <p
          role="status"
          style={{
            margin: "0 0 0.7rem",
            padding: "0.5rem 0.7rem",
            borderRadius: 6,
            border: `1px solid ${aviso.color}`,
            color: aviso.color,
            fontWeight: 600,
            fontSize: "0.9rem",
          }}
        >
          {aviso.texto(orden)}
        </p>
      )}
      <dl style={{ margin: 0, display: "grid", gap: "0.35rem" }}>
        {filas.map(([etiqueta, valor]) => (
          <div
            key={etiqueta}
            style={{ display: "flex", justifyContent: "space-between" }}
          >
            <dt style={{ color: colores.suave }}>{etiqueta}</dt>
            <dd style={{ margin: 0, fontWeight: 600 }}>{valor}</dd>
          </div>
        ))}
      </dl>
      <HistorialAjustes
        orden={orden}
        usuarios={usuarios}
        actor={props.actor}
        ocupado={props.ocupado}
        editable={!!(descontar || cortesia)}
        onRevertirAjuste={props.onRevertirAjuste}
        onCorregirAjuste={props.onCorregirAjuste}
      />
      <ListaMovimientos orden={orden} medios={medios} usuarios={usuarios} />
      {/* DEC-AJ-10: un solo formulario, desde «Aplicar un descuento» o
          desde «Otorgar una cortesía» (elige la clase al abrirse). */}
      {descontar && (
        <FormularioAjusteComercial
          key={`descuento-${orden.updated_at}`}
          accion={descontar}
          clasePreferida="DESCUENTO"
          descontar={descontar}
          cortesia={cortesia ?? null}
          {...props}
        />
      )}
      {cortesia && (
        <FormularioAjusteComercial
          key={`cortesia-${orden.updated_at}`}
          accion={cortesia}
          clasePreferida="CORTESIA"
          descontar={descontar ?? null}
          cortesia={cortesia}
          {...props}
        />
      )}
      {cobro && (
        <FormularioCobro
          key={`cobro-${orden.updated_at}`}
          accion={cobro}
          {...props}
        />
      )}
      {devolucion && (
        <FormularioDevolucionDinero
          key={`devolucion-${orden.updated_at}`}
          accion={devolucion}
          {...props}
        />
      )}
      {anulaciones.length > 0 && (
        <FormularioAnulacion
          key={`anulacion-${orden.updated_at}`}
          acciones={anulaciones}
          {...props}
        />
      )}
    </div>
  );
}

/**
 * DEC-AJ-10 (D-10.1): un solo formulario de Ajuste Comercial. Elige la
 * clase (descuento o cortesía, cada una con su permiso), el destino (la
 * Orden o un trabajo), el tipo (porcentaje o importe) y el motivo, con la
 * vista previa del precio original, el ajuste y el precio final. Cambiar o
 * quitar el vigente exige además el permiso de su clase (el backend lo
 * valida igual). Por debajo de lo cobrado deja saldo a favor, que se
 * devuelve antes de entregar.
 */
function FormularioAjusteComercial({
  orden,
  actor,
  ocupado,
  onDescontar,
  accion,
  clasePreferida,
  descontar,
  cortesia,
}: Props & {
  accion: Accion;
  clasePreferida: ClaseAjuste;
  descontar: Accion | null;
  cortesia: Accion | null;
}) {
  const trabajos = orden.reparaciones_detail.filter(
    (d) => d.estado !== "CANCELADO",
  );
  const permitida = (clase: ClaseAjuste) =>
    puede(
      actor,
      PERMISO_DE_CLASE[clase],
      (clase === "CORTESIA" ? cortesia : descontar)?.roles ?? ROLES_AJUSTE,
    );
  const clases = (["DESCUENTO", "CORTESIA"] as ClaseAjuste[]).filter(permitida);
  const [destino, setDestino] = useState("");
  const [clase, setClase] = useState<ClaseAjuste>(
    clases.includes(clasePreferida) ? clasePreferida : (clases[0] ?? clasePreferida),
  );
  const detalleId = destino || null;
  const vigente = vigenteDelDestino(orden, detalleId);
  const [tipo, setTipo] = useState<TipoDescuento>(vigente?.tipo ?? "PORCENTAJE");
  const [valor, setValor] = useState(vigente ? String(Number(vigente.valor)) : "");
  const [motivo, setMotivo] = useState("");
  const base = baseDelDestino(orden, detalleId);
  const previa = vistaPrevia(base, tipo, valor);
  const deshabilitado = !habilitada(accion, actor) || ocupado;
  // Cambiar o quitar el vigente exige también el permiso de su clase.
  const puedeReemplazar = !vigente || permitida(vigente.clase ?? "DESCUENTO");
  const cobrado = Number(orden.resumen.pagado) - Number(orden.resumen.devuelto);
  const listo =
    !deshabilitado &&
    clases.includes(clase) &&
    puedeReemplazar &&
    previa.valido &&
    motivo.trim() !== "";
  return (
    <Seccion titulo="Ajuste comercial" accion={accion} actor={actor}>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Descuento o cortesía sobre la Orden o sobre un trabajo. El precio de
        cada trabajo no cambia; el de la Orden se aplica sobre lo que queda
        después de los ajustes de los trabajos y no se reparte. Queda
        registrado quién, cuándo y por qué.
      </p>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        <Campo etiqueta="Clase">
          <select
            value={clase}
            disabled={deshabilitado}
            onChange={(e) => setClase(e.target.value as ClaseAjuste)}
            style={estiloInput}
          >
            {clases.map((opcion) => (
              <option key={opcion} value={opcion}>
                {etiquetaClase(opcion)}
              </option>
            ))}
          </select>
        </Campo>
        <Campo etiqueta="Sobre">
          <select
            value={destino}
            disabled={deshabilitado}
            onChange={(e) => {
              setDestino(e.target.value);
              const nuevo = vigenteDelDestino(orden, e.target.value || null);
              setTipo(nuevo?.tipo ?? "PORCENTAJE");
              setValor(nuevo ? String(Number(nuevo.valor)) : "");
            }}
            style={estiloInput}
          >
            <option value="">La Orden</option>
            {trabajos.map((d) => (
              <option key={d.id} value={d.id}>
                {d.id} · {d.tipo_reparacion_nombre ?? d.tipo_reparacion_id} ·{" "}
                {importe(d.precio)}
              </option>
            ))}
          </select>
        </Campo>
        <Campo etiqueta="Tipo">
          <select
            value={tipo}
            disabled={deshabilitado}
            onChange={(e) => setTipo(e.target.value as TipoDescuento)}
            style={estiloInput}
          >
            <option value="PORCENTAJE">Porcentaje (%)</option>
            <option value="IMPORTE">Importe fijo ($)</option>
          </select>
        </Campo>
        <div style={{ width: 140 }}>
          <Campo etiqueta={tipo === "PORCENTAJE" ? "Porcentaje" : "Importe"}>
            <input
              value={valor}
              disabled={deshabilitado}
              inputMode="decimal"
              onChange={(e) => setValor(e.target.value)}
              style={estiloInput}
            />
          </Campo>
        </div>
      </div>
      <Campo etiqueta="Motivo (obligatorio)">
        <input
          value={motivo}
          disabled={deshabilitado}
          onChange={(e) => setMotivo(e.target.value)}
          style={estiloInput}
        />
      </Campo>
      {vigente && (
        <p style={{ margin: "0.3rem 0", fontSize: "0.82rem" }}>
          Vigente en {detalleId ?? "la Orden"}: {etiquetaClase(vigente.clase)}{" "}
          {vigente.descripcion} (−{importe(vigente.importe)}).
          {!puedeReemplazar &&
            ` Cambiarlo o quitarlo exige el permiso de ${etiquetaClase(vigente.clase).toLowerCase()}.`}
        </p>
      )}
      {valor.trim() !== "" && (
        <p style={{ margin: "0 0 0.5rem", fontSize: "0.85rem" }}>
          {previa.valido ? (
            <>
              Precio original {importe(String(previa.original))} ·{" "}
              {etiquetaClase(clase)} −{importe(String(previa.ajuste))} · Precio
              final <strong>{importe(String(previa.final))}</strong>
              {!detalleId &&
                cobrado > previa.final &&
                ` · quedan ${importe(String(cobrado - previa.final))} a favor del cliente: hay que devolverlos antes de entregar el equipo.`}
            </>
          ) : (
            <span style={{ color: colores.error }}>{previa.error}</span>
          )}
        </p>
      )}
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        <Boton
          disabled={!listo}
          onClick={() =>
            onDescontar(
              tipo,
              valor.trim().replace(",", "."),
              motivo.trim(),
              clase,
              detalleId,
            )
          }
        >
          {vigente ? "Cambiar el ajuste" : "Aplicar el ajuste"}
        </Boton>
        {vigente && (
          <Boton
            variante="secundario"
            disabled={deshabilitado || !puedeReemplazar || !motivo.trim()}
            onClick={() =>
              onDescontar(
                null,
                null,
                motivo.trim(),
                vigente.clase ?? "DESCUENTO",
                detalleId,
              )
            }
          >
            Quitar el ajuste
          </Boton>
        )}
      </div>
    </Seccion>
  );
}

/**
 * Historial del Ajuste Comercial (DEC-AJ-10): cada alta, cambio, retiro,
 * corrección, reversión y recálculo, con la evidencia de los importes,
 * quién, cuándo y por qué. Sobre el ajuste vigente de cada destino, quien
 * tiene el permiso de reversión puede revertirlo o corregirlo antes de la
 * entrega. El ajuste no es un movimiento de dinero: los pagos no cambian.
 */
function HistorialAjustes({
  orden,
  usuarios,
  actor,
  ocupado,
  editable,
  onRevertirAjuste,
  onCorregirAjuste,
}: {
  orden: Orden;
  usuarios: Usuario[];
  actor: Usuario | null;
  ocupado: boolean;
  editable: boolean;
  onRevertirAjuste?: Props["onRevertirAjuste"];
  onCorregirAjuste?: Props["onCorregirAjuste"];
}) {
  const [abierto, setAbierto] = useState<{
    id: string;
    modo: "REVERTIR" | "CORREGIR";
  } | null>(null);
  const entradas = historialDeAjustes(orden);
  if (entradas.length === 0) return null;
  const puedeRevertir =
    editable && puede(actor, "AJUSTE_REVERTIR", ROLES_REVERTIR);
  return (
    <div style={{ marginTop: "0.8rem" }}>
      <h4
        style={{
          margin: "0 0 0.4rem",
          fontSize: "0.8rem",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          color: colores.suave,
        }}
      >
        Historial de ajustes comerciales
      </h4>
      <ul style={{ margin: 0, paddingLeft: "1.1rem", fontSize: "0.82rem" }}>
        {entradas.map((entrada) => (
          <li key={entrada.clave} style={{ marginBottom: "0.25rem" }}>
            <strong>{ETIQUETA_OPERACION[entrada.operacion]}</strong> ·{" "}
            <span
              style={
                entrada.revertido
                  ? { textDecoration: "line-through", color: colores.suave }
                  : undefined
              }
            >
              {entrada.descripcion}
            </span>
            {entrada.revertido && " (revertido)"}
            {entrada.evidencia && ` · ${entrada.evidencia}`}
            {entrada.motivo && ` · ${entrada.motivo}`}{" "}
            <span style={{ color: colores.suave }}>
              ({nombreDeUsuario(usuarios, entrada.usuarioId)},{" "}
              {fechaCorta(entrada.fecha)})
            </span>
            {puedeRevertir && entrada.revertible?.id && (
              <span style={{ marginLeft: "0.4rem", display: "inline-flex", gap: "0.3rem" }}>
                <Boton
                  variante="secundario"
                  disabled={ocupado}
                  onClick={() =>
                    setAbierto({ id: entrada.revertible!.id!, modo: "REVERTIR" })
                  }
                >
                  Revertir
                </Boton>
                <Boton
                  variante="secundario"
                  disabled={ocupado}
                  onClick={() =>
                    setAbierto({ id: entrada.revertible!.id!, modo: "CORREGIR" })
                  }
                >
                  Corregir
                </Boton>
              </span>
            )}
            {abierto &&
              entrada.revertible?.id === abierto.id && (
                <FormularioReversion
                  key={`${abierto.id}-${abierto.modo}`}
                  modo={abierto.modo}
                  registro={entrada.revertible}
                  actor={actor}
                  ocupado={ocupado}
                  onCancelar={() => setAbierto(null)}
                  onRevertir={(motivo) =>
                    onRevertirAjuste?.(abierto.id, motivo)
                  }
                  onCorregir={(tipo, valor, clase, motivo) =>
                    onCorregirAjuste?.(abierto.id, tipo, valor, clase, motivo)
                  }
                  base={baseDelDestino(orden, entrada.revertible.detalle_id ?? null)}
                />
              )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Revertir (motivo) o corregir (el ajuste correcto y el motivo). */
function FormularioReversion({
  modo,
  registro,
  actor,
  ocupado,
  base,
  onCancelar,
  onRevertir,
  onCorregir,
}: {
  modo: "REVERTIR" | "CORREGIR";
  registro: RegistroDescuento;
  actor: Usuario | null;
  ocupado: boolean;
  base: number;
  onCancelar: () => void;
  onRevertir: (motivo: string) => void;
  onCorregir: (
    tipo: TipoDescuento,
    valor: string,
    clase: ClaseAjuste,
    motivo: string,
  ) => void;
}) {
  const clases = (["DESCUENTO", "CORTESIA"] as ClaseAjuste[]).filter((c) =>
    puede(actor, PERMISO_DE_CLASE[c], ROLES_AJUSTE),
  );
  const [clase, setClase] = useState<ClaseAjuste>(
    registro.clase && clases.includes(registro.clase)
      ? registro.clase
      : (clases[0] ?? "DESCUENTO"),
  );
  const [tipo, setTipo] = useState<TipoDescuento>(registro.tipo ?? "PORCENTAJE");
  const [valor, setValor] = useState("");
  const [motivo, setMotivo] = useState("");
  // Al corregir, el registro equivocado deja de contar: la base del
  // destino puede cambiar (el backend la vuelve a validar).
  const previa = vistaPrevia(base, tipo, valor);
  const corregir = modo === "CORREGIR";
  const listo =
    !ocupado &&
    motivo.trim() !== "" &&
    (!corregir || (previa.valido && clases.includes(clase)));
  return (
    <div
      style={{
        margin: "0.4rem 0 0.6rem",
        padding: "0.5rem 0.7rem",
        border: `1px solid ${colores.borde}`,
        borderRadius: 6,
      }}
    >
      <p style={{ margin: "0 0 0.4rem", fontSize: "0.8rem", color: colores.suave }}>
        {corregir
          ? "Revierte el ajuste equivocado y registra el correcto en una sola operación. Los pagos no cambian."
          : "El ajuste deja de contar y vuelve a regir el anterior de este destino, si existe. Los pagos no cambian: si queda saldo a favor, se devuelve antes de entregar."}
      </p>
      {corregir && (
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <Campo etiqueta="Clase">
            <select
              value={clase}
              onChange={(e) => setClase(e.target.value as ClaseAjuste)}
              style={estiloInput}
            >
              {clases.map((opcion) => (
                <option key={opcion} value={opcion}>
                  {etiquetaClase(opcion)}
                </option>
              ))}
            </select>
          </Campo>
          <Campo etiqueta="Tipo">
            <select
              value={tipo}
              onChange={(e) => setTipo(e.target.value as TipoDescuento)}
              style={estiloInput}
            >
              <option value="PORCENTAJE">Porcentaje (%)</option>
              <option value="IMPORTE">Importe fijo ($)</option>
            </select>
          </Campo>
          <div style={{ width: 140 }}>
            <Campo etiqueta={tipo === "PORCENTAJE" ? "Porcentaje" : "Importe"}>
              <input
                value={valor}
                inputMode="decimal"
                onChange={(e) => setValor(e.target.value)}
                style={estiloInput}
              />
            </Campo>
          </div>
        </div>
      )}
      {corregir && valor.trim() !== "" && !previa.valido && (
        <p style={{ margin: "0 0 0.4rem", fontSize: "0.82rem", color: colores.error }}>
          {previa.error}
        </p>
      )}
      <Campo etiqueta="Motivo (obligatorio)">
        <input
          value={motivo}
          onChange={(e) => setMotivo(e.target.value)}
          style={estiloInput}
        />
      </Campo>
      <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.3rem" }}>
        <Boton
          disabled={!listo}
          onClick={() =>
            corregir
              ? onCorregir(tipo, valor.trim().replace(",", "."), clase, motivo.trim())
              : onRevertir(motivo.trim())
          }
        >
          {corregir ? "Corregir el ajuste" : "Revertir el ajuste"}
        </Boton>
        <Boton variante="secundario" onClick={onCancelar}>
          Volver
        </Boton>
      </div>
    </div>
  );
}

interface Fila {
  fecha: string;
  clave: string;
  movimiento: string;
  medio: string;
  importe: string;
  usuario: string;
  detalle: string;
  color: string;
  anulado?: boolean;
}

function ListaMovimientos({
  orden,
  medios,
  usuarios,
}: {
  orden: Orden;
  medios: MedioPago[];
  usuarios: Usuario[];
}) {
  const filas: Fila[] = [];
  for (const pago of orden.pagos) {
    filas.push({
      fecha: pago.fecha,
      clave: pago.id,
      movimiento: `Pago ${pago.tipo_pago} · ${pago.id}`,
      medio: nombreDeMedio(medios, pago.metodo),
      importe: importe(pago.monto),
      usuario: nombreDeUsuario(usuarios, pago.usuario_id),
      // UX-08: el recargo se cobró aparte; al saldo va el importe.
      detalle: [
        Number(pago.recargo_importe ?? 0) > 0
          ? `Recargo ${pago.recargo_porcentaje}%: ${importe(
              pago.recargo_importe ?? "0",
            )} · total cobrado ${importe(pago.total_cobrado ?? pago.monto)}`
          : "",
        pago.referencia ?? "",
      ]
        .filter(Boolean)
        .join(" · "),
      color: pago.tipo_pago === "ANTICIPO" ? colores.alerta : colores.ok,
      anulado: !pago.vigente,
    });
    if (pago.anulacion) {
      filas.push({
        fecha: pago.anulacion.fecha,
        clave: `${pago.id}-anulacion`,
        movimiento: `Anulación de ${pago.id}`,
        medio: "—",
        importe: `−${importe(pago.monto)}`,
        usuario: nombreDeUsuario(usuarios, pago.anulacion.usuario_id),
        detalle: pago.anulacion.motivo,
        color: colores.texto,
      });
    }
  }
  for (const devolucion of orden.devoluciones_dinero) {
    filas.push({
      fecha: devolucion.fecha,
      clave: devolucion.id,
      movimiento: `Devolución desde ${devolucion.pago_id}`,
      medio: nombreDeMedio(medios, devolucion.medio),
      importe: `−${importe(devolucion.monto)}`,
      usuario: nombreDeUsuario(usuarios, devolucion.usuario_id),
      // DEC-UX-14: el recargo reintegrado junto con el importe.
      detalle: [
        Number(devolucion.recargo_importe ?? 0) > 0
          ? `Recargo devuelto ${importe(devolucion.recargo_importe ?? "0")} · total reintegrado ${importe(devolucion.total_reintegrado ?? devolucion.monto)}`
          : "",
        devolucion.motivo,
        devolucion.referencia,
      ]
        .filter(Boolean)
        .join(" · "),
      color: colores.error,
    });
  }
  filas.sort((a, b) => a.fecha.localeCompare(b.fecha));

  return (
    <div style={{ marginTop: "1rem" }}>
      <h4
        style={{
          margin: "0 0 0.5rem",
          fontSize: "0.8rem",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          color: colores.suave,
        }}
      >
        Movimientos
      </h4>
      {filas.length === 0 ? (
        <p style={{ margin: 0, color: colores.suave, fontSize: "0.85rem" }}>
          Todavía no se registró ningún pago.
        </p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: "0.82rem",
            }}
          >
            <thead>
              <tr style={{ textAlign: "left", color: colores.suave }}>
                <th style={{ padding: "0.2rem 0.3rem 0.2rem 0" }}>Fecha</th>
                <th>Movimiento</th>
                <th>Medio</th>
                <th style={{ textAlign: "right", paddingRight: "0.75rem" }}>
                  Importe
                </th>
                <th>Usuario</th>
                <th>Detalle</th>
              </tr>
            </thead>
            <tbody>
              {filas.map((fila) => (
                <tr
                  key={fila.clave}
                  style={{ borderTop: `1px solid ${colores.borde}` }}
                >
                  <td style={{ padding: "0.3rem 0.3rem 0.3rem 0", whiteSpace: "nowrap" }}>
                    {fechaCorta(fila.fecha)}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <Etiqueta color={fila.color}>{fila.movimiento}</Etiqueta>
                    {fila.anulado && (
                      <>
                        {" "}
                        <Etiqueta color={colores.texto}>ANULADO</Etiqueta>
                      </>
                    )}
                  </td>
                  <td>{fila.medio}</td>
                  <td
                    style={{
                      textAlign: "right",
                      paddingRight: "0.75rem",
                      whiteSpace: "nowrap",
                      fontWeight: 600,
                      textDecoration: fila.anulado ? "line-through" : "none",
                    }}
                  >
                    {fila.importe}
                  </td>
                  <td>{fila.usuario}</td>
                  <td style={{ color: colores.suave }}>{fila.detalle}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/**
 * El formulario de UNA acción, con su título. `UbicacionAccion` lo oculta
 * si el usuario no puede ejecutarla y lo lleva a «Próximo paso» o a «Otras
 * acciones» cuando corresponde.
 */
export function Seccion({
  titulo,
  accion,
  children,
}: {
  titulo: string;
  accion: Accion;
  actor?: Usuario | null;
  children: ReactNode;
}) {
  return (
    <UbicacionAccion accion={accion}>
      <div
        style={{
          marginTop: "1rem",
          paddingTop: "0.9rem",
          borderTop: `1px solid ${colores.borde}`,
        }}
      >
        <TituloAccion>{titulo}</TituloAccion>
        {children}
      </div>
    </UbicacionAccion>
  );
}

function SelectorMedio({
  medios,
  valor,
  onCambiar,
  deshabilitado,
  paraDevolucion = false,
}: {
  medios: MedioPago[];
  valor: string;
  onCambiar: (medio: string) => void;
  deshabilitado: boolean;
  paraDevolucion?: boolean;
}) {
  const opciones = medios.filter(
    (medio) => medio.activo && (!paraDevolucion || medio.admite_devolucion),
  );
  return (
    <select
      value={valor}
      disabled={deshabilitado}
      onChange={(evento) => onCambiar(evento.target.value)}
      style={estiloInput}
    >
      {opciones.map((medio) => (
        <option key={medio.id} value={medio.id}>
          {medio.nombre}
        </option>
      ))}
    </select>
  );
}

function FormularioCobro({
  accion,
  orden,
  actor,
  medios,
  ocupado,
  onPagar,
}: Props & { accion: Accion }) {
  const saldo = Number(orden.resumen.saldo);
  const [monto, setMonto] = useState(saldo > 0 ? orden.resumen.saldo : "");
  const [metodo, setMetodo] = useState(
    medios.find((medio) => medio.activo)?.id ?? "",
  );
  const [referencia, setReferencia] = useState("");
  const [operacion] = useState(nuevaOperacion);
  const deshabilitado = !habilitada(accion, actor) || ocupado;
  // UX-08: el recargo del medio elegido, como lo calcula el backend. Al
  // saldo se imputa el importe; el recargo se cobra aparte.
  const porcentaje =
    medios.find((medio) => medio.id === metodo)?.recargo_porcentaje ?? "0";
  const conRecargo = Number(porcentaje) > 0 ? recargoDe(monto, porcentaje) : null;

  return (
    <Seccion titulo={accion.etiqueta} accion={accion} actor={actor}>
      {saldo <= 0 && (
        <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
          Seña antes de definir los trabajos: si después no se realizan, se
          devuelve.
        </p>
      )}
      <Campo
        etiqueta={
          saldo > 0
            ? `Importe (hasta ${importe(orden.resumen.saldo)})`
            : "Importe"
        }
      >
        <input
          value={monto}
          inputMode="decimal"
          disabled={deshabilitado}
          onChange={(evento) => setMonto(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Medio de pago">
        <SelectorMedio
          medios={medios}
          valor={metodo}
          onCambiar={setMetodo}
          deshabilitado={deshabilitado}
        />
      </Campo>
      {conRecargo && (
        <div
          role="status"
          style={{
            margin: "0 0 0.6rem",
            padding: "0.5rem 0.7rem",
            border: `1px solid ${colores.borde}`,
            borderRadius: 6,
            fontSize: "0.85rem",
          }}
        >
          <div>Importe (se imputa al saldo): {importe(monto)}</div>
          <div>
            Recargo {porcentaje}%: {importe(String(conRecargo.recargo))}
          </div>
          <div>
            <strong>Total a cobrar: {importe(String(conRecargo.total))}</strong>
          </div>
        </div>
      )}
      <Campo etiqueta="Referencia (opcional)">
        <input
          value={referencia}
          disabled={deshabilitado}
          onChange={(evento) => setReferencia(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Boton
        disabled={deshabilitado || !monto.trim() || !metodo}
        onClick={() =>
          onPagar(monto.trim(), metodo, referencia.trim() || null, operacion)
        }
      >
        {accion.etiqueta}
      </Boton>
    </Seccion>
  );
}

function FormularioDevolucionDinero({
  accion,
  orden,
  actor,
  medios,
  ocupado,
  onDevolver,
}: Props & { accion: Accion }) {
  const credito = Number(orden.resumen.credito_a_favor);
  const pagos = orden.pagos.filter(
    (pago) => pago.vigente && Number(pago.devolvible) > 0,
  );
  const [pagoId, setPagoId] = useState(pagos[0]?.id ?? "");
  const pago = pagos.find((candidato) => candidato.id === pagoId);
  const sugerido = pago
    ? String(Math.min(credito, Number(pago.devolvible)))
    : "";
  const [monto, setMonto] = useState(sugerido);
  const [medio, setMedio] = useState(
    medios.find((m) => m.activo && m.admite_devolucion)?.id ?? "",
  );
  const [motivo, setMotivo] = useState("");
  const [referencia, setReferencia] = useState("");
  const [confirmando, setConfirmando] = useState(false);
  const [operacion] = useState(nuevaOperacion);
  const deshabilitado = !habilitada(accion, actor) || ocupado;

  useEffect(() => setMonto(sugerido), [sugerido]);
  useEffect(
    () => setConfirmando(false),
    [pagoId, monto, medio, motivo, referencia],
  );
  // DEC-UX-14: con el importe se reintegra la parte proporcional del
  // recargo cobrado en ese pago (como lo calcula el backend).
  const recargo = pago
    ? recargoADevolver({
        montoPago: pago.monto,
        recargoPago: pago.recargo_importe ?? "0",
        devueltoAntes: pago.devuelto,
        recargoDevueltoAntes: pago.recargo_devuelto ?? "0",
        monto: monto.trim(),
      })
    : 0;
  const totalReintegro = String(
    Math.round((Number(monto || "0") + recargo) * 100) / 100,
  );

  return (
    <Seccion titulo={accion.etiqueta} accion={accion} actor={actor}>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Registra dinero efectivamente devuelto. No modifica el pago
        original: queda vinculado a él.
      </p>
      <Campo etiqueta="Pago desde el que se devuelve">
        <select
          value={pagoId}
          disabled={deshabilitado}
          onChange={(evento) => setPagoId(evento.target.value)}
          style={estiloInput}
        >
          {pagos.map((candidato) => (
            <option key={candidato.id} value={candidato.id}>
              {candidato.id} · {importe(candidato.monto)} ·{" "}
              {nombreDeMedio(medios, candidato.metodo)} · disponible{" "}
              {importe(candidato.devolvible)}
            </option>
          ))}
        </select>
      </Campo>
      <Campo etiqueta={`Importe (crédito pendiente ${importe(orden.resumen.credito_a_favor)})`}>
        <input
          value={monto}
          inputMode="decimal"
          disabled={deshabilitado}
          onChange={(evento) => setMonto(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      {recargo > 0 && (
        <div
          role="status"
          style={{
            margin: "0 0 0.6rem",
            padding: "0.5rem 0.7rem",
            border: `1px solid ${colores.borde}`,
            borderRadius: 6,
            fontSize: "0.85rem",
          }}
        >
          <div>Importe (se imputa al saldo): {importe(monto)}</div>
          <div>Recargo cobrado que se devuelve: {importe(String(recargo))}</div>
          <div>
            <strong>Total a reintegrar: {importe(totalReintegro)}</strong>
          </div>
        </div>
      )}
      <Campo etiqueta="Medio de devolución">
        <SelectorMedio
          medios={medios}
          valor={medio}
          onCambiar={setMedio}
          deshabilitado={deshabilitado}
          paraDevolucion
        />
      </Campo>
      <Campo etiqueta="Motivo (obligatorio)">
        <input
          value={motivo}
          disabled={deshabilitado}
          onChange={(evento) => setMotivo(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Referencia de la operación (opcional)">
        <input
          value={referencia}
          disabled={deshabilitado}
          onChange={(evento) => setReferencia(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      {!confirmando ? (
        <Boton
          disabled={
            deshabilitado || !pagoId || !monto.trim() || !medio || !motivo.trim()
          }
          onClick={() => setConfirmando(true)}
        >
          Registrar devolución
        </Boton>
      ) : (
        <Confirmacion
          texto={`¿Confirmás que se devolvieron ${importe(totalReintegro)} al cliente desde ${pagoId}?`}
          ocupado={ocupado}
          onVolver={() => setConfirmando(false)}
          onConfirmar={() =>
            onDevolver({
              pago_id: pagoId,
              monto: monto.trim(),
              medio,
              motivo: motivo.trim(),
              referencia: referencia.trim() || null,
              operacion_id: operacion,
            })
          }
        />
      )}
    </Seccion>
  );
}

function FormularioAnulacion({
  acciones,
  orden,
  actor,
  medios,
  ocupado,
  onAnular,
}: Props & { acciones: Accion[] }) {
  const [pagoId, setPagoId] = useState(acciones[0]?.pago_id ?? "");
  const [motivo, setMotivo] = useState("");
  const [confirmando, setConfirmando] = useState(false);
  const accion = acciones[0];
  const deshabilitado = !habilitada(accion, actor) || ocupado;

  useEffect(() => setConfirmando(false), [pagoId, motivo]);

  const descripcion = (id: string | null) => {
    const pago = orden.pagos.find((candidato) => candidato.id === id);
    return pago
      ? `${pago.id} · ${pago.tipo_pago} · ${importe(pago.monto)} · ${nombreDeMedio(medios, pago.metodo)}`
      : (id ?? "");
  };

  return (
    <Seccion titulo="Anular un pago registrado por error" accion={accion} actor={actor}>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Corrige un registro equivocado: el pago queda en el historial como
        anulado y deja de contar como pagado. No es una devolución de dinero.
      </p>
      <Campo etiqueta="Pago">
        <select
          value={pagoId}
          disabled={deshabilitado}
          onChange={(evento) => setPagoId(evento.target.value)}
          style={estiloInput}
        >
          {acciones.map((candidata) => (
            <option key={candidata.pago_id} value={candidata.pago_id ?? ""}>
              {descripcion(candidata.pago_id)}
            </option>
          ))}
        </select>
      </Campo>
      <Campo etiqueta="Motivo (obligatorio)">
        <input
          value={motivo}
          disabled={deshabilitado}
          onChange={(evento) => setMotivo(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      {!confirmando ? (
        <Boton
          variante="secundario"
          disabled={deshabilitado || !pagoId || !motivo.trim()}
          onClick={() => setConfirmando(true)}
        >
          Anular pago
        </Boton>
      ) : (
        <Confirmacion
          texto={`¿Confirmás la anulación de ${descripcion(pagoId)}? No se puede deshacer.`}
          ocupado={ocupado}
          onVolver={() => setConfirmando(false)}
          onConfirmar={() => onAnular(pagoId, motivo.trim())}
        />
      )}
    </Seccion>
  );
}

export function Confirmacion({
  texto,
  ocupado,
  onConfirmar,
  onVolver,
}: {
  texto: string;
  ocupado: boolean;
  onConfirmar: () => void;
  onVolver: () => void;
}) {
  return (
    <div
      role="alertdialog"
      aria-label={texto}
      style={{
        padding: "0.6rem 0.8rem",
        borderRadius: 6,
        border: `1px solid ${colores.alerta}`,
        background: "#fff8e6",
        fontSize: "0.85rem",
      }}
    >
      <p style={{ margin: "0 0 0.5rem" }}>
        <strong>{texto}</strong>
      </p>
      <div style={{ display: "flex", gap: "0.5rem" }}>
        <Boton disabled={ocupado} onClick={onConfirmar}>
          Confirmar
        </Boton>
        <Boton variante="secundario" onClick={onVolver}>
          Volver
        </Boton>
      </div>
    </div>
  );
}
