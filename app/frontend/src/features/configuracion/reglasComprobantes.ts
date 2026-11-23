/**
 * Comprobantes (DEC-AJ-09): reglas de pantalla sin React para «Datos de la
 * empresa» y «Términos y condiciones».
 *
 * - Los datos de la empresa se editan como texto; un campo vacío queda sin
 *   informar. El nombre comercial es obligatorio (encabeza cada
 *   comprobante). Las condiciones de garantía no se editan aquí: las
 *   cubren los términos versionados.
 * - Los términos se editan como un borrador de la versión vigente: cada
 *   apartado es un texto con una línea por renglón. Publicar crea una
 *   versión nueva y completa; ninguna versión publicada se modifica.
 */

import type { DatosEmpresaEditables } from "../../api/configuracion";
import type { ContenidoTextoLegal, EmpresaEnDocumento, TextoLegal } from "../../types/api";

export const CAMPOS_EMPRESA: readonly {
  campo: keyof DatosEmpresaEditables;
  etiqueta: string;
  largo?: boolean;
}[] = [
  { campo: "nombre", etiqueta: "Nombre comercial" },
  { campo: "razon_social", etiqueta: "Razón social" },
  { campo: "cuit", etiqueta: "CUIT" },
  { campo: "direccion", etiqueta: "Dirección" },
  { campo: "telefono", etiqueta: "Teléfono" },
  { campo: "email", etiqueta: "Email" },
  { campo: "horario", etiqueta: "Horario de atención" },
  { campo: "pie_comprobante", etiqueta: "Pie de los comprobantes", largo: true },
];

export type FormularioEmpresa = Record<keyof DatosEmpresaEditables, string>;

export function formularioDeEmpresa(empresa: EmpresaEnDocumento): FormularioEmpresa {
  return Object.fromEntries(
    CAMPOS_EMPRESA.map(({ campo }) => [campo, (empresa[campo] as string | null | undefined) ?? ""]),
  ) as FormularioEmpresa;
}

/** Lo que se envía: los textos sin espacios de más; vacío es `null`. */
export function datosDeEmpresa(formulario: FormularioEmpresa): DatosEmpresaEditables {
  const limpio = (valor: string) => valor.trim() || null;
  return {
    nombre: formulario.nombre.trim(),
    razon_social: limpio(formulario.razon_social),
    cuit: limpio(formulario.cuit),
    direccion: limpio(formulario.direccion),
    telefono: limpio(formulario.telefono),
    email: limpio(formulario.email),
    horario: limpio(formulario.horario),
    pie_comprobante: limpio(formulario.pie_comprobante),
  };
}

/** ¿Cambió algo respecto de lo guardado? */
export function empresaCambio(empresa: EmpresaEnDocumento, formulario: FormularioEmpresa): boolean {
  const datos = datosDeEmpresa(formulario);
  return CAMPOS_EMPRESA.some(({ campo }) => (empresa[campo] ?? null) !== datos[campo]);
}

// --- Términos y condiciones -------------------------------------------------

export interface ApartadoBorrador {
  /** Una línea por renglón: la primera abre el apartado. */
  texto: string;
  destacado: boolean;
}

export interface BorradorTerminos {
  titulo: string;
  marca: string;
  subtitulo: string;
  apartados: ApartadoBorrador[];
  /** Una línea por espacio del pie (firma, aclaración, fecha). */
  pie: string;
}

export function borradorDe(texto: TextoLegal): BorradorTerminos {
  return {
    titulo: texto.titulo,
    marca: texto.contenido.encabezado.marca,
    subtitulo: texto.contenido.encabezado.subtitulo,
    apartados: texto.contenido.apartados.map((apartado) => ({
      texto: apartado.lineas.join("\n"),
      destacado: apartado.destacado,
    })),
    pie: texto.contenido.pie.join("\n"),
  };
}

function lineas(texto: string): string[] {
  return texto
    .split("\n")
    .map((linea) => linea.trim())
    .filter(Boolean);
}

/** Lo que falta para publicar el borrador (vacío: se puede publicar). */
export function faltantesDelBorrador(borrador: BorradorTerminos): string[] {
  const faltantes: string[] = [];
  if (!borrador.titulo.trim()) faltantes.push("el título");
  if (borrador.apartados.length === 0) faltantes.push("al menos un apartado");
  borrador.apartados.forEach((apartado, indice) => {
    if (lineas(apartado.texto).length === 0) faltantes.push(`el texto del apartado ${indice + 1}`);
  });
  return faltantes;
}

/** El contenido de la versión nueva, con los apartados numerados en orden. */
export function contenidoDelBorrador(borrador: BorradorTerminos): {
  titulo: string;
  contenido: ContenidoTextoLegal;
} {
  const titulo = borrador.titulo.trim();
  return {
    titulo,
    contenido: {
      encabezado: {
        marca: borrador.marca.trim(),
        titulo,
        subtitulo: borrador.subtitulo.trim(),
      },
      apartados: borrador.apartados.map((apartado, indice) => ({
        numero: indice + 1,
        lineas: lineas(apartado.texto),
        destacado: apartado.destacado,
      })),
      pie: lineas(borrador.pie),
    },
  };
}

/** ¿El borrador repite la versión vigente? (la API no lo publicaría). */
export function igualAVigente(borrador: BorradorTerminos, vigente: TextoLegal | null): boolean {
  if (!vigente) return false;
  const nuevo = contenidoDelBorrador(borrador);
  return (
    nuevo.titulo === vigente.titulo &&
    JSON.stringify(nuevo.contenido) === JSON.stringify(vigente.contenido)
  );
}
