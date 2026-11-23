/**
 * DEC-AJ-09: los datos de la empresa en la hoja de un comprobante, tal como
 * los copió el documento al emitirse (un cambio posterior en Configuración
 * no altera lo ya emitido). Los comprobantes anteriores no tienen horario
 * ni pie: no se muestran.
 *
 * Solo reglas: la hoja vive en `DocumentosOrden.tsx`.
 */

import type { EmpresaEnDocumento } from "../../types/api";

/** Los renglones bajo el nombre comercial, en orden y sin vacíos. */
export function renglonesDeEmpresa(empresa: EmpresaEnDocumento): string[] {
  return [
    empresa.razon_social,
    empresa.cuit && `CUIT ${empresa.cuit}`,
    empresa.direccion,
    [empresa.telefono, empresa.email].filter(Boolean).join(" · "),
    empresa.horario && `Horario: ${empresa.horario}`,
  ].filter((renglon): renglon is string => Boolean(renglon && renglon.trim()));
}

/** Los párrafos del pie libre del comprobante (vacío si no hay). */
export function pieDeComprobante(empresa: EmpresaEnDocumento): string[] {
  return (empresa.pie_comprobante ?? "")
    .split("\n")
    .map((parrafo) => parrafo.trim())
    .filter(Boolean);
}
