/**
 * Reparación RT (etapa 1): filtros en la URL, rótulos y estados de la copia
 * (funciones puras). Se ejecuta con `npm test`.
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import type {
  CoincidenciaSugerida,
  EstadoCopiaRt,
  ProductoRtResumen,
  SincronizacionProductosRt,
} from "../src/api/productosRt.ts";
import {
  FILTROS_RT_INICIALES,
  alternarSede,
  conFiltro,
  consultaDeFiltros,
  etiquetaEquipo,
  filtrosActivos,
  filtrosDeConsulta,
  hace,
  imeiAbreviado,
  nivelCopia,
  nombreSede,
  normalizarConsultaRt,
  parametrosApi,
  resumenCoincidencias,
  resumenSincronizacion,
  textoAviso,
  textoCoincidencia,
  textoCriterios,
  totalPaginas,
} from "../src/features/reparacion-rt/filtros.ts";
import {
  esCanonico,
  hashDe,
  parsearRuta,
} from "../src/features/ordenes-reparacion/rutas.ts";

function intento(
  datos: Partial<SincronizacionProductosRt> = {},
): SincronizacionProductosRt {
  return {
    id: "SINC-0123456789ab",
    usuario_id: "ADMIN-001",
    origen: "Archivo CSV (producto.csv)",
    filtro: "producto_status = Reparacion",
    iniciada_en: "2026-11-19T12:00:00Z",
    finalizada_en: "2026-11-19T12:00:05Z",
    resultado: "EXITOSA",
    mensaje: null,
    contadores: { en_reparacion: 14 },
    avisos: [],
    ...datos,
  };
}

function copia(datos: Partial<EstadoCopiaRt> = {}): EstadoCopiaRt {
  const exitosa = intento();
  return {
    habilitado: true,
    sincronizable: true,
    origen: "Archivo CSV (producto.csv)",
    filtro: "producto_status = Reparacion",
    datos_del: exitosa.finalizada_en,
    ultima: exitosa,
    ultima_exitosa: exitosa,
    desactualizada: false,
    antiguedad_aviso_horas: 24,
    ...datos,
  };
}

function coincidencia(
  datos: Partial<CoincidenciaSugerida> = {},
): CoincidenciaSugerida {
  return {
    orden_id: "OR-000041",
    criterios: ["REFERENCIA_RT"],
    origen: "RT_INTERNO",
    estado_workflow: "EN_COLA",
    cerrada: false,
    creada_en: "2026-11-18T10:00:00Z",
    ...datos,
  };
}

function producto(datos: Partial<ProductoRtResumen> = {}): ProductoRtResumen {
  return {
    producto_id: "900001",
    imei: "359999000000014",
    imei_valido: true,
    imei_repetido: false,
    modelo: "iPhone 13 Pro",
    capacidad: "256 GB",
    color: "Graphite",
    descripcion_tipo: "iPhone 13 Pro 256gb graphite",
    sede: "Centro",
    estado_gestion_rt: "Reparacion",
    en_reparacion: true,
    en_reparacion_desde: "2026-11-19T12:00:00Z",
    salio_de_reparacion_en: null,
    eliminado_en_origen: false,
    presente_en_origen: true,
    avisos: [],
    coincidencias_sugeridas: [],
    ...datos,
  };
}

describe("filtros en la URL", () => {
  test("sin filtros la consulta queda vacía", () => {
    assert.equal(consultaDeFiltros(FILTROS_RT_INICIALES), "");
    assert.deepEqual(filtrosDeConsulta(""), FILTROS_RT_INICIALES);
    assert.ok(!filtrosActivos(FILTROS_RT_INICIALES));
  });

  test("ida y vuelta con todos los filtros", () => {
    const filtros = {
      q: "13 pro",
      sedes: ["Centro", "Alippi", ""],
      ordenRma: "CON_SUGERENCIAS" as const,
      incluirFuera: true,
      pagina: 3,
    };
    const consulta = consultaDeFiltros(filtros);
    assert.equal(
      consulta,
      "q=13+pro&sede=Centro&sede=Alippi&sede=&orden_rma=CON_SUGERENCIAS&fuera=1&pagina=3",
    );
    assert.deepEqual(filtrosDeConsulta(consulta), filtros);
    assert.ok(filtrosActivos(filtros));
  });

  test("valores inválidos se descartan y la forma queda canónica", () => {
    assert.deepEqual(
      filtrosDeConsulta("?orden_rma=VINCULADA&pagina=-2&fuera=si&sede=Centro&sede=Centro"),
      { ...FILTROS_RT_INICIALES, sedes: ["Centro"] },
    );
    assert.equal(normalizarConsultaRt("pagina=1&q=%20%20"), "");
    assert.equal(normalizarConsultaRt("fuera=1&q=x"), "q=x&fuera=1");
  });

  test("el pedido al backend", () => {
    const parametros = parametrosApi({
      ...FILTROS_RT_INICIALES,
      q: " 4 5678 ",
      sedes: ["RMA", ""],
      incluirFuera: true,
    });
    assert.equal(
      parametros.toString(),
      "q=4+5678&sede=RMA&sede=&incluir_fuera=true&pagina=1&tamano=50",
    );
  });

  test("cambiar un filtro vuelve a la primera página; las sedes se combinan", () => {
    const en3 = { ...FILTROS_RT_INICIALES, pagina: 3 };
    assert.equal(conFiltro(en3, { q: "x" }).pagina, 1);
    const dos = alternarSede(alternarSede(en3, "Centro"), "RMA");
    assert.deepEqual(dos.sedes, ["Centro", "RMA"]);
    assert.equal(dos.pagina, 1);
    assert.deepEqual(alternarSede(dos, "Centro").sedes, ["RMA"]);
  });

  test("páginas", () => {
    assert.equal(totalPaginas(0), 1);
    assert.equal(totalPaginas(50), 1);
    assert.equal(totalPaginas(51), 2);
    assert.equal(totalPaginas(14, 5), 3);
  });
});

describe("rutas de Reparación RT", () => {
  test("listado, filtros y ficha en el hash", () => {
    assert.equal(hashDe({ pantalla: "reparacion-rt", consulta: "" }), "#/reparacion-rt");
    assert.deepEqual(parsearRuta("#/reparacion-rt"), {
      pantalla: "reparacion-rt",
      consulta: "",
    });
    const ficha = parsearRuta("#/reparacion-rt/900001?sede=Centro");
    assert.deepEqual(ficha, {
      pantalla: "reparacion-rt",
      consulta: "sede=Centro",
      productoId: "900001",
    });
    assert.equal(hashDe(ficha), "#/reparacion-rt/900001?sede=Centro");
    assert.ok(esCanonico("#/reparacion-rt/900001?sede=Centro"));
    assert.ok(!esCanonico("#/reparacion-rt?pagina=1"));
    assert.equal(hashDe(parsearRuta("#/reparacion-rt?pagina=1")), "#/reparacion-rt");
    assert.deepEqual(parsearRuta("#/reparacion-rt/a/b"), { pantalla: "inicio" });
  });

  test("las demás rutas no cambian", () => {
    assert.deepEqual(parsearRuta("#/ordenes/OR-000001?x=1"), {
      pantalla: "orden",
      ordenId: "OR-000001",
    });
    assert.equal(hashDe({ pantalla: "taller" }), "#/taller");
  });
});

describe("rótulos", () => {
  test("equipo e IMEI", () => {
    assert.equal(etiquetaEquipo(producto()), "iPhone 13 Pro 256 GB Graphite");
    assert.equal(
      etiquetaEquipo(producto({ modelo: null, capacidad: null, color: null })),
      "iPhone 13 Pro 256gb graphite",
    );
    assert.equal(
      etiquetaEquipo(
        producto({ modelo: null, capacidad: null, color: null, descripcion_tipo: null }),
      ),
      "Equipo sin TipoProducto en el catálogo",
    );
    assert.equal(imeiAbreviado("359999000000014"), "…0 0014");
    assert.equal(imeiAbreviado(null), "—");
    assert.equal(imeiAbreviado("123"), "123");
    assert.equal(nombreSede(null), "Sin sede");
    assert.equal(nombreSede(""), "Sin sede");
  });

  test("una coincidencia es siempre una pregunta con su criterio", () => {
    assert.equal(
      textoCoincidencia(coincidencia()),
      "¿OR-000041? En cola (sugerida por referencia RT)",
    );
    assert.equal(
      textoCoincidencia(
        coincidencia({ criterios: ["IMEI", "REFERENCIA_RT"], cerrada: true, estado_workflow: "ENTREGADA" }),
      ),
      "¿OR-000041? Entregada, cerrada (sugerida por referencia RT e IMEI)",
    );
    assert.equal(textoCriterios(["IMEI"]), "sugerida por IMEI");
    for (const c of [coincidencia(), coincidencia({ criterios: ["IMEI"] })]) {
      const texto = textoCoincidencia(c);
      assert.match(texto, /^¿OR-\d+\?/);
      assert.match(texto, /sugerida por/);
      assert.doesNotMatch(texto, /vinculad|historial|activa/i);
    }
  });

  test("resumen de coincidencias en el listado", () => {
    assert.equal(resumenCoincidencias(producto()), "Sin coincidencias");
    assert.equal(
      resumenCoincidencias(producto({ coincidencias_sugeridas: [coincidencia()] })),
      "¿OR-000041? En cola (sugerida por referencia RT)",
    );
    assert.equal(
      resumenCoincidencias(
        producto({
          coincidencias_sugeridas: [coincidencia(), coincidencia({ orden_id: "OR-000042" })],
        }),
      ),
      "2 coincidencias sugeridas",
    );
  });

  test("avisos y resultado de una actualización", () => {
    assert.match(textoAviso("IMEI_REPETIDO"), /no se usa para sugerir/);
    assert.match(textoAviso("FUERA_DE_REPARACION"), /Reparación/);
    assert.equal(
      resumenSincronizacion({ en_reparacion: 14, nuevos: 2, salieron: 1, ausentes: 0 }),
      "14 en reparación · 2 nuevos · 1 salieron",
    );
  });

  test("antigüedad de los datos", () => {
    const ahora = new Date("2026-11-19T15:00:00Z");
    assert.equal(hace("2026-11-19T14:59:40Z", ahora), "recién");
    assert.equal(hace("2026-11-19T14:30:00Z", ahora), "hace 30 min");
    assert.equal(hace("2026-11-19T12:00:00Z", ahora), "hace 3 h");
    assert.equal(hace("2026-11-16T15:00:00Z", ahora), "hace 3 días");
  });
});

describe("estado de la copia", () => {
  test("cada estado de la pantalla", () => {
    assert.equal(nivelCopia(copia({ habilitado: false })), "no_habilitada");
    assert.equal(nivelCopia(copia()), "al_dia");
    assert.equal(nivelCopia(copia({ desactualizada: true })), "desactualizada");
    const sinDatos = { datos_del: null, ultima: null, ultima_exitosa: null };
    assert.equal(nivelCopia(copia(sinDatos)), "nunca");
    assert.equal(
      nivelCopia(copia({ ...sinDatos, sincronizable: false })),
      "sin_origen",
    );
    const fallida = intento({ resultado: "FALLIDA", mensaje: "No respondió." });
    assert.equal(nivelCopia(copia({ ultima: fallida })), "error_con_copia");
    assert.equal(
      nivelCopia(copia({ ...sinDatos, ultima: fallida })),
      "error_sin_copia",
    );
    // Un error con copia se informa aunque la copia esté vieja.
    assert.equal(
      nivelCopia(copia({ ultima: fallida, desactualizada: true })),
      "error_con_copia",
    );
  });
});
