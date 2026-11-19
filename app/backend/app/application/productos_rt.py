"""Reparacion RT, etapa 1: Productos de Gestion RT en reparacion.

    sincronizar_productos_rt   lee el origen y actualiza la copia (a pedido;
                               Administracion, DEC-RT-05)
    estado_productos_rt        de cuando son los datos y como termino el
                               ultimo intento
    listar_productos_rt        busqueda, filtros, paginas y coincidencias
    ficha_producto_rt          datos tecnicos y coincidencias sugeridas
    sincronizaciones_productos_rt  los ultimos intentos

La sincronizacion usa el motor comun del bloque C
(``application.sincronizacion_origen``): una sola por copia entre todas las
instancias, lectura fuera de toda transaccion, aplicacion atomica, y la
copia anterior intacta si el origen falla o no es confiable. Habla con el
origen solo a traves de ``ProveedorProductosRt``. Solo lectura de Gestion
RT: nada se escribe alla (DEC-RT-01).

Solo sobre PostgreSQL (como Compras): en el modo JSON la copia no existe y
la pantalla lo informa. Las coincidencias con Ordenes son sugerencias:
nunca un vinculo, una Orden activa ni historial (DEC-RT-03).
"""

from dataclasses import dataclass
from datetime import timedelta

from app.domain.models import (
    CoincidenciaSugerida,
    ProductoRt,
    ReservaSincronizacion,
    ResultadoSincronizacion,
    SincronizacionProductosRt,
    Usuario,
)
from app.integraciones.gestion_rt import (
    LecturaProductosRt,
    ProveedorProductosRt,
)
from app.repositories.productos_rt import (
    FiltroProductosRt,
    PaginaProductosRt,
    ProductosRtRepository,
)
from app.services import permisos, validar_alguno_de
from app.services.productos_rt import (
    FusionProductosRt,
    ProductoRtNoEncontradoError,
    ProductosRtNoHabilitadoError,
    ProductosRtRechazadoError,
    fusionar_productos_rt,
)

from .contexto import ApplicationContext
from .sincronizacion_origen import ejecutar_sincronizacion

MENSAJE_SOLO_POSTGRES = (
    "Reparación RT funciona sobre la base PostgreSQL; en el modo JSON no "
    "está disponible."
)


def _copia(contexto: ApplicationContext) -> ProductosRtRepository:
    if contexto.productos_rt is None:
        raise ProductosRtNoHabilitadoError(MENSAJE_SOLO_POSTGRES)
    return contexto.productos_rt


def sincronizar_productos_rt(
    contexto: ApplicationContext, *, usuario_id: str
) -> SincronizacionProductosRt:
    """Actualiza la copia desde el origen y registra el resultado.

    Lanza ``ProductosRtOrigenNoDisponibleError`` (no se pudo leer) o
    ``ProductosRtRechazadoError`` (datos no confiables) DESPUES de
    registrar el intento; en los dos casos la copia queda como estaba. Con
    otra sincronizacion en curso, ``SincronizacionEnCursoError``.
    """
    if contexto.unidad_de_trabajo.en_curso():
        # La reserva se confirma sola y el origen se lee fuera de toda
        # transaccion (como el catalogo de Ventas).
        raise RuntimeError(
            "La sincronización no puede correr dentro de una transacción."
        )
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    validar_alguno_de(usuario, permisos.PRODUCTOS_RT_SINCRONIZAR)
    copia = _copia(contexto)
    proveedor = contexto.proveedor_productos_rt
    if proveedor is None:
        raise ProductosRtNoHabilitadoError(
            "No hay un origen de Productos RT configurado "
            "(RMA_PRODUCTOS_RT_ORIGEN): no se puede sincronizar."
        )
    return ejecutar_sincronizacion(
        _CopiaProductosRt(contexto, copia, proveedor, usuario),
        duracion=contexto.reserva_sincronizacion,
    )


class _CopiaProductosRt:
    """Los Productos RT como ``CopiaSincronizable``.

    La fusion con la copia vigente se hace al VALIDAR: si la lectura no es
    confiable (una lectura truncada), el intento queda RECHAZADA y nada
    cambia. Entre validar y aplicar nadie mas escribe la copia: la reserva
    es de esta sincronizacion."""

    mensaje_en_curso = "Ya hay una sincronización de Productos RT en curso."
    rechazos = (ProductosRtRechazadoError,)

    def __init__(
        self,
        contexto: ApplicationContext,
        repositorio: ProductosRtRepository,
        proveedor: ProveedorProductosRt,
        usuario: Usuario,
    ) -> None:
        self._contexto = contexto
        self._repositorio = repositorio
        self._proveedor = proveedor
        self._usuario = usuario
        self._reserva: ReservaSincronizacion | None = None
        self._fusion: FusionProductosRt | None = None

    def rechazo(self, mensaje: str) -> Exception:
        return ProductosRtRechazadoError(mensaje)

    def reservar(
        self, *, id: str, propietario: str, duracion: timedelta
    ) -> ReservaSincronizacion:
        self._reserva = self._repositorio.reservar_sincronizacion(
            id=id,
            usuario_id=self._usuario.id,
            origen=self._proveedor.descripcion,
            filtro=self._contexto.reglas_productos_rt.descripcion,
            duracion=duracion,
            propietario=propietario,
        )
        return self._reserva

    def leer(self) -> LecturaProductosRt:
        return self._proveedor.leer()

    def validar(self, lectura: LecturaProductosRt) -> None:
        assert self._reserva is not None
        self._fusion = fusionar_productos_rt(
            self._repositorio.listar_productos(),
            lectura.filas,
            lectura.tipos,
            fecha=self._reserva.iniciada_en,
            reglas=self._contexto.reglas_productos_rt,
            leidos=lectura.leidos,
            descartados=lectura.descartados,
            faltantes=lectura.faltantes,
        )

    def aplicar(
        self, reserva: ReservaSincronizacion, lectura: LecturaProductosRt
    ) -> SincronizacionProductosRt:
        assert self._fusion is not None
        sincronizacion = SincronizacionProductosRt(
            **self._base(reserva),
            resultado=ResultadoSincronizacion.EXITOSA,
            contadores=self._fusion.contadores,
            avisos=list(self._fusion.avisos),
        )
        self._repositorio.aplicar_sincronizacion(
            sincronizacion, self._fusion.productos, reserva
        )
        return sincronizacion

    def finalizar(
        self,
        reserva: ReservaSincronizacion,
        resultado: ResultadoSincronizacion,
        mensaje: str,
        lectura: LecturaProductosRt | None,
    ) -> None:
        self._repositorio.registrar_sincronizacion(
            SincronizacionProductosRt(
                **self._base(reserva),
                resultado=resultado,
                mensaje=mensaje,
                contadores={
                    "leidos": lectura.leidos if lectura else 0,
                    "descartados": lectura.descartados if lectura else 0,
                },
            ),
            reserva,
        )

    def _base(self, reserva: ReservaSincronizacion) -> dict:
        return {
            "id": reserva.id,
            "usuario_id": reserva.usuario_id,
            "origen": reserva.origen,
            "filtro": reserva.filtro,
            "iniciada_en": reserva.iniciada_en,
            "finalizada_en": max(self._contexto.ahora(), reserva.iniciada_en),
        }


# --- Consultas ----------------------------------------------------------


@dataclass(frozen=True)
class EstadoProductosRt:
    """De cuando son los datos (siempre visible) y el ultimo intento."""

    habilitado: bool
    # Hay un origen configurado (se puede sincronizar).
    sincronizable: bool
    origen: str | None
    filtro: str
    ultima: SincronizacionProductosRt | None
    ultima_exitosa: SincronizacionProductosRt | None
    # La ultima exitosa es mas vieja que el umbral (o nunca la hubo).
    desactualizada: bool
    antiguedad_aviso: timedelta


def _estado(
    contexto: ApplicationContext,
    ultima: SincronizacionProductosRt | None,
    ultima_exitosa: SincronizacionProductosRt | None,
) -> EstadoProductosRt:
    proveedor = contexto.proveedor_productos_rt
    habilitado = contexto.productos_rt is not None
    umbral = contexto.antiguedad_aviso_productos_rt
    desactualizada = habilitado and (
        ultima_exitosa is None
        or contexto.ahora() - ultima_exitosa.finalizada_en > umbral
    )
    return EstadoProductosRt(
        habilitado=habilitado,
        sincronizable=habilitado and proveedor is not None,
        origen=proveedor.descripcion if proveedor else None,
        filtro=contexto.reglas_productos_rt.descripcion,
        ultima=ultima,
        ultima_exitosa=ultima_exitosa,
        desactualizada=desactualizada,
        antiguedad_aviso=umbral,
    )


def _leer_estado(
    contexto: ApplicationContext, copia: ProductosRtRepository
) -> EstadoProductosRt:
    """Dentro de una lectura abierta por el llamador."""
    ultimas = copia.listar_sincronizaciones(limite=1)
    return _estado(
        contexto, ultimas[0] if ultimas else None, copia.ultima_exitosa()
    )


def estado_productos_rt(contexto: ApplicationContext) -> EstadoProductosRt:
    copia = contexto.productos_rt
    if copia is None:
        return _estado(contexto, None, None)
    with contexto.lectura():
        return _leer_estado(contexto, copia)


def listar_productos_rt(
    contexto: ApplicationContext, filtro: FiltroProductosRt
) -> tuple[EstadoProductosRt, PaginaProductosRt]:
    """El estado de la copia y una pagina del listado, de UNA lectura
    consistente. En el modo JSON: el estado (no habilitado) y nada mas."""
    copia = contexto.productos_rt
    if copia is None:
        return _estado(contexto, None, None), PaginaProductosRt((), 0, ())
    with contexto.lectura():
        return _leer_estado(contexto, copia), copia.buscar(filtro)


@dataclass(frozen=True)
class FichaProductoRt:
    estado: EstadoProductosRt
    producto: ProductoRt
    coincidencias: tuple[CoincidenciaSugerida, ...]


def ficha_producto_rt(
    contexto: ApplicationContext, producto_id: str
) -> FichaProductoRt:
    copia = _copia(contexto)
    with contexto.lectura():
        producto = copia.obtener_producto(producto_id)
        if producto is None:
            raise ProductoRtNoEncontradoError(
                f"No hay un producto {producto_id} en la copia de Gestión RT."
            )
        return FichaProductoRt(
            estado=_leer_estado(contexto, copia),
            producto=producto,
            coincidencias=copia.coincidencias(producto_id),
        )


def sincronizaciones_productos_rt(
    contexto: ApplicationContext, *, limite: int = 10
) -> list[SincronizacionProductosRt]:
    copia = contexto.productos_rt
    if copia is None:
        return []
    with contexto.lectura():
        return copia.listar_sincronizaciones(limite=limite)
