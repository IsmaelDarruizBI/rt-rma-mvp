/**
 * Ingreso (ajustes funcionales, bloque 3): trabajo solicitado, verificación
 * de funcionalidades, «Crear y generar el comprobante» e IMEI no disponible.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { DocumentoEmitido } from "../src/types/api.ts";
import {
  CANAL_PREDETERMINADO,
  TIPO_DEL_COMPROBANTE,
  comprobanteDelAlta,
  comprobanteGenerado,
  datosAgregadosDelIngreso,
  esCoincidenciaDeImei,
  explicacionDelAlta,
  faltantesDelIngreso,
  identificacionDelEquipo,
  imeiRealCompleto,
  referenciaParaCheckin,
  respuestaDe,
  textoVerificacion,
  verificacionDe,
} from "../src/features/ordenes-reparacion/ingresoAjustes.ts";

test("DEC-AJ-05 y 07: lo que el alta agrega a la recepción", () => {
  assert.deepEqual(
    datosAgregadosDelIngreso({
      trabajoSolicitado: "  Cambiar la batería ",
      verificacion: "NO",
      observacionesVerificacion: " No enciende ",
      imeiNoDisponible: true,
    }),
    {
      trabajo_solicitado: "Cambiar la batería",
      funcionalidades_verificadas: false,
      observaciones_verificacion: "No enciende",
      imei_no_disponible: true,
    },
  );
  assert.deepEqual(
    datosAgregadosDelIngreso({
      trabajoSolicitado: "  ",
      verificacion: "SI",
      observacionesVerificacion: "",
      imeiNoDisponible: false,
    }),
    {
      trabajo_solicitado: null,
      funcionalidades_verificadas: true,
      observaciones_verificacion: null,
      imei_no_disponible: false,
    },
  );
});

test("DEC-AJ-07: la verificación es obligatoria para crear", () => {
  assert.deepEqual(
    faltantesDelIngreso({ observaciones: "No carga", verificacion: "" }),
    ["responder si se pudieron verificar las funcionalidades"],
  );
  assert.deepEqual(
    faltantesDelIngreso({ observaciones: "No carga", verificacion: "NO" }),
    [],
  );
  assert.equal(
    faltantesDelIngreso({ observaciones: " ", verificacion: "SI" }).length,
    1,
  );
});

test("DEC-AJ-07: Sí o No, y sin responder", () => {
  assert.equal(verificacionDe("SI"), true);
  assert.equal(verificacionDe("NO"), false);
  assert.equal(verificacionDe(""), null);
  assert.equal(respuestaDe(true), "SI");
  assert.equal(respuestaDe(false), "NO");
  assert.equal(respuestaDe(null), "");
  assert.equal(textoVerificacion(null), null);
  assert.equal(
    textoVerificacion({ funcionalidades_verificadas: null }),
    null,
  );
  assert.equal(
    textoVerificacion({
      funcionalidades_verificadas: false,
      observaciones_verificacion: "La pantalla no responde",
    }),
    "No. La pantalla no responde",
  );
  assert.equal(textoVerificacion({ funcionalidades_verificadas: true }), "Sí");
});

test("DEC-AJ-07: en el check-in de entrega es solo una referencia", () => {
  const texto = referenciaParaCheckin({ funcionalidades_verificadas: false });
  assert.match(texto, /Al ingresar/);
  assert.match(texto, /No/);
  assert.match(texto, /no reemplaza este check-in/);
  assert.match(referenciaParaCheckin(undefined), /no se registró/);
});

test("DEC-AJ-08: con trabajo, el de ingreso; sin trabajo, el de recepción", () => {
  assert.equal(comprobanteDelAlta("TR-001"), "INGRESO");
  assert.equal(comprobanteDelAlta(null), "RECEPCION");
  assert.equal(TIPO_DEL_COMPROBANTE.INGRESO, "COMPROBANTE_INGRESO");
  assert.equal(TIPO_DEL_COMPROBANTE.RECEPCION, "COMPROBANTE_RECEPCION");
  assert.equal(CANAL_PREDETERMINADO, "PRESENCIAL");
  assert.match(explicacionDelAlta("INGRESO"), /canal elegido/);
  assert.match(explicacionDelAlta("RECEPCION"), /revisión técnica/);
  assert.match(explicacionDelAlta("RECEPCION"), /quedó en el local/);
});

test("DEC-AJ-08: el visor abre el comprobante recién generado", () => {
  const documento = (id: string, tipo: string) =>
    ({ id, tipo }) as unknown as DocumentoEmitido;
  const emitidos = [
    documento("OR-1-REC-01", "COMPROBANTE_RECEPCION"),
    documento("OR-1-ING-01", "COMPROBANTE_INGRESO"),
  ];
  assert.equal(
    comprobanteGenerado(emitidos, "COMPROBANTE_INGRESO")?.id,
    "OR-1-ING-01",
  );
  assert.equal(
    comprobanteGenerado(emitidos, "COMPROBANTE_RECEPCION")?.id,
    "OR-1-REC-01",
  );
  // El que ya estaba no se vuelve a abrir.
  assert.equal(
    comprobanteGenerado(emitidos, "COMPROBANTE_INGRESO", "OR-1-ING-01"),
    null,
  );
  assert.equal(comprobanteGenerado([], "COMPROBANTE_INGRESO"), null);
});

test("DEC-AJ-06: sin IMEI se identifica con el EQP, que no es un IMEI", () => {
  const sinImei = { id: "EQP-0123456789ab", imei: null };
  const provisorio = identificacionDelEquipo(sinImei, true);
  assert.equal(provisorio.provisorio, true);
  assert.match(provisorio.imei, /No disponible/);
  assert.match(provisorio.imei, /EQP-0123456789ab/);
  assert.match(provisorio.imei, /no es un IMEI/);
  assert.equal(identificacionDelEquipo(sinImei, false).provisorio, false);
  assert.deepEqual(
    identificacionDelEquipo({ id: "EQP-1", imei: "356789012345678" }, true),
    { imei: "356789012345678", provisorio: false },
  );
});

test("DEC-AJ-06: el IMEI real y el aviso de otro equipo", () => {
  assert.equal(imeiRealCompleto(" "), false);
  assert.equal(imeiRealCompleto("356789012345678"), true);
  assert.equal(esCoincidenciaDeImei("CONFIRMACION_REQUERIDA"), true);
  assert.equal(esCoincidenciaDeImei("PRECONDICION_INVALIDA"), false);
});
