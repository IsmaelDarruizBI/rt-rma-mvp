"""Datos de la empresa y terminos y condiciones (DEC-AJ-09, BF-19).

La consulta vale en los dos modos (en JSON, los valores iniciales). La
edicion es de Administracion y sobre PostgreSQL, con auditoria en la
misma transaccion, como el resto de la configuracion (DC23): en el modo
JSON es de solo lectura.
"""

from dataclasses import dataclass

from app.domain.models import (
    ContenidoTextoLegal,
    DatosEmpresa,
    TextoLegal,
    TipoTextoLegal,
)
from app.services.comprobantes import (
    datos_de_empresa_editados,
    nueva_version_texto_legal,
)

from .contexto import ApplicationContext
from .operativa import _editable

TERMINOS = TipoTextoLegal.TERMINOS_CONDICIONES_ENTREGA


def datos_empresa(contexto: ApplicationContext) -> DatosEmpresa:
    with contexto.lectura():
        return contexto.catalogos.obtener_datos_empresa()


def guardar_datos_empresa(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    datos: dict[str, str | None],
) -> DatosEmpresa:
    """Administracion edita los datos de la empresa, con auditoria. Rige
    para los comprobantes que se emitan despues."""
    repositorio = _editable(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with contexto.transaccion():
        anterior = contexto.catalogos.obtener_datos_empresa()
        nueva, cambios = datos_de_empresa_editados(
            anterior, datos, usuario=usuario, fecha=fecha
        )
        repositorio.guardar_datos_empresa(nueva, cambios)
    return nueva


@dataclass(frozen=True)
class VersionesTextoLegal:
    """Las versiones publicadas y la que rige ahora."""

    tipo: TipoTextoLegal
    vigente: TextoLegal | None
    versiones: list[TextoLegal]


def versiones_terminos(contexto: ApplicationContext) -> VersionesTextoLegal:
    with contexto.lectura():
        return VersionesTextoLegal(
            tipo=TERMINOS,
            vigente=contexto.catalogos.obtener_texto_legal_vigente(TERMINOS),
            versiones=contexto.catalogos.listar_textos_legales(TERMINOS),
        )


def publicar_terminos(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    titulo: str,
    contenido: ContenidoTextoLegal,
) -> TextoLegal:
    """Publica una version nueva de los terminos y condiciones, vigente
    desde ahora. Las anteriores no cambian."""
    repositorio = _editable(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with contexto.transaccion():
        nuevo, cambio = nueva_version_texto_legal(
            contexto.catalogos.listar_textos_legales(TERMINOS),
            contexto.catalogos.obtener_texto_legal_vigente(TERMINOS),
            tipo=TERMINOS,
            titulo=titulo,
            contenido=contenido,
            usuario=usuario,
            fecha=fecha,
        )
        repositorio.publicar_texto_legal(nuevo, cambio)
    return nuevo
