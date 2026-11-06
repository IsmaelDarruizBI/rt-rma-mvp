/**
 * E6 (B3): claves de idempotencia de los envíos. Solo funciones sin DOM.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ClavesDeEnvio,
  OperacionesEstables,
  conClave,
  llevaClave,
} from "../src/api/idempotencia.ts";

function contador(): () => string {
  let n = 0;
  return () => `k${++n}`;
}

/** Un envío que responde con esos estados, en orden (200: éxito). */
function enviosCon(...estados: number[]) {
  const recibidas: (string | undefined)[] = [];
  const enviar = async (clave: string | undefined) => {
    recibidas.push(clave);
    const estado = estados.shift() ?? 200;
    if (estado !== 200) throw Object.assign(new Error("falla"), { status: estado });
    return "ok";
  };
  return { enviar, recibidas };
}

const PAGO = "/api/orders/OR-000001/payments";
const CUERPO = JSON.stringify({ usuario_id: "RECEP-001", monto: "100" });

test("solo las operaciones que crean registros llevan clave", () => {
  for (const ruta of [
    "/api/orders",
    "/api/orders/rt-interno",
    "/api/orders/OR-000001/warranty-rma",
    "/api/orders/OR-000001/details",
    "/api/orders/OR-000001/review/details",
    "/api/orders/OR-000001/reception/notes",
    "/api/orders/OR-000001/notify",
    PAGO,
    "/api/orders/OR-000001/refunds",
    "/api/orders/OR-000001/photos?usuario_id=RECEP-001",
    "/api/inventory/INS-001/receipts",
    "/api/inventory/INS-001/adjustments",
    "/api/catalogs/equipment/sync?usuario_id=ADMIN-001",
  ]) {
    assert.equal(llevaClave(ruta), true, ruta);
  }
  for (const ruta of [
    "/api/orders/OR-000001/take",
    "/api/orders/OR-000001/details/DET-001/start",
    "/api/orders/OR-000001/payments/PAG-1/void",
    "/api/orders/OR-000001/deliver",
    "/api/inventory/revalidate-orders",
  ]) {
    assert.equal(llevaClave(ruta), false, ruta);
  }
});

test("un reintento incierto reutiliza la clave", async () => {
  const claves = new ClavesDeEnvio(contador());
  for (const estado of [0, 500, 503]) {
    const { enviar, recibidas } = enviosCon(estado, 200);
    await assert.rejects(conClave(claves, PAGO, CUERPO, enviar));
    await conClave(claves, PAGO, CUERPO, enviar);
    assert.equal(recibidas.length, 2);
    assert.equal(recibidas[0], recibidas[1], `estado ${estado}`);
  }
});

test("después de una respuesta definitiva, la misma operación es otra", async () => {
  const claves = new ClavesDeEnvio(contador());
  for (const estado of [200, 409, 422]) {
    const { enviar, recibidas } = enviosCon(estado, 200);
    if (estado === 200) await conClave(claves, PAGO, CUERPO, enviar);
    else await assert.rejects(conClave(claves, PAGO, CUERPO, enviar));
    await conClave(claves, PAGO, CUERPO, enviar);
    assert.notEqual(recibidas[0], recibidas[1], `estado ${estado}`);
  }
});

test("otra ruta u otro cuerpo es otra clave; sin clave, ninguna", async () => {
  const claves = new ClavesDeEnvio(contador());
  const a = claves.clave(PAGO, CUERPO);
  assert.equal(claves.clave(PAGO, CUERPO), a);
  assert.notEqual(claves.clave(PAGO, JSON.stringify({ monto: "200" })), a);
  assert.notEqual(claves.clave("/api/orders/OR-000002/payments", CUERPO), a);
  const { enviar, recibidas } = enviosCon(200);
  await conClave(claves, "/api/orders/OR-000001/take", "{}", enviar);
  assert.deepEqual(recibidas, [undefined]);
});

test("fotos: el mismo archivo conserva la clave; otro archivo, otra", async () => {
  const claves = new ClavesDeEnvio(contador());
  const ruta = "/api/orders/OR-000001/photos?usuario_id=RECEP-001";
  const foto = new Blob([new Uint8Array([1, 2, 3])], { type: "image/jpeg" });
  const otra = new Blob([new Uint8Array([1, 2, 3])], { type: "image/jpeg" });
  const { enviar, recibidas } = enviosCon(0, 200, 200);
  await assert.rejects(conClave(claves, ruta, foto, enviar));
  await conClave(claves, ruta, foto, enviar);
  await conClave(claves, ruta, otra, enviar);
  assert.equal(recibidas[0], recibidas[1]);
  assert.notEqual(recibidas[1], recibidas[2]);
});

test("inventario: el operacion_id es el mismo hasta registrarse", () => {
  const operaciones = new OperacionesEstables(contador());
  const datos = { valor: "3", motivo: "Compra", referencia: null };
  const primera = operaciones.id("ingreso:INS-001", datos);
  assert.equal(operaciones.id("ingreso:INS-001", { ...datos }), primera);
  assert.notEqual(operaciones.id("ingreso:INS-002", datos), primera);
  assert.notEqual(
    operaciones.id("ingreso:INS-001", { ...datos, valor: "4" }),
    primera,
  );
  operaciones.olvidar("ingreso:INS-001", datos);
  assert.notEqual(operaciones.id("ingreso:INS-001", datos), primera);
});
