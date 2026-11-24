"""Importacion masiva de precios por modelo (DEC-AJ-13, BF-02).

Tres casos de uso, con el permiso «Gestionar precios» (PRECIOS_GESTIONAR,
punto 10 de la seccion 11.1 del discovery):

- ``plantilla_precios``: la planilla con los precios vigentes, en .xlsx o
  CSV, para editarla y volver a importarla.
- ``previsualizar_importacion``: lee la planilla y arma la vista previa
  (cambios, errores y avisos) contra el catalogo vigente. No escribe nada;
  funciona tambien en el modo JSON (solo lectura).
- ``aplicar_importacion``: vuelve a leer y validar la planilla en el
  servidor, dentro de la transaccion, contra los precios de ese momento
  (nunca confia en una vista previa del cliente: si un precio cambio en el
  medio, cuenta el actual). Aplica solo sin errores y con algun cambio,
  todo o nada, con ``guardar_precios_modelo``: la importacion queda
  registrada y cada cambio de la auditoria lleva su identificador. Solo
  con PostgreSQL, como el resto de la administracion (DC23).
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel

from app.domain.models import (
    FormatoImportacion,
    ImportacionPrecios,
    ModeloEquipo,
    TipoReparacion,
)
from app.integraciones.planillas import (
    TIPO_CSV,
    TIPO_XLSX,
    PlanillaIlegibleError,
    escribir_csv,
    escribir_xlsx,
    formato_de,
    leer_planilla,
)
from app.services.autorizacion import validar_alguno_de
from app.services.configuracion import ROLES_PRECIOS
from app.services.exceptions import PrecondicionInvalidaError
from app.services.importacion_precios import (
    MAX_COLUMNAS,
    MAX_FILAS,
    Valor,
    VistaPreviaImportacion,
    matriz_plantilla,
    precios_a_aplicar,
    previsualizar,
)

from .configuracion import (
    _repositorio,
    guardar_precios_modelo,
    listar_modelos_administrables,
)
from .contexto import ApplicationContext

MAX_NOMBRE_ARCHIVO = 200


@dataclass(frozen=True)
class ArchivoPlantilla:
    contenido: bytes
    tipo: str
    nombre: str


class ResultadoImportacion(BaseModel):
    """La importacion aplicada y la vista previa con la que se aplico."""

    importacion: ImportacionPrecios
    vista: VistaPreviaImportacion
    cambios_registrados: int


def _catalogo(
    contexto: ApplicationContext,
) -> tuple[dict[str, TipoReparacion], dict[str, ModeloEquipo]]:
    tipos = {t.id: t for t in contexto.catalogos.listar_tipos_reparacion()}
    modelos = {m.id: m for m in listar_modelos_administrables(contexto)}
    return tipos, modelos


def plantilla_precios(
    contexto: ApplicationContext, *, formato: FormatoImportacion
) -> ArchivoPlantilla:
    """La plantilla con los precios vigentes (D-13.1), en .xlsx o CSV."""
    with contexto.lectura():
        tipos, modelos = _catalogo(contexto)
    matriz = matriz_plantilla(list(tipos.values()), list(modelos.values()))
    fecha = contexto.ahora().astimezone(contexto.zona_horaria)
    nombre = f"precios-por-modelo-{fecha:%Y%m%d}"
    if formato is FormatoImportacion.XLSX:
        return ArchivoPlantilla(
            escribir_xlsx(matriz), TIPO_XLSX, f"{nombre}.xlsx"
        )
    return ArchivoPlantilla(
        escribir_csv(matriz), f"{TIPO_CSV}; charset=utf-8", f"{nombre}.csv"
    )


def _leer(
    contenido: bytes, tipo_contenido: str | None
) -> tuple[FormatoImportacion, list[list[Valor]]]:
    try:
        formato = formato_de(contenido, tipo_contenido)
        # Las filas de modelos mas la del encabezado.
        matriz = leer_planilla(
            contenido,
            formato,
            max_filas=MAX_FILAS + 1,
            max_columnas=MAX_COLUMNAS,
        )
    except PlanillaIlegibleError as error:
        raise PrecondicionInvalidaError(str(error)) from error
    return formato, matriz


def _nombre(nombre_archivo: str | None) -> str | None:
    limpio = " ".join((nombre_archivo or "").split())
    return limpio[:MAX_NOMBRE_ARCHIVO] or None


def previsualizar_importacion(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    contenido: bytes,
    tipo_contenido: str | None,
    nombre_archivo: str | None = None,
) -> VistaPreviaImportacion:
    """La vista previa de la importacion (D-13.3), sin escribir nada."""
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    validar_alguno_de(usuario, ROLES_PRECIOS)
    formato, matriz = _leer(contenido, tipo_contenido)
    with contexto.lectura():
        tipos, modelos = _catalogo(contexto)
    return previsualizar(
        matriz,
        tipos=tipos,
        modelos=modelos,
        formato=formato,
        nombre_archivo=_nombre(nombre_archivo),
    )


def aplicar_importacion(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    contenido: bytes,
    tipo_contenido: str | None,
    nombre_archivo: str | None = None,
) -> ResultadoImportacion:
    """Aplica la importacion: todo o nada, auditada con un identificador
    comun. Se rechaza con algun error o si no cambia ningun precio."""
    _repositorio(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    validar_alguno_de(usuario, ROLES_PRECIOS)
    formato, matriz = _leer(contenido, tipo_contenido)
    fecha: datetime = contexto.ahora()
    with contexto.transaccion():
        tipos, modelos = _catalogo(contexto)
        vista = previsualizar(
            matriz,
            tipos=tipos,
            modelos=modelos,
            formato=formato,
            nombre_archivo=_nombre(nombre_archivo),
        )
        if vista.errores:
            primeros = "; ".join(
                f"{e.celda}: {e.mensaje}" if e.celda else e.mensaje
                for e in vista.errores[:3]
            )
            raise PrecondicionInvalidaError(
                f"La importacion tiene {len(vista.errores)} error(es) y no "
                f"se aplico ningun precio. {primeros}"
            )
        if not vista.cambios:
            raise PrecondicionInvalidaError(
                "Los precios ya tienen esos valores: no hay cambios."
            )
        importacion = ImportacionPrecios(
            id=str(uuid4()),
            usuario_id=usuario.id,
            fecha=fecha,
            formato=formato,
            nombre_archivo=vista.nombre_archivo,
            nuevos=vista.resumen.nuevos,
            actualizados=vista.resumen.actualizados,
            sin_cambio=vista.resumen.sin_cambio,
        )
        cambios = guardar_precios_modelo(
            contexto,
            usuario_id=usuario.id,
            precios=precios_a_aplicar(vista),
            importacion=importacion,
        )
    # Lo que quedo registrado: contado sobre los cambios escritos.
    nuevos = sum(1 for c in cambios if c.valor_anterior is None)
    importacion = importacion.model_copy(
        update={"nuevos": nuevos, "actualizados": len(cambios) - nuevos}
    )
    return ResultadoImportacion(
        importacion=importacion,
        vista=vista,
        cambios_registrados=len(cambios),
    )
