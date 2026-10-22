/**
 * Selector del catálogo de equipos de Ventas: Modelo → Variante →
 * Capacidad → Color con las combinaciones que existen, carga manual y
 * cómo se muestra un equipo (también los de Órdenes anteriores).
 *
 * Se ejecuta con `npm test` (node --test). Catálogo ficticio con la forma
 * de la respuesta real de `GET /api/catalogs/equipment`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { CatalogoEquipos, Equipo } from "../src/types/api.ts";
import {
  COLOR_GENERICO,
  ETIQUETA_COLOR_GENERICO,
  SELECCION_VACIA,
  VARIANTE_ESTANDAR,
  ajustarSeleccion,
  cantidadDeProductos,
  datosDelEquipo,
  descripcionEquipo,
  elegir,
  equipoElegidoDe,
  equipoElegidoInicial,
  modoEfectivo,
  nombreEquipo,
  opcionesCapacidad,
  opcionesColor,
  opcionesModelo,
  opcionesVariante,
  productoElegido,
} from "../src/features/ordenes-reparacion/catalogoEquipos.ts";

const id = (n: string, v: string, gb: string, c: string) =>
  `apple_usados_iPhone_${n}_${v}_${gb}_${c}`;

const CATALOGO: CatalogoEquipos = {
  estado: {
    habilitado: true,
    sincronizable: true,
    origen: "Google Sheets (hoja raw_TipoProducto)",
    filtro: "subcategoría: IPHONE USADOS",
    ultima: null,
    ultima_exitosa: null,
    vigentes: 6,
    elegibles: 6,
  },
  modelos: [
    {
      marca: "Apple",
      modelo: "iPhone 12",
      variantes: [
        {
          variante: null,
          capacidades: [
            {
              capacidad: "128 GB",
              colores: [
                { color: "Black", generico: false, tipo_producto_id: id("12", "Nada", "128gb", "black") },
                { color: null, generico: true, tipo_producto_id: id("12", "Nada", "128gb", "cualquier_color") },
              ],
            },
          ],
        },
        {
          variante: "Pro",
          capacidades: [
            {
              capacidad: "256 GB",
              colores: [
                { color: "Black", generico: false, tipo_producto_id: id("12", "Pro", "256gb", "black") },
                { color: "Gold", generico: false, tipo_producto_id: id("12", "Pro", "256gb", "gold") },
              ],
            },
          ],
        },
        {
          variante: "Pro Max",
          capacidades: [
            {
              capacidad: "256 GB",
              colores: [
                { color: "Black", generico: false, tipo_producto_id: id("12", "Pro Max", "256gb", "black") },
              ],
            },
          ],
        },
      ],
    },
    {
      marca: "Apple",
      modelo: "iPhone SE 2020",
      variantes: [
        {
          variante: null,
          capacidades: [
            {
              capacidad: "64 GB",
              colores: [
                { color: "Red", generico: false, tipo_producto_id: id("SE 2020", "Nada", "64gb", "red") },
              ],
            },
          ],
        },
      ],
    },
  ],
};

const DOCE = "Apple|iPhone 12";
const SE = "Apple|iPhone SE 2020";

test("cada nivel ofrece solo lo que existe para lo elegido arriba", () => {
  assert.deepEqual(
    opcionesModelo(CATALOGO).map((o) => o.etiqueta),
    ["iPhone 12", "iPhone SE 2020"],
  );
  assert.deepEqual(opcionesVariante(CATALOGO, SELECCION_VACIA), []);
  const doce = { ...SELECCION_VACIA, modelo: DOCE };
  assert.deepEqual(
    opcionesVariante(CATALOGO, doce).map((o) => [o.valor, o.etiqueta]),
    [
      [VARIANTE_ESTANDAR, "Estándar"],
      ["Pro", "Pro"],
      ["Pro Max", "Pro Max"],
    ],
  );
  const pro = { ...doce, variante: "Pro" };
  assert.deepEqual(opcionesCapacidad(CATALOGO, pro).map((o) => o.valor), ["256 GB"]);
  assert.deepEqual(
    opcionesColor(CATALOGO, { ...pro, capacidad: "256 GB" }).map((o) => o.etiqueta),
    ["Black", "Gold"],
  );
});

test("un nivel con una sola opción se elige solo", () => {
  // SE 2020: una variante, una capacidad, un color.
  const se = elegir(CATALOGO, SELECCION_VACIA, "modelo", SE);
  assert.deepEqual(se, {
    modelo: SE,
    variante: VARIANTE_ESTANDAR,
    capacidad: "64 GB",
    color: "Red",
  });
  assert.equal(
    productoElegido(CATALOGO, se)?.tipo_producto_id,
    id("SE 2020", "Nada", "64gb", "red"),
  );
  // Pro Max: una capacidad y un color.
  const proMax = elegir(
    CATALOGO,
    elegir(CATALOGO, SELECCION_VACIA, "modelo", DOCE),
    "variante",
    "Pro Max",
  );
  assert.equal(proMax.capacidad, "256 GB");
  assert.equal(proMax.color, "Black");
});

test("cambiar un nivel conserva lo de abajo solo si sigue existiendo", () => {
  let s = elegir(CATALOGO, SELECCION_VACIA, "modelo", DOCE);
  s = elegir(CATALOGO, s, "variante", "Pro");
  s = elegir(CATALOGO, s, "color", "Gold");
  assert.equal(productoElegido(CATALOGO, s)?.tipo_producto_id, id("12", "Pro", "256gb", "gold"));

  // Pro Max 256 GB existe, pero no en Gold: el color se borra.
  const proMax = elegir(CATALOGO, { ...s, color: "Gold" }, "variante", "Pro Max");
  assert.equal(proMax.capacidad, "256 GB");
  assert.equal(proMax.color, "Black"); // única opción: se elige sola
  const conNegro = elegir(CATALOGO, s, "color", "Black");
  const deNuevo = elegir(CATALOGO, conNegro, "variante", "Pro Max");
  assert.equal(
    productoElegido(CATALOGO, deNuevo)?.tipo_producto_id,
    id("12", "Pro Max", "256gb", "black"),
  );

  // Otro modelo sin esa variante: se borra todo lo de abajo.
  const otro = elegir(CATALOGO, s, "modelo", SE);
  assert.equal(otro.variante, VARIANTE_ESTANDAR);
  assert.equal(productoElegido(CATALOGO, otro)?.modelo, "iPhone SE 2020");

  // Una selección que no existe se limpia.
  assert.deepEqual(
    ajustarSeleccion(CATALOGO, { ...SELECCION_VACIA, modelo: "Apple|iPhone 99" }),
    SELECCION_VACIA,
  );
});

test("el color genérico se ofrece como «Otro / sin especificar»", () => {
  let s = elegir(CATALOGO, SELECCION_VACIA, "modelo", DOCE);
  s = elegir(CATALOGO, s, "variante", VARIANTE_ESTANDAR);
  const colores = opcionesColor(CATALOGO, s);
  assert.deepEqual(colores.at(-1), { valor: COLOR_GENERICO, etiqueta: ETIQUETA_COLOR_GENERICO });
  const generico = productoElegido(CATALOGO, elegir(CATALOGO, s, "color", COLOR_GENERICO));
  assert.equal(generico?.color, null);
  assert.equal(generico?.tipo_producto_id, id("12", "Nada", "128gb", "cualquier_color"));
});

test("al backend va el tp_id elegido, o marca y modelo a mano", () => {
  const inicial = equipoElegidoInicial({ marca: "Apple", modelo: "iPhone 14" });
  // Sin catálogo (todavía no sincronizado o sin conexión): a mano.
  assert.equal(modoEfectivo(null, inicial), "manual");
  assert.deepEqual(datosDelEquipo(null, inicial), { marca: "Apple", modelo: "iPhone 14" });
  const vacio = { ...CATALOGO, modelos: [] };
  assert.equal(modoEfectivo(vacio, inicial), "manual");

  // Con catálogo: hasta elegir los cuatro niveles no hay equipo.
  assert.equal(modoEfectivo(CATALOGO, inicial), "catalogo");
  assert.equal(datosDelEquipo(CATALOGO, inicial), null);
  const elegido = { ...inicial, seleccion: elegir(CATALOGO, SELECCION_VACIA, "modelo", SE) };
  assert.deepEqual(datosDelEquipo(CATALOGO, elegido), {
    tipo_producto_id: id("SE 2020", "Nada", "64gb", "red"),
  });

  // «No está en el catálogo»: a mano, aunque haya catálogo.
  const manual = { ...elegido, modo: "manual" as const, marca: " Samsung ", modelo: "A54 " };
  assert.deepEqual(datosDelEquipo(CATALOGO, manual), { marca: "Samsung", modelo: "A54" });
  assert.equal(datosDelEquipo(CATALOGO, { ...manual, modelo: " " }), null);
});

const DEL_CATALOGO: Equipo = {
  id: "EQP-1",
  marca: "Apple",
  modelo: "iPhone 12",
  falla_reportada: "No carga.",
  imei: null,
  numero_serie: null,
  tipo_producto_id: id("12", "Pro Max", "256gb", "deep_purple"),
  variante: "Pro Max",
  capacidad: "256 GB",
  color: "Deep Purple",
};

test("corregir: se conserva el producto que tenía si no se elige otro", () => {
  const elegido = equipoElegidoDe(DEL_CATALOGO);
  assert.equal(elegido.modo, "catalogo");
  // Aunque ya no esté en el catálogo, o no haya catálogo.
  for (const catalogo of [CATALOGO, null]) {
    assert.equal(modoEfectivo(catalogo, elegido), "catalogo");
    assert.deepEqual(datosDelEquipo(catalogo, elegido), {
      tipo_producto_id: DEL_CATALOGO.tipo_producto_id,
    });
  }
  // Empezar a elegir otro: ya no vale el anterior hasta completarlo.
  const otro = { ...elegido, seleccion: { ...SELECCION_VACIA, modelo: DOCE } };
  assert.equal(datosDelEquipo(CATALOGO, otro), null);
  // A mano: marca y modelo que tenía.
  assert.deepEqual(datosDelEquipo(CATALOGO, { ...elegido, modo: "manual" }), {
    marca: "Apple",
    modelo: "iPhone 12",
  });
  // Una Orden cargada a mano se corrige a mano.
  const manual = equipoElegidoDe({ ...DEL_CATALOGO, tipo_producto_id: null });
  assert.equal(manual.modo, "manual");
});

test("cómo se muestra un equipo (y uno de una Orden anterior)", () => {
  assert.equal(nombreEquipo(DEL_CATALOGO), "Apple iPhone 12 Pro Max");
  assert.equal(descripcionEquipo(DEL_CATALOGO), "Apple iPhone 12 Pro Max · 256 GB · Deep Purple");
  const estandarSinColor = { ...DEL_CATALOGO, variante: null, color: null };
  assert.equal(descripcionEquipo(estandarSinColor), "Apple iPhone 12 · 256 GB");
  // Orden anterior al catálogo: sin variante, capacidad ni color.
  const anterior = { marca: "Motorola", modelo: "Moto G84" };
  assert.equal(nombreEquipo(anterior), "Motorola Moto G84");
  assert.equal(descripcionEquipo(anterior), "Motorola Moto G84");
  assert.equal(cantidadDeProductos(CATALOGO), 6);
});
