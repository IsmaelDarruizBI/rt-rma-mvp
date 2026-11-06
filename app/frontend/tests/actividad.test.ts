/**
 * Actividad de red: barra de carga y lecturas iguales simultáneas.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { ActividadDeRed, LecturasEnCurso } from "../src/api/actividad.ts";

function diferida<T>() {
  let resolver!: (valor: T) => void;
  let rechazar!: (motivo: unknown) => void;
  const promesa = new Promise<T>((ok, mal) => {
    resolver = ok;
    rechazar = mal;
  });
  return { promesa, resolver, rechazar };
}

test("la actividad dura mientras haya algún pedido en curso", async () => {
  const actividad = new ActividadDeRed();
  const uno = diferida<number>();
  const dos = diferida<number>();
  const primero = actividad.seguir(() => uno.promesa);
  const segundo = actividad.seguir(() => dos.promesa);
  assert.equal(actividad.activa(), true);
  uno.resolver(1);
  await primero;
  assert.equal(actividad.activa(), true);
  dos.resolver(2);
  await segundo;
  assert.equal(actividad.activa(), false);
});

test("un pedido que falla también termina la actividad", async () => {
  const actividad = new ActividadDeRed();
  await assert.rejects(
    actividad.seguir(() => Promise.reject(new Error("sin red"))),
  );
  assert.equal(actividad.activa(), false);
});

test("avisa solo cuando cambia si hay actividad, y deja de avisar", async () => {
  const actividad = new ActividadDeRed();
  let avisos = 0;
  const cancelar = actividad.suscribir(() => (avisos += 1));
  const uno = diferida<void>();
  const dos = diferida<void>();
  const pedidos = [
    actividad.seguir(() => uno.promesa),
    actividad.seguir(() => dos.promesa),
  ];
  uno.resolver();
  dos.resolver();
  await Promise.all(pedidos);
  assert.equal(avisos, 2);
  cancelar();
  await actividad.seguir(() => Promise.resolve());
  assert.equal(avisos, 2);
});

test("dos lecturas iguales simultáneas hacen un solo pedido", async () => {
  const lecturas = new LecturasEnCurso();
  const respuesta = diferida<string>();
  let pedidos = 0;
  const leer = () => {
    pedidos += 1;
    return respuesta.promesa;
  };
  const una = lecturas.compartir("/api/orders", leer);
  const otra = lecturas.compartir("/api/orders", leer);
  respuesta.resolver("ok");
  assert.deepEqual(await Promise.all([una, otra]), ["ok", "ok"]);
  assert.equal(pedidos, 1);
});

test("lecturas distintas no se comparten", async () => {
  const lecturas = new LecturasEnCurso();
  let pedidos = 0;
  const leer = async () => (pedidos += 1);
  await Promise.all([
    lecturas.compartir("/api/orders", leer),
    lecturas.compartir("/api/inventory", leer),
  ]);
  assert.equal(pedidos, 2);
});

test("una lectura terminada no se reutiliza: no es un caché", async () => {
  const lecturas = new LecturasEnCurso();
  let pedidos = 0;
  const leer = async () => (pedidos += 1);
  assert.equal(await lecturas.compartir("/api/orders", leer), 1);
  assert.equal(await lecturas.compartir("/api/orders", leer), 2);
});

test("una lectura que falla se puede volver a pedir", async () => {
  const lecturas = new LecturasEnCurso();
  await assert.rejects(
    lecturas.compartir("/api/orders", () =>
      Promise.reject(new Error("sin red")),
    ),
  );
  assert.equal(
    await lecturas.compartir("/api/orders", async () => "ok"),
    "ok",
  );
});
