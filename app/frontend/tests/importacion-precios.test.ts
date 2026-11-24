/**
 * Importación masiva de precios por modelo (DEC-AJ-13): el tipo de la
 * planilla por su extensión, las celdas pegadas como texto con
 * tabulaciones, la consulta, el resumen, cuándo se puede aplicar, la clave
 * de idempotencia de «Aplicar» y la sección de Configuración.
 *
 * Se ejecuta con `npm test` (node --test, sin dependencias extra).
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import type { VistaPreviaImportacion } from "../src/api/configuracion.ts";
import { llevaClave } from "../src/api/idempotencia.ts";
import {
  MAX_BYTES_PLANILLA,
  TIPO_CSV,
  TIPO_PEGADO,
  TIPO_XLSX,
  consultaImportacion,
  etiquetaEstado,
  motivoParaNoAplicar,
  nombrePlantilla,
  planillaDeArchivo,
  planillaPegada,
  puedeAplicar,
  textoObservacion,
  textoResumen,
  tipoDeArchivo,
} from "../src/features/configuracion/importacionPrecios.ts";
import {
  ENTIDAD_DE_SECCION,
  seccionesPermitidas,
} from "../src/features/configuracion/secciones.ts";

function vista(datos: Partial<VistaPreviaImportacion> = {}): VistaPreviaImportacion {
  return {
    formato: "CSV",
    nombre_archivo: "lista.csv",
    resumen: {
      modelos: 2,
      tipos: 1,
      nuevos: 1,
      actualizados: 1,
      sin_cambio: 0,
      vacias: 0,
      errores: 0,
      avisos: 0,
    },
    cambios: [
      {
        celda: "C2",
        modelo_equipo_id: "MOD-0001",
        modelo: "Apple iPhone 8",
        tipo_reparacion_id: "TR-010",
        tipo: "Cambio de módulo",
        anterior: null,
        nuevo: "80000.00",
        estado: "NUEVO",
      },
    ],
    errores: [],
    avisos: [],
    columnas_ignoradas: [],
    aplicable: true,
    editable: true,
    ...datos,
  };
}

describe("Planilla a importar", () => {
  test("el tipo sale de la extensión, no del navegador", () => {
    assert.equal(tipoDeArchivo("Precios.XLSX"), TIPO_XLSX);
    assert.equal(tipoDeArchivo("lista.csv"), TIPO_CSV);
    assert.equal(tipoDeArchivo("pegado.tsv"), TIPO_PEGADO);
    assert.equal(tipoDeArchivo("viejo.xls"), null);
    assert.equal(tipoDeArchivo("foto.png"), null);
  });

  test("un archivo elegido viaja con su tipo; los inválidos se explican", () => {
    // Windows declara los .csv como Excel: se corrige por la extensión.
    const csv = new Blob(["Modelo;TR-010\n"], { type: "application/vnd.ms-excel" });
    const planilla = planillaDeArchivo(csv, "lista.csv");
    assert.ok(!("error" in planilla));
    assert.equal(planilla.cuerpo.type, TIPO_CSV);
    assert.equal(planilla.nombre, "lista.csv");
    const xls = planillaDeArchivo(csv, "viejo.xls");
    assert.ok("error" in xls && xls.error.includes(".xls"));
    const vacio = planillaDeArchivo(new Blob([]), "lista.csv");
    assert.ok("error" in vacio && vacio.error.includes("vacío"));
    const grande = planillaDeArchivo(new Blob([new Uint8Array(MAX_BYTES_PLANILLA + 1)]), "a.xlsx");
    assert.ok("error" in grande && grande.error.includes("2 MB"));
  });

  test("las celdas pegadas son texto con tabulaciones, sin nombre", async () => {
    assert.equal(planillaPegada("  \n "), null);
    const pegada = planillaPegada("Modelo\tTR-010\nMOD-0001\t80.000");
    assert.ok(pegada);
    assert.equal(pegada.cuerpo.type, TIPO_PEGADO);
    assert.equal(pegada.nombre, null);
    assert.equal(await pegada.cuerpo.text(), "Modelo\tTR-010\nMOD-0001\t80.000");
  });

  test("la consulta lleva el usuario y, si hay, el nombre del archivo", () => {
    assert.equal(consultaImportacion("ADMIN-001", null), "usuario_id=ADMIN-001");
    assert.equal(
      consultaImportacion("ADMIN-001", "lista de precios.csv"),
      "usuario_id=ADMIN-001&nombre=lista+de+precios.csv",
    );
  });

  test("solo «Aplicar» lleva clave de idempotencia", () => {
    assert.equal(llevaClave("/api/admin/model-prices/import?usuario_id=A"), true);
    assert.equal(llevaClave("/api/admin/model-prices/import/preview?usuario_id=A"), false);
  });

  test("plantilla con la fecha en el nombre", () => {
    assert.equal(nombrePlantilla("xlsx", new Date(2026, 10, 24)), "precios-por-modelo-20261124.xlsx");
  });
});

describe("Vista previa", () => {
  test("resumen legible", () => {
    assert.equal(
      textoResumen({ ...vista().resumen, sin_cambio: 30, vacias: 4 }),
      "1 precio nuevo, 1 actualizado, 30 sin cambios y 4 celdas vacías",
    );
    assert.equal(
      textoResumen({ ...vista().resumen, nuevos: 2, actualizados: 0, vacias: 1 }),
      "2 precios nuevos, 0 actualizados, 0 sin cambios y 1 celda vacía",
    );
    assert.equal(etiquetaEstado("NUEVO"), "Nuevo");
    assert.equal(etiquetaEstado("CAMBIA"), "Cambia");
    assert.equal(textoObservacion({ celda: "C5", mensaje: "Importe inválido" }), "C5: Importe inválido");
    assert.equal(textoObservacion({ celda: null, mensaje: "Vacía" }), "Vacía");
  });

  test("«Aplicar» solo sin errores, con cambios y sobre PostgreSQL", () => {
    assert.equal(puedeAplicar(null), false);
    assert.match(motivoParaNoAplicar(null) ?? "", /vista previa/);
    assert.equal(puedeAplicar(vista()), true);
    assert.equal(motivoParaNoAplicar(vista()), null);

    const conErrores = vista({
      aplicable: false,
      errores: [{ celda: "C5", mensaje: "x" }, { celda: null, mensaje: "y" }],
    });
    assert.equal(puedeAplicar(conErrores), false);
    assert.match(motivoParaNoAplicar(conErrores) ?? "", /2 errores/);

    const sinCambios = vista({ aplicable: false, cambios: [] });
    assert.equal(puedeAplicar(sinCambios), false);
    assert.match(motivoParaNoAplicar(sinCambios) ?? "", /ningún precio/);

    const json = vista({ editable: false });
    assert.equal(puedeAplicar(json), false);
    assert.match(motivoParaNoAplicar(json) ?? "", /solo lectura/);
  });

  test("la sección se ve con «Gestionar precios» y muestra su historial", () => {
    const admin = {
      rol: "ADMINISTRADOR" as const,
      roles: ["ADMINISTRADOR" as const],
      permisos: ["PRECIOS_GESTIONAR"],
      activo: true,
    };
    assert.deepEqual(
      seccionesPermitidas(admin).map((s) => s.id),
      ["importar-precios"],
    );
    assert.equal(ENTIDAD_DE_SECCION["importar-precios"], "PRECIO_MODELO");
  });
});
