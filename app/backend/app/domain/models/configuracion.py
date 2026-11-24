"""Auditoria de la configuracion (DC23AUD, BR-REP-040).

Un ``CambioConfiguracion`` por campo cambiado de un catalogo, con el valor
anterior y el nuevo como texto, el usuario y la fecha/hora. El historial de
precios de un Tipo de Reparacion son sus cambios del campo ``precio``.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class EntidadConfiguracion(str, Enum):
    TIPO_REPARACION = "TIPO_REPARACION"
    MESA_TRABAJO = "MESA_TRABAJO"
    USUARIO = "USUARIO"
    PERMISO = "PERMISO"
    INSUMO = "INSUMO"
    MOTIVO = "MOTIVO"
    PLANTILLA = "PLANTILLA"
    PARAMETRO = "PARAMETRO"
    CHECKLIST = "CHECKLIST"
    PROVEEDOR = "PROVEEDOR"
    MEDIO_PAGO = "MEDIO_PAGO"
    # DEC-AJ-09: datos de la empresa y versiones de los textos legales.
    EMPRESA = "EMPRESA"
    TEXTO_LEGAL = "TEXTO_LEGAL"
    # DEC-AJ-12: modelos de equipo y precios por modelo (clave
    # «TR-001/MOD-0012», campo «precio»).
    MODELO_EQUIPO = "MODELO_EQUIPO"
    PRECIO_MODELO = "PRECIO_MODELO"
    # DEC-AJ-14: categorias de insumos y fabricantes de repuestos. La
    # clasificacion y la compatibilidad de un insumo van en INSUMO.
    CATEGORIA_INSUMO = "CATEGORIA_INSUMO"
    FABRICANTE_REPUESTO = "FABRICANTE_REPUESTO"


class CambioConfiguracion(BaseModel):
    entidad: EntidadConfiguracion
    clave: str = Field(min_length=1)
    campo: str = Field(min_length=1)
    valor_anterior: str | None = None
    valor_nuevo: str | None = None
    usuario_id: str = Field(min_length=1)
    fecha: datetime
    # DEC-AJ-13: los cambios de una importacion masiva de precios por
    # modelo comparten el identificador de la importacion; vacio en los
    # demas cambios.
    importacion_id: str | None = None


class FormatoImportacion(str, Enum):
    """Como llego la planilla de una importacion de precios (DEC-AJ-13)."""

    XLSX = "XLSX"
    CSV = "CSV"
    # Celdas copiadas de Google Sheets o Excel: texto con tabulaciones.
    TEXTO = "TEXTO"


class ImportacionPrecios(BaseModel):
    """Una importacion masiva de precios por modelo aplicada (DEC-AJ-13).

    Agrupa sus cambios de la auditoria (``CambioConfiguracion.importacion_id``)
    y registra quien la aplico, cuando, el archivo y cuantos precios fueron
    nuevos, actualizados o quedaron sin cambios.
    """

    id: str = Field(min_length=1)
    usuario_id: str = Field(min_length=1)
    fecha: datetime
    formato: FormatoImportacion
    nombre_archivo: str | None = None
    nuevos: int = Field(ge=0)
    actualizados: int = Field(ge=0)
    sin_cambio: int = Field(ge=0)
