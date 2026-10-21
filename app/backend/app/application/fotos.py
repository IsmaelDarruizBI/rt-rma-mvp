"""Fotografias del equipo (MVP v2, UAT-010).

    agregar_foto              valida, guarda la imagen y registra quien y
                              cuando
    foto_de_orden             devuelve una imagen para verla
    limpiar_fotos_huerfanas   borra imagenes que ninguna Orden usa
                              (Administracion; por defecto solo informa)

La imagen se guarda en el almacenamiento de objetos FUERA de la seccion
critica de las Ordenes (una subida lenta no frena al resto); despues, ya
dentro, se vuelve a validar la Orden y se registran los datos de la foto.
Si ese registro fallara, la imagen queda huerfana en el almacenamiento,
sin referencia desde ninguna Orden: nunca al reves.
"""

from dataclasses import dataclass
from datetime import timedelta

from app.domain.models import OrdenReparacion, RolUsuario
from app.services import (
    PrecondicionInvalidaError,
    buscar_foto,
    clave_de_foto,
    exigir_foto_agregable,
    exigir_orden_abierta,
    fotos_referenciadas,
    nuevo_id,
    registrar_foto,
    validar_alguno_de,
    validar_imagen,
)
from app.storage import AlmacenFotos

from .concurrencia import seccion_critica_ordenes
from .contexto import ApplicationContext
from .modificacion import orden_para_modificar

# Una imagen recien subida puede no estar registrada todavia en su Orden
# (la subida ocurre antes): la limpieza nunca toca las mas nuevas.
ANTIGUEDAD_MINIMA_HUERFANA = timedelta(hours=1)
PREFIJO_FOTOS = "ordenes/"


def _almacen(contexto: ApplicationContext) -> AlmacenFotos:
    if contexto.fotos is None:
        raise PrecondicionInvalidaError(
            "Las fotos no están habilitadas en este entorno: falta "
            "configurar su almacenamiento."
        )
    return contexto.fotos


def agregar_foto(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    contenido: bytes,
    nombre_original: str | None = None,
) -> OrdenReparacion:
    """Agrega UNA foto del equipo a una Orden abierta."""
    almacen = _almacen(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    tipo = validar_imagen(contenido)
    previa = contexto.ordenes.obtener(orden_id)
    exigir_orden_abierta(previa)
    exigir_foto_agregable(previa, usuario=usuario)

    foto_id = nuevo_id("FOT")
    objeto = clave_de_foto(orden_id, foto_id, tipo)
    almacen.guardar(objeto, contenido, tipo)

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = registrar_foto(
            orden,
            foto_id=foto_id,
            objeto=objeto,
            tipo=tipo,
            tamano=len(contenido),
            usuario=usuario,
            fecha=contexto.ahora(),
            nombre_original=nombre_original,
        )
        contexto.ordenes.guardar(orden)
    return orden


@dataclass(frozen=True)
class LimpiezaFotos:
    """Resultado de revisar el almacenamiento contra las Ordenes."""

    aplicada: bool
    revisadas: int
    referenciadas: int
    huerfanas: tuple[str, ...]
    eliminadas: tuple[str, ...]
    recientes_conservadas: tuple[str, ...]


def limpiar_fotos_huerfanas(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    aplicar: bool = False,
) -> LimpiezaFotos:
    """Imagenes que ninguna Orden usa (Administracion).

    En el UAT las Ordenes viven en JSON efimero: un redespliegue las borra
    y sus fotos quedan en el bucket sin Orden. Primero se lista el
    almacenamiento y despues se leen las Ordenes (una foto registrada en el
    medio cuenta como usada). Nunca se borra una imagen que una Orden usa
    ni una mas nueva que ``ANTIGUEDAD_MINIMA_HUERFANA``. Sin ``aplicar``
    solo informa.
    """
    almacen = _almacen(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    validar_alguno_de(usuario, (RolUsuario.ADMINISTRADOR,))
    ahora = contexto.ahora()

    objetos = almacen.listar(PREFIJO_FOTOS)
    with seccion_critica_ordenes():
        usadas = fotos_referenciadas(contexto.ordenes.listar())
    huerfanas = [objeto for objeto in objetos if objeto.clave not in usadas]
    viejas = [
        objeto
        for objeto in huerfanas
        if ahora - objeto.actualizado >= ANTIGUEDAD_MINIMA_HUERFANA
    ]
    recientes = [objeto for objeto in huerfanas if objeto not in viejas]
    eliminadas = []
    if aplicar:
        for objeto in viejas:
            almacen.eliminar(objeto.clave)
            eliminadas.append(objeto.clave)
    return LimpiezaFotos(
        aplicada=aplicar,
        revisadas=len(objetos),
        referenciadas=len(objetos) - len(huerfanas),
        huerfanas=tuple(objeto.clave for objeto in viejas),
        eliminadas=tuple(eliminadas),
        recientes_conservadas=tuple(objeto.clave for objeto in recientes),
    )


def foto_de_orden(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    foto_id: str,
) -> tuple[bytes, str]:
    """La imagen y su tipo, para mostrarla (tambien en Ordenes cerradas)."""
    almacen = _almacen(contexto)
    foto = buscar_foto(contexto.ordenes.obtener(orden_id), foto_id)
    return almacen.obtener(foto.objeto), foto.tipo_contenido
