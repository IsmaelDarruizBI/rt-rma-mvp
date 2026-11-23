"""Reglas de los comprobantes configurables (DEC-AJ-09, BF-19).

- **Datos de la empresa:** Administracion edita el nombre comercial, la
  razon social, el CUIT, la direccion, el telefono, el email, el horario
  de atencion y un pie de comprobante libre, con el permiso no
  configurable de parametros del sistema (``CONFIGURACION_ADMINISTRAR``).
  Cada campo cambiado queda en la auditoria (entidad ``EMPRESA``). Los
  documentos ya emitidos conservan su copia.
- **Terminos y condiciones versionados:** una version nueva se publica
  completa y rige desde ese momento para los comprobantes que se emitan
  despues. Una version publicada nunca se edita ni se borra (la usan los
  documentos que la imprimieron). La publicacion queda en la auditoria
  (entidad ``TEXTO_LEGAL``).

Sin reglas de negocio nuevas sobre el texto: lo redacta el negocio.
"""

from datetime import datetime

from app.domain.models import (
    CambioConfiguracion,
    ContenidoTextoLegal,
    DatosEmpresa,
    EntidadConfiguracion,
    TextoLegal,
    TipoTextoLegal,
    Usuario,
)

from . import permisos
from .autorizacion import validar_alguno_de
from .configuracion import texto
from .exceptions import PrecondicionInvalidaError

CLAVE_EMPRESA = "EMPRESA"

# Lo que edita la pantalla «Datos de la empresa», en su orden.
CAMPOS_EMPRESA = (
    "nombre",
    "razon_social",
    "cuit",
    "direccion",
    "telefono",
    "email",
    "horario",
    "pie_comprobante",
)
# Topes tecnicos (un renglon de comprobante; el pie, un parrafo).
_LARGO_MAXIMO = {"pie_comprobante": 600}
_LARGO_RENGLON = 200


def _normalizado(campo: str, valor: str | None) -> str | None:
    valor = (valor or "").strip()
    if not valor:
        return None
    tope = _LARGO_MAXIMO.get(campo, _LARGO_RENGLON)
    if len(valor) > tope:
        raise PrecondicionInvalidaError(
            f"El campo {campo} admite hasta {tope} caracteres."
        )
    return valor


def datos_de_empresa_editados(
    anterior: DatosEmpresa,
    datos: dict[str, str | None],
    *,
    usuario: Usuario,
    fecha: datetime,
) -> tuple[DatosEmpresa, list[CambioConfiguracion]]:
    """Los datos nuevos y un cambio auditado por cada campo que cambio.

    Los campos que no se editan aca (las condiciones de garantia, que ya
    cubren los terminos versionados) se conservan. El nombre comercial es
    obligatorio: encabeza cada comprobante.
    """
    validar_alguno_de(usuario, permisos.CONFIGURACION_ADMINISTRAR)
    valores = {
        campo: _normalizado(campo, datos.get(campo))
        for campo in CAMPOS_EMPRESA
    }
    if valores["nombre"] is None:
        raise PrecondicionInvalidaError(
            "El nombre comercial de la empresa es obligatorio: encabeza "
            "cada comprobante."
        )
    if valores["email"] is not None and "@" not in valores["email"]:
        raise PrecondicionInvalidaError("El email no es valido.")
    nueva = anterior.model_copy(update=valores)
    cambios = [
        CambioConfiguracion(
            entidad=EntidadConfiguracion.EMPRESA,
            clave=CLAVE_EMPRESA,
            campo=campo,
            valor_anterior=texto(getattr(anterior, campo)),
            valor_nuevo=texto(getattr(nueva, campo)),
            usuario_id=usuario.id,
            fecha=fecha,
        )
        for campo in CAMPOS_EMPRESA
        if texto(getattr(anterior, campo)) != texto(getattr(nueva, campo))
    ]
    if not cambios:
        raise PrecondicionInvalidaError(
            "Los datos de la empresa ya tienen esos valores: no hay cambios."
        )
    return nueva, cambios


def nueva_version_texto_legal(
    versiones: list[TextoLegal],
    vigente: TextoLegal | None,
    *,
    tipo: TipoTextoLegal,
    titulo: str,
    contenido: ContenidoTextoLegal,
    usuario: Usuario,
    fecha: datetime,
) -> tuple[TextoLegal, CambioConfiguracion]:
    """La version siguiente del texto, vigente desde ``fecha``.

    Los apartados se numeran en el orden recibido. Un texto igual al
    vigente no se publica (no hay cambios). Ninguna version anterior se
    toca: los documentos que la usaron la siguen imprimiendo.
    """
    validar_alguno_de(usuario, permisos.CONFIGURACION_ADMINISTRAR)
    titulo = (titulo or "").strip()
    if not titulo:
        raise PrecondicionInvalidaError("El texto legal necesita un titulo.")
    apartados = [
        apartado.model_copy(update={"numero": indice})
        for indice, apartado in enumerate(contenido.apartados, start=1)
    ]
    contenido = contenido.model_copy(
        update={
            "apartados": apartados,
            "pie": [linea.strip() for linea in contenido.pie if linea.strip()],
        }
    )
    if (
        vigente is not None
        and vigente.titulo == titulo
        and vigente.contenido == contenido
    ):
        raise PrecondicionInvalidaError(
            f"El texto es igual a la version {vigente.version} vigente: no "
            "hay cambios."
        )
    version = max((v.version for v in versiones), default=0) + 1
    nuevo = TextoLegal(
        tipo=tipo,
        version=version,
        titulo=titulo,
        contenido=contenido,
        vigente_desde=fecha,
        publicado_por=usuario.id,
    )
    cambio = CambioConfiguracion(
        entidad=EntidadConfiguracion.TEXTO_LEGAL,
        clave=tipo.value,
        campo="version",
        valor_anterior=str(vigente.version) if vigente else None,
        valor_nuevo=str(version),
        usuario_id=usuario.id,
        fecha=fecha,
    )
    return nuevo, cambio
