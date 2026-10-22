"""Catalogo de equipos de Gestion de Ventas.

    sincronizar_catalogo_equipos  lee el origen configurado y actualiza la
                                  copia (manual; Administracion o
                                  Coordinacion RMA)
    estado_catalogo_equipos       ultima sincronizacion y que hay en la copia
    catalogo_para_seleccion       el arbol del selector del alta
    equipo_desde_catalogo         completa el Equipo con el producto elegido

La sincronizacion habla con el origen SOLO a traves de
``ProveedorCatalogo``: no sabe si es Google Sheets, un CSV o una base de
datos. Si el origen falla o responde algo no confiable, el intento queda
registrado y la copia no cambia (sigue la de la ultima sincronizacion
exitosa). El alta de una Orden nunca consulta el origen: lee la copia.
"""

import threading
from dataclasses import dataclass

from app.domain.models import (
    Equipo,
    ResultadoSincronizacion,
    SincronizacionCatalogo,
)
from app.integraciones.catalogo import (
    CatalogoOrigenInvalidoError,
    CatalogoOrigenNoDisponibleError,
    LecturaCatalogo,
)
from app.repositories import CatalogoEquiposRepository
from app.services import (
    CAMPOS_COMERCIALES,
    ROLES_SINCRONIZACION_CATALOGO,
    CatalogoRechazadoError,
    OpcionModelo,
    PrecondicionInvalidaError,
    SincronizacionEnCursoError,
    equipo_carga_manual,
    equipo_con_producto,
    fusionar_catalogo,
    nuevo_id,
    opciones_de_seleccion,
    producto_elegible,
    validar_alguno_de,
    validar_informados,
)

from .contexto import ApplicationContext

# Una sincronizacion por vez en el proceso (la lectura puede tardar unos
# segundos): la segunda se rechaza en vez de esperar.
_SINCRONIZANDO = threading.Lock()


def _copia(contexto: ApplicationContext) -> CatalogoEquiposRepository:
    if contexto.catalogo_equipos is None:
        raise PrecondicionInvalidaError(
            "El catálogo de equipos no está habilitado en este entorno."
        )
    return contexto.catalogo_equipos


def sincronizar_catalogo_equipos(
    contexto: ApplicationContext, *, usuario_id: str
) -> SincronizacionCatalogo:
    """Actualiza la copia desde el origen y registra el resultado.

    Lanza ``CatalogoOrigenNoDisponibleError`` (no se pudo leer) o
    ``CatalogoRechazadoError`` (datos no confiables) DESPUES de registrar
    el intento; en los dos casos la copia queda como estaba.
    """
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    validar_alguno_de(usuario, ROLES_SINCRONIZACION_CATALOGO)
    copia = _copia(contexto)
    proveedor = contexto.proveedor_catalogo
    if proveedor is None:
        raise PrecondicionInvalidaError(
            "No hay un origen del catálogo configurado "
            "(RMA_CATALOGO_ORIGEN): no se puede sincronizar."
        )
    if not _SINCRONIZANDO.acquire(blocking=False):
        raise SincronizacionEnCursoError(
            "Ya hay una sincronización del catálogo en curso."
        )
    try:
        iniciada = contexto.ahora()
        base = {
            "id": nuevo_id("SINC"),
            "usuario_id": usuario.id,
            "origen": proveedor.descripcion,
            "filtro": contexto.filtro_catalogo.descripcion,
            "iniciada_en": iniciada,
        }
        lectura: LecturaCatalogo | None = None
        try:
            lectura = proveedor.leer(contexto.filtro_catalogo)
            validar_informados(lectura.productos)
        except CatalogoOrigenNoDisponibleError as error:
            copia.registrar_sincronizacion(
                _intento(
                    base,
                    contexto,
                    ResultadoSincronizacion.FALLIDA,
                    str(error),
                    lectura,
                )
            )
            raise
        except (CatalogoOrigenInvalidoError, CatalogoRechazadoError) as error:
            copia.registrar_sincronizacion(
                _intento(
                    base,
                    contexto,
                    ResultadoSincronizacion.RECHAZADA,
                    str(error),
                    lectura,
                )
            )
            raise CatalogoRechazadoError(str(error)) from error

        fusion = fusionar_catalogo(
            copia.listar_productos(), lectura.productos, fecha=iniciada
        )
        sincronizacion = SincronizacionCatalogo(
            **base,
            finalizada_en=contexto.ahora(),
            resultado=ResultadoSincronizacion.EXITOSA,
            leidos=lectura.leidos,
            filtrados=lectura.filtrados,
            descartados=lectura.descartados,
            nuevos=fusion.nuevos,
            actualizados=fusion.actualizados,
            sin_cambios=fusion.sin_cambios,
            reactivados=fusion.reactivados,
            dados_de_baja=fusion.dados_de_baja,
            vigentes=fusion.vigentes,
            elegibles=fusion.elegibles,
        )
        copia.aplicar_sincronizacion(sincronizacion, fusion.productos)
        return sincronizacion
    finally:
        _SINCRONIZANDO.release()


def _intento(
    base: dict,
    contexto: ApplicationContext,
    resultado: ResultadoSincronizacion,
    mensaje: str,
    lectura: LecturaCatalogo | None,
) -> SincronizacionCatalogo:
    return SincronizacionCatalogo(
        **base,
        finalizada_en=contexto.ahora(),
        resultado=resultado,
        mensaje=mensaje,
        leidos=lectura.leidos if lectura else 0,
        filtrados=lectura.filtrados if lectura else 0,
        descartados=lectura.descartados if lectura else 0,
    )


@dataclass(frozen=True)
class EstadoCatalogoEquipos:
    habilitado: bool
    # Hay un origen configurado (se puede sincronizar).
    sincronizable: bool
    origen: str | None
    filtro: str
    ultima: SincronizacionCatalogo | None
    ultima_exitosa: SincronizacionCatalogo | None
    vigentes: int
    elegibles: int


def estado_catalogo_equipos(
    contexto: ApplicationContext,
) -> EstadoCatalogoEquipos:
    """Que hay en la copia y como termino la ultima sincronizacion."""
    proveedor = contexto.proveedor_catalogo
    copia = contexto.catalogo_equipos
    sincronizaciones = copia.listar_sincronizaciones() if copia else []
    productos = copia.listar_productos() if copia else []
    exitosas = [
        registro
        for registro in sincronizaciones
        if registro.resultado == ResultadoSincronizacion.EXITOSA
    ]
    return EstadoCatalogoEquipos(
        habilitado=copia is not None,
        sincronizable=copia is not None and proveedor is not None,
        origen=proveedor.descripcion if proveedor else None,
        filtro=contexto.filtro_catalogo.descripcion,
        ultima=sincronizaciones[-1] if sincronizaciones else None,
        ultima_exitosa=exitosas[-1] if exitosas else None,
        vigentes=sum(1 for producto in productos if producto.vigente),
        elegibles=sum(1 for producto in productos if producto.elegible),
    )


def catalogo_para_seleccion(
    contexto: ApplicationContext,
) -> tuple[OpcionModelo, ...]:
    """Modelo -> Variante -> Capacidad -> Color, de la copia local."""
    copia = contexto.catalogo_equipos
    if copia is None:
        return ()
    return opciones_de_seleccion(copia.listar_productos())


def equipo_desde_catalogo(
    contexto: ApplicationContext,
    equipo: Equipo,
    *,
    actual: Equipo | None = None,
) -> Equipo:
    """El Equipo con sus caracteristicas comerciales resueltas.

    Con ``tipo_producto_id``: las del producto de la copia (marca, modelo,
    variante, capacidad y color salen del catalogo, no de lo que mando la
    pantalla). Si es el mismo producto que ya tenia la Orden (``actual``),
    se conservan los datos que tenia: corregir el IMEI no depende de que el
    producto siga en el catalogo. Sin ``tipo_producto_id``: carga manual.
    """
    tipo_id = (equipo.tipo_producto_id or "").strip()
    if not tipo_id:
        return equipo_carga_manual(equipo)
    if actual is not None and actual.tipo_producto_id == tipo_id:
        return equipo.model_copy(
            update={
                campo: getattr(actual, campo) for campo in CAMPOS_COMERCIALES
            }
        )
    copia = contexto.catalogo_equipos
    producto = producto_elegible(
        copia.obtener_producto(tipo_id) if copia else None, tipo_id
    )
    return equipo_con_producto(equipo, producto)
