/**
 * Requisitos de insumo por Tipo y pieza elegida de cada trabajo (DEC-AJ-14,
 * D-14.4): marcas, qué acción se ofrece, cuándo se exige motivo, qué se
 * envía y el editor de «Insumos necesarios» del Tipo. El backend valida y
 * aplica las mismas reglas.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { llevaClave } from "../src/api/idempotencia.ts";
import {
  type DatosInsumosNecesarios,
  cantidadValida,
  categoriaVigente,
  conInsumosDelTipo,
  editorInicial,
  insumosAgregables,
  moverLinea,
  normalizarCantidad,
  resumenInsumosNecesarios,
  validarInsumosNecesarios,
} from "../src/features/configuracion/insumosNecesarios.ts";
import {
  AYUDA_PIEZA_SIN_ELEGIR,
  accionDePieza,
  alcanza,
  etiquetaPiezaElegida,
  exigeMotivo,
  marcasDeRequisito,
  mensajeConAyudaPieza,
  pedidoDePieza,
  previstosConcretos,
  puedeElegirPieza,
  requisitosDe,
  requisitosPendientes,
  textoCantidad,
  textoDisponible,
} from "../src/features/ordenes-reparacion/piezas.ts";
import type {
  OpcionPieza,
  RequisitoInsumoDetalle,
  RolUsuario,
} from "../src/types/api.ts";

const pendiente: RequisitoInsumoDetalle = {
  requisito_id: "REQ-1",
  categoria_id: "CAT-001",
  categoria_nombre: "Módulos › OLED",
  cantidad: "1.000",
  estado: "PENDIENTE",
  requisito_vigente: true,
  insumo_id: null,
  insumo_codigo: null,
  insumo_nombre: null,
  causa: null,
  compatibilidad_no_verificada: false,
  compatible_con_modelo: true,
  reservada: false,
  consumida: false,
  motivo: null,
  elegida_por: null,
  elegida_en: null,
};

const elegida: RequisitoInsumoDetalle = {
  ...pendiente,
  estado: "ELEGIDA",
  insumo_id: "INS-012",
  insumo_codigo: "INS-012",
  insumo_nombre: "Módulo iPhone 14",
  causa: "ELECCION",
  elegida_por: "U-TEC",
  elegida_en: "2026-11-23T10:00:00Z",
};

const opcion = (id: string, cambios: Partial<OpcionPieza> = {}): OpcionPieza => ({
  id,
  codigo: id,
  nombre: `Pieza ${id}`,
  activo: true,
  disponible: "2.000",
  categoria_id: "CAT-001",
  fabricante_id: null,
  variante: null,
  codigo_fabricante: null,
  modelos_compatibles: ["MOD-0001"],
  compatibilidad_no_verificada: false,
  elegida: false,
  ...cambios,
});

const usuario = (rol: RolUsuario, permisos?: string[]) => ({ rol, permisos, activo: true });

describe("pieza de un requisito: presentación", () => {
  test("pendiente: solo «Pendiente de elegir»", () => {
    assert.deepEqual(marcasDeRequisito(pendiente), [
      { texto: "Pendiente de elegir", tono: "alerta" },
    ]);
  });

  test("elegida automáticamente, sin verificar, no compatible, reservada y consumida", () => {
    const textos = marcasDeRequisito({
      ...elegida,
      causa: "AUTOMATICA",
      compatibilidad_no_verificada: true,
      compatible_con_modelo: false,
      reservada: true,
      consumida: true,
      requisito_vigente: false,
    }).map((marca) => marca.texto);
    assert.deepEqual(textos, [
      "Elegida automáticamente",
      "Compatibilidad no verificada",
      "No compatible con el modelo actual",
      "Reservada",
      "Consumida",
      "El tipo ya no lo pide",
    ]);
  });

  test("una elección manual sin novedades no lleva marcas", () => {
    assert.deepEqual(marcasDeRequisito(elegida), []);
  });

  test("etiqueta de la pieza: código y nombre, o la del catálogo", () => {
    assert.equal(etiquetaPiezaElegida(elegida), "INS-012 · Módulo iPhone 14");
    assert.equal(etiquetaPiezaElegida(pendiente), "—");
    assert.equal(
      etiquetaPiezaElegida(elegida, (i) => `${i.codigo} · ${i.nombre} · Acme`),
      "INS-012 · Módulo iPhone 14 · Acme",
    );
    assert.equal(
      etiquetaPiezaElegida({ ...elegida, insumo_codigo: null, insumo_nombre: null }),
      "INS-012",
    );
  });

  test("cantidades y disponible sin ceros de más", () => {
    assert.equal(textoCantidad("1.000"), "1");
    assert.equal(textoCantidad("0.500"), "0.5");
    assert.equal(textoDisponible({ disponible: "3.000" }), "disponible 3");
    assert.equal(textoDisponible({ disponible: "0.000" }), "sin disponible");
    assert.equal(alcanza({ disponible: "1.000" }, "1"), true);
    assert.equal(alcanza({ disponible: "0.5" }, "1.000"), false);
  });

  test("sin requisitos (backend anterior o Tipo sin requisitos) todo queda como antes", () => {
    const previstos = [
      { insumo_id: "INS-001", codigo: "INS-001", nombre: "Adhesivo", cantidad_prevista: "1" },
    ];
    const detalle = { insumos_previstos: previstos };
    assert.deepEqual(requisitosDe(detalle), []);
    assert.deepEqual(requisitosPendientes(detalle), []);
    assert.deepEqual(previstosConcretos(detalle), previstos);
  });

  test("las piezas elegidas se separan de los previstos concretos", () => {
    const detalle = {
      insumos_previstos: [
        { insumo_id: "INS-001", codigo: "INS-001", nombre: "Adhesivo", cantidad_prevista: "1", pieza: false },
        { insumo_id: "INS-012", codigo: "INS-012", nombre: "Módulo", cantidad_prevista: "1", pieza: true },
      ],
      requisitos_insumo: [elegida, { ...pendiente, requisito_id: "REQ-2" }, { ...pendiente, requisito_id: "REQ-3", requisito_vigente: false }],
    };
    assert.deepEqual(
      previstosConcretos(detalle).map((p) => p.insumo_id),
      ["INS-001"],
    );
    assert.deepEqual(
      requisitosPendientes(detalle).map((r) => r.requisito_id),
      ["REQ-2"],
    );
  });
});

describe("pieza de un requisito: qué se ofrece", () => {
  test("permiso PIEZA_ELEGIR: predeterminados y configuración", () => {
    assert.equal(puedeElegirPieza(usuario("TECNICO")), true);
    assert.equal(puedeElegirPieza(usuario("COORDINADOR_RMA")), true);
    assert.equal(puedeElegirPieza(usuario("ADMINISTRADOR")), true);
    assert.equal(puedeElegirPieza(usuario("RECEPCION")), false);
    assert.equal(puedeElegirPieza(usuario("RECEPCION", ["PIEZA_ELEGIR"])), true);
    assert.equal(puedeElegirPieza(usuario("TECNICO", ["ORDENES_CONSULTAR"])), false);
    assert.equal(puedeElegirPieza(null), false);
  });

  test("trabajo definido: elegir la pendiente y sustituir la elegida", () => {
    assert.equal(accionDePieza("DEFINIDO", pendiente, true), "ELEGIR");
    assert.equal(accionDePieza("DEFINIDO", elegida, true), "SUSTITUIR");
  });

  test("en curso: solo se sustituye (la primera elección es antes de iniciar)", () => {
    assert.equal(accionDePieza("EN_PROGRESO", pendiente, true), null);
    assert.equal(accionDePieza("EN_PROGRESO", { ...elegida, reservada: true }, true), "SUSTITUIR");
  });

  test("ni consumida, ni sin permiso, ni con el trabajo terminado o cancelado", () => {
    assert.equal(accionDePieza("EN_PROGRESO", { ...elegida, consumida: true }, true), null);
    assert.equal(accionDePieza("DEFINIDO", pendiente, false), null);
    assert.equal(accionDePieza("COMPLETO", elegida, true), null);
    assert.equal(accionDePieza("CANCELADO", pendiente, true), null);
  });

  test("un requisito que el Tipo ya no pide no se elige por primera vez", () => {
    assert.equal(accionDePieza("DEFINIDO", { ...pendiente, requisito_vigente: false }, true), null);
    assert.equal(accionDePieza("DEFINIDO", { ...elegida, requisito_vigente: false }, true), "SUSTITUIR");
  });

  test("motivo: al sustituir y con una pieza sin compatibilidad verificada", () => {
    assert.equal(exigeMotivo(pendiente), false);
    assert.equal(exigeMotivo(pendiente, opcion("INS-1")), false);
    assert.equal(exigeMotivo(pendiente, opcion("INS-1", { compatibilidad_no_verificada: true })), true);
    assert.equal(exigeMotivo(elegida, opcion("INS-1")), true);
  });
});

describe("pieza de un requisito: qué se envía", () => {
  const opciones = [
    opcion("INS-012", { elegida: true }),
    opcion("INS-013"),
    opcion("INS-020", { compatibilidad_no_verificada: true, modelos_compatibles: ["MOD-0009"] }),
  ];

  test("sin pieza en el formulario: nada que enviar y sin error", () => {
    assert.deepEqual(pedidoDePieza(pendiente, opciones, "", ""), { pedido: null, error: null });
  });

  test("elegir una compatible: sin motivo", () => {
    assert.deepEqual(pedidoDePieza(pendiente, opciones, "INS-013", "  "), {
      pedido: { requisito_id: "REQ-1", insumo_id: "INS-013", motivo: null },
      error: null,
    });
  });

  test("una pieza sin verificar exige motivo", () => {
    const sinMotivo = pedidoDePieza(pendiente, opciones, "INS-020", "");
    assert.equal(sinMotivo.pedido, null);
    assert.match(sinMotivo.error ?? "", /motivo/);
    assert.deepEqual(pedidoDePieza(pendiente, opciones, "INS-020", " Equipo sin modelo "), {
      pedido: { requisito_id: "REQ-1", insumo_id: "INS-020", motivo: "Equipo sin modelo" },
      error: null,
    });
  });

  test("sustituir exige motivo y otra pieza", () => {
    assert.equal(pedidoDePieza(elegida, opciones, "INS-013", "").error, "Sustituir la pieza exige el motivo.");
    assert.match(pedidoDePieza(elegida, opciones, "INS-012", "rota").error ?? "", /elegida ahora/);
    assert.deepEqual(pedidoDePieza(elegida, opciones, "INS-013", "La anterior vino fallada"), {
      pedido: { requisito_id: "REQ-1", insumo_id: "INS-013", motivo: "La anterior vino fallada" },
      error: null,
    });
  });

  test("solo las piezas ofrecidas y un motivo de hasta 500 caracteres", () => {
    assert.match(pedidoDePieza(pendiente, opciones, "INS-999", "").error ?? "", /no está entre/);
    assert.match(pedidoDePieza(elegida, opciones, "INS-013", "x".repeat(501)).error ?? "", /500/);
  });

  test("elegir o sustituir lleva clave de idempotencia (ELEGIR_PIEZA)", () => {
    assert.equal(llevaClave("/api/orders/OR-000001/details/DET-001/pieces"), true);
    assert.equal(llevaClave("/api/orders/OR-000001/details/DET-001/pieces/options"), false);
  });

  test("iniciar sin la pieza elegida: el mensaje dice dónde se elige", () => {
    const mensaje = "Falta elegir la pieza de Módulos en el Detalle DET-001.";
    assert.equal(mensajeConAyudaPieza("PIEZA_SIN_ELEGIR", mensaje), `${mensaje} ${AYUDA_PIEZA_SIN_ELEGIR}`);
    assert.equal(mensajeConAyudaPieza("PRECONDICION_INVALIDA", mensaje), mensaje);
  });
});

// --- Insumos necesarios del Tipo -------------------------------------------

const datos: DatosInsumosNecesarios = {
  previstos: [
    { tipo_reparacion_id: "TR-001", insumo_id: "INS-002", cantidad: "1.000" },
    { tipo_reparacion_id: "TR-001", insumo_id: "INS-001", cantidad: "2.000" },
    // Uno que depende del modelo, cargado antes: se conserva.
    { tipo_reparacion_id: "TR-001", insumo_id: "INS-050", cantidad: "1.000" },
    { tipo_reparacion_id: "TR-002", insumo_id: "INS-001", cantidad: "1.000" },
  ],
  requisitos: [
    { id: "R2", tipo_reparacion_id: "TR-001", categoria_id: "CAT-002", cantidad: "1.000", posicion: 2, activo: true },
    { id: "R1", tipo_reparacion_id: "TR-001", categoria_id: "CAT-001", cantidad: "1.000", posicion: 1, activo: true },
    { id: "R0", tipo_reparacion_id: "TR-001", categoria_id: "CAT-003", cantidad: "1.000", posicion: 3, activo: false },
    { id: "R9", tipo_reparacion_id: "TR-002", categoria_id: "CAT-001", cantidad: "1.000", posicion: 1, activo: true },
  ],
  insumos: [
    { id: "INS-001", codigo: "INS-001", nombre: "Adhesivo", unidad: "u", activo: true, modelos_compatibles: [] },
    { id: "INS-002", codigo: "INS-002", nombre: "Tornillos", unidad: "u", activo: true, modelos_compatibles: [] },
    { id: "INS-003", codigo: "INS-003", nombre: "Alcohol", unidad: "ml", activo: true, modelos_compatibles: [] },
    { id: "INS-004", codigo: "INS-004", nombre: "Viejo", unidad: "u", activo: false, modelos_compatibles: [] },
    { id: "INS-050", codigo: "INS-050", nombre: "Módulo 14", unidad: "u", activo: true, modelos_compatibles: ["MOD-0001"] },
    { id: "INS-051", codigo: "INS-051", nombre: "Módulo 15", unidad: "u", activo: true, modelos_compatibles: ["MOD-0002"] },
  ],
  categorias: [
    { id: "CAT-001", nombre: "Módulos", padre_id: null, activo: true },
    { id: "CAT-002", nombre: "Baterías", padre_id: null, activo: true },
    { id: "CAT-003", nombre: "Viejas", padre_id: null, activo: false },
    { id: "CAT-004", nombre: "OLED", padre_id: "CAT-001", activo: true },
    { id: "CAT-005", nombre: "Flex", padre_id: "CAT-003", activo: true },
  ],
};

describe("insumos necesarios del Tipo: editor", () => {
  test("al abrir: los previstos del Tipo y sus requisitos vigentes en orden", () => {
    assert.deepEqual(editorInicial(datos, "TR-001"), {
      previstos: [
        { insumo_id: "INS-001", cantidad: "2" },
        { insumo_id: "INS-002", cantidad: "1" },
        { insumo_id: "INS-050", cantidad: "1" },
      ],
      requisitos: [
        { categoria_id: "CAT-001", cantidad: "1" },
        { categoria_id: "CAT-002", cantidad: "1" },
      ],
    });
    assert.deepEqual(editorInicial(datos, "TR-009"), { previstos: [], requisitos: [] });
  });

  test("resumen por Tipo", () => {
    assert.equal(resumenInsumosNecesarios(datos, "TR-001"), "3 insumos · 2 requisitos");
    assert.equal(resumenInsumosNecesarios(datos, "TR-002"), "1 insumo · 1 requisito");
    assert.equal(resumenInsumosNecesarios(datos, "TR-009"), "Sin insumos necesarios");
  });

  test("cantidades: mayores que cero, hasta tres decimales, coma o punto", () => {
    assert.equal(cantidadValida("1"), "1");
    assert.equal(cantidadValida("0,5"), "0.5");
    assert.equal(cantidadValida("1.250"), "1.25");
    assert.equal(cantidadValida("0"), null);
    assert.equal(cantidadValida("1.2345"), null);
    assert.equal(cantidadValida("-1"), null);
    assert.equal(cantidadValida("abc"), null);
    assert.equal(cantidadValida(""), null);
    assert.equal(normalizarCantidad("2.000"), "2");
  });

  test("agregables: vigentes y universales, más los que el Tipo ya tiene", () => {
    assert.deepEqual(
      insumosAgregables(datos.insumos).map((i) => i.id),
      ["INS-001", "INS-002", "INS-003"],
    );
    assert.deepEqual(
      insumosAgregables(datos.insumos, ["INS-050"]).map((i) => i.id),
      ["INS-001", "INS-002", "INS-003", "INS-050"],
    );
  });

  test("categoría vigente: la subcategoría de una dada de baja cuenta como de baja", () => {
    assert.equal(categoriaVigente("CAT-004", datos.categorias), true);
    assert.equal(categoriaVigente("CAT-003", datos.categorias), false);
    assert.equal(categoriaVigente("CAT-005", datos.categorias), false);
    assert.equal(categoriaVigente("CAT-999", datos.categorias), false);
  });

  test("mover líneas (el orden de los requisitos es el que se guarda)", () => {
    assert.deepEqual(moverLinea(["a", "b", "c"], 2, -1), ["a", "c", "b"]);
    assert.deepEqual(moverLinea(["a", "b", "c"], 0, 1), ["b", "a", "c"]);
    assert.deepEqual(moverLinea(["a", "b"], 0, -1), ["a", "b"]);
  });
});

describe("insumos necesarios del Tipo: validación y pedido", () => {
  test("sin tocar nada: sin cambios, aunque cambie el orden de los previstos", () => {
    const editor = editorInicial(datos, "TR-001");
    assert.equal(validarInsumosNecesarios(editor, datos, "TR-001").sinCambios, true);
    const otroOrden = { ...editor, previstos: [...editor.previstos].reverse() };
    assert.equal(validarInsumosNecesarios(otroOrden, datos, "TR-001").sinCambios, true);
    // «1.0» es la misma cantidad.
    const mismaCantidad = {
      ...editor,
      previstos: editor.previstos.map((p) => ({ ...p, cantidad: `${p.cantidad}.0` })),
    };
    assert.equal(validarInsumosNecesarios(mismaCantidad, datos, "TR-001").sinCambios, true);
  });

  test("reordenar los requisitos es un cambio", () => {
    const editor = editorInicial(datos, "TR-001");
    const resultado = validarInsumosNecesarios(
      { ...editor, requisitos: moverLinea(editor.requisitos, 1, -1) },
      datos,
      "TR-001",
    );
    assert.equal(resultado.sinCambios, false);
    assert.deepEqual(resultado.errores, []);
    assert.deepEqual(resultado.pedido?.requisitos, [
      { categoria_id: "CAT-002", cantidad: "1" },
      { categoria_id: "CAT-001", cantidad: "1" },
    ]);
  });

  test("el pedido es el conjunto completo: lo que se quita no va", () => {
    const resultado = validarInsumosNecesarios(
      {
        previstos: [{ insumo_id: "INS-003", cantidad: "0,25" }],
        requisitos: [{ categoria_id: "CAT-004", cantidad: "2" }],
      },
      datos,
      "TR-001",
    );
    assert.deepEqual(resultado, {
      pedido: {
        insumos: [{ insumo_id: "INS-003", cantidad: "0.25" }],
        requisitos: [{ categoria_id: "CAT-004", cantidad: "2" }],
      },
      errores: [],
      sinCambios: false,
    });
    const vacio = validarInsumosNecesarios({ previstos: [], requisitos: [] }, datos, "TR-001");
    assert.deepEqual(vacio.pedido, { insumos: [], requisitos: [] });
    assert.equal(vacio.sinCambios, false);
  });

  test("un insumo nuevo tiene que ser vigente y universal; el que ya estaba se conserva", () => {
    const conservado = validarInsumosNecesarios(
      { previstos: [{ insumo_id: "INS-050", cantidad: "1" }], requisitos: [] },
      datos,
      "TR-001",
    );
    assert.deepEqual(conservado.errores, []);
    const errores = validarInsumosNecesarios(
      {
        previstos: [
          { insumo_id: "INS-051", cantidad: "1" },
          { insumo_id: "INS-004", cantidad: "1" },
          { insumo_id: "INS-999", cantidad: "1" },
        ],
        requisitos: [],
      },
      datos,
      "TR-001",
    ).errores;
    assert.equal(errores.length, 3);
    assert.match(errores[0], /INS-051 solo sirve para algunos modelos: agregalo como requisito/);
    assert.match(errores[1], /INS-004 está dado de baja/);
    assert.match(errores[2], /No existe el insumo INS-999/);
  });

  test("repetidos, cantidades inválidas y líneas sin elegir", () => {
    const { pedido, errores } = validarInsumosNecesarios(
      {
        previstos: [
          { insumo_id: "INS-001", cantidad: "1" },
          { insumo_id: "INS-001", cantidad: "2" },
          { insumo_id: "", cantidad: "1" },
          { insumo_id: "INS-002", cantidad: "1.0005" },
        ],
        requisitos: [
          { categoria_id: "CAT-001", cantidad: "1" },
          { categoria_id: "CAT-001", cantidad: "1" },
          { categoria_id: "", cantidad: "1" },
          { categoria_id: "CAT-002", cantidad: "0" },
        ],
      },
      datos,
      "TR-001",
    );
    assert.equal(pedido, null);
    assert.deepEqual(errores, [
      "INS-001 está repetido: va una sola línea con la cantidad total.",
      "Insumo 3: falta elegir el insumo.",
      "La cantidad de INS-002 tiene que ser mayor que cero, con hasta tres decimales.",
      "Módulos está repetida: va un solo requisito con la cantidad total.",
      "Requisito 3: falta elegir la categoría.",
      "La cantidad de Baterías tiene que ser mayor que cero, con hasta tres decimales.",
    ]);
  });

  test("una categoría nueva tiene que estar vigente (también su padre)", () => {
    const errores = validarInsumosNecesarios(
      {
        previstos: [],
        requisitos: [
          { categoria_id: "CAT-003", cantidad: "1" },
          { categoria_id: "CAT-005", cantidad: "1" },
          { categoria_id: "CAT-999", cantidad: "1" },
        ],
      },
      datos,
      "TR-001",
    ).errores;
    assert.deepEqual(errores, [
      "Viejas está dada de baja: no se agrega como requisito.",
      "Flex está dada de baja: no se agrega como requisito.",
      "No existe la categoría CAT-999.",
    ]);
  });

  test("después de guardar: los datos del Tipo se reemplazan con lo devuelto", () => {
    const nuevos = conInsumosDelTipo(
      datos,
      "TR-001",
      [{ tipo_reparacion_id: "TR-001", insumo_id: "INS-003", cantidad: "1.000" }],
      [{ id: "R1", tipo_reparacion_id: "TR-001", categoria_id: "CAT-001", cantidad: "2.000", posicion: 1, activo: true }],
    );
    assert.deepEqual(editorInicial(nuevos, "TR-001"), {
      previstos: [{ insumo_id: "INS-003", cantidad: "1" }],
      requisitos: [{ categoria_id: "CAT-001", cantidad: "2" }],
    });
    assert.deepEqual(editorInicial(nuevos, "TR-002"), editorInicial(datos, "TR-002"));
  });
});
