"""Compras (DEC-MI-09): proveedores, solicitudes, ordenes de compra y
recepciones. Sobre PostgreSQL (DC23); en la demo JSON no esta disponible.

Cada recepcion, en una sola transaccion: bloquea la orden de compra,
valida lo pendiente, registra un INGRESO del libro por linea (o por numero
de serie) con su lote y una referencia unica (sin duplicados ante un
reintento) y guarda la recepcion con los movimientos que genero.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.domain.models import TipoMovimientoInsumo
from app.domain.models.compras import (
    CostoCompra,
    EstadoSolicitud,
    ItemOrdenCompra,
    LineaRecepcion,
    OrdenCompra,
    OrigenSolicitud,
    Proveedor,
    SolicitudCompra,
    SugerenciaCompra,
)
from app.domain.models.lotes import OrigenLote
from app.services import (
    EntidadNoEncontradaError,
    PrecondicionInvalidaError,
    faltantes_de_detalles_bloqueados,
    permisos,
    reservas_externas_a,
    situacion_inventario,
)
from app.services.autorizacion import validar_alguno_de
from app.services.compras import (
    cambios_de_proveedor,
    cancelar_orden_compra,
    confirmar_orden_compra,
    costos,
    descartar_solicitud,
    en_camino,
    nueva_orden_compra,
    nueva_recepcion,
    nueva_solicitud,
    sugerencias,
)
from app.services.inventario import insumos_previstos_del_detalle
from app.services.piezas import (
    modelo_de,
    requisito_factible,
    requisitos_pendientes,
)
from app.services.recursos import detalles_bloqueados_por_recursos

from .codigos import con_reintento_de_codigo
from .contexto import ApplicationContext
from .inventario import _registrar_movimiento
from .piezas import requisitos_de_insumo

CERO = Decimal("0")


def _repo(contexto: ApplicationContext):
    if contexto.compras is None:
        raise PrecondicionInvalidaError(
            "Compras funciona sobre la base PostgreSQL (DC23); en el modo "
            "JSON no esta disponible."
        )
    return contexto.compras


def disponible(contexto: ApplicationContext) -> bool:
    return contexto.compras is not None


# --- Proveedores -------------------------------------------------------------


def listar_proveedores(contexto: ApplicationContext) -> list[Proveedor]:
    if contexto.compras is None:
        return []
    with contexto.lectura():
        return contexto.compras.listar_proveedores()


def guardar_proveedor(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    datos: dict,
    codigo: str | None,
) -> Proveedor:
    """Alta (``codigo`` None: el siguiente PRV) o edicion, con auditoria."""
    repo = _repo(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    # El permiso antes de reservar un codigo: un rechazo no consume numeros.
    validar_alguno_de(usuario, permisos.PROVEEDOR_GESTIONAR)
    codigo_informado = codigo

    def intento():
        codigo = codigo_informado
        with contexto.transaccion():
            existentes = {p.id: p for p in repo.listar_proveedores()}
            nuevo = codigo is None
            codigo = codigo or repo.siguiente_codigo("PRV")
            anterior = existentes.get(codigo)
            if not nuevo and anterior is None:
                raise EntidadNoEncontradaError(
                    f"No existe el proveedor {codigo}"
                )
            guardado = Proveedor(id=codigo, **datos)
            cambios = cambios_de_proveedor(
                anterior, guardado, usuario=usuario, fecha=fecha
            )
            repo.guardar_proveedor(guardado, nuevo=nuevo, cambios=cambios)
        return guardado

    return con_reintento_de_codigo(intento, generado=codigo_informado is None)


# --- Solicitudes y sugerencias -----------------------------------------------


def listar_solicitudes(contexto: ApplicationContext) -> list[SolicitudCompra]:
    with contexto.lectura():
        return _repo(contexto).listar_solicitudes()


def crear_solicitud(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    insumo_id: str,
    cantidad: Decimal,
    motivo: str,
    origen: OrigenSolicitud = OrigenSolicitud.MANUAL,
    ordenes: Sequence[str] = (),
) -> SolicitudCompra:
    """Manual, o confirmando una sugerencia: por faltante (``FALTANTE``)
    o de reposicion hasta el minimo (``STOCK_MINIMO``, DEC-AJ-11)."""
    repo = _repo(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    validar_alguno_de(usuario, permisos.COMPRA_SOLICITAR)
    with contexto.transaccion():
        solicitud = nueva_solicitud(
            solicitud_id=repo.siguiente_codigo("SC"),
            insumo=contexto.catalogos.obtener_insumo(insumo_id),
            cantidad=cantidad,
            motivo=motivo,
            origen=origen,
            ordenes=ordenes,
            usuario=usuario,
            fecha=contexto.ahora(),
        )
        repo.agregar_solicitud(solicitud)
    return solicitud


def descartar(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    solicitud_id: str,
    motivo: str,
) -> SolicitudCompra:
    repo = _repo(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    with contexto.transaccion():
        solicitud = descartar_solicitud(
            repo.obtener_solicitud(solicitud_id),
            motivo=motivo,
            usuario=usuario,
            fecha=contexto.ahora(),
        )
        repo.actualizar_solicitud(solicitud)
    return solicitud


def sugerencias_de_compra(
    contexto: ApplicationContext,
) -> list[SugerenciaCompra]:
    """Faltantes de las Ordenes que esperan recursos y reposicion hasta el
    stock minimo (DEC-AJ-11), menos lo disponible y lo que ya esta en
    camino. Solo consulta: nada se compra solo."""
    repo = _repo(contexto)
    with contexto.lectura():
        insumos = contexto.catalogos.listar_insumos()
        previstos = contexto.catalogos.listar_tipo_reparacion_insumos()
        requisitos = requisitos_de_insumo(contexto)
        abiertas = contexto.ordenes.listar_abiertas()
        situaciones = situacion_inventario(insumos, abiertas)
        camino = en_camino(repo.listar_ordenes(), repo.listar_solicitudes())
    demanda: dict[str, tuple[Decimal, list[str]]] = {}
    for orden in abiertas:
        bloqueados = faltantes_de_detalles_bloqueados(
            orden,
            insumos=insumos,
            insumos_previstos=previstos,
            reservas_externas=reservas_externas_a(orden.id, abiertas),
            requisitos=requisitos,
        )
        detalles = {d.id: d for d in orden.reparaciones_detail}
        for detalle_id, faltantes in bloqueados.items():
            # DEC-AJ-14: lo previsto del Detalle con su pieza elegida (la
            # demanda es de ese SKU). Un requisito sin pieza no es demanda
            # de ningun SKU: va en ``requisitos_sin_pieza_de_compra``.
            for previsto in insumos_previstos_del_detalle(
                detalles[detalle_id], previstos
            ):
                if previsto.insumo_id not in faltantes:
                    continue
                cantidad, ordenes = demanda.get(previsto.insumo_id, (CERO, []))
                demanda[previsto.insumo_id] = (
                    cantidad + previsto.cantidad,
                    [*ordenes, orden.id],
                )
    return sugerencias(
        disponibles={s.insumo.id: s.disponible for s in situaciones},
        demanda=demanda,
        en_camino=camino,
        # Un insumo inactivo no se repone (tampoco admite solicitudes).
        minimos={
            i.id: i.stock_minimo
            for i in insumos
            if i.activo and i.stock_minimo is not None
        },
    )


@dataclass(frozen=True)
class RequisitoSinPieza:
    """DEC-AJ-14: un trabajo bloqueado por recursos con un requisito sin
    pieza elegida y sin ninguna pieza elegible con disponible suficiente.
    No es demanda de un SKU (no entra en ``por_faltante``): se informa
    aparte para elegir la pieza o comprar una compatible."""

    orden_id: str
    detalle_id: str
    tipo_reparacion_id: str
    requisito_id: str
    categoria_id: str
    categoria_nombre: str
    cantidad: Decimal
    modelo_equipo_id: str | None


def requisitos_sin_pieza_de_compra(
    contexto: ApplicationContext,
) -> list[RequisitoSinPieza]:
    """Los requisitos sin pieza elegida que hoy bloquean un trabajo (ver
    ``RequisitoSinPieza``). Solo consulta."""
    _repo(contexto)
    with contexto.lectura():
        requisitos = requisitos_de_insumo(contexto)
        if not requisitos.requisitos:
            return []
        insumos = contexto.catalogos.listar_insumos()
        abiertas = contexto.ordenes.listar_abiertas()
    resultado: list[RequisitoSinPieza] = []
    for orden in abiertas:
        bloqueados = set(detalles_bloqueados_por_recursos(orden))
        if not bloqueados:
            continue
        ajenas = reservas_externas_a(orden.id, abiertas)
        for detalle in orden.reparaciones_detail:
            if detalle.id not in bloqueados:
                continue
            for requisito in requisitos_pendientes(detalle, requisitos):
                if requisito_factible(
                    requisito,
                    insumos=insumos,
                    modelo_equipo_id=modelo_de(orden),
                    categorias=requisitos.categorias,
                    movimientos=orden.movimientos_insumo,
                    reservas_externas=ajenas,
                ):
                    continue
                resultado.append(
                    RequisitoSinPieza(
                        orden_id=orden.id,
                        detalle_id=detalle.id,
                        tipo_reparacion_id=detalle.tipo_reparacion_id,
                        requisito_id=requisito.id,
                        categoria_id=requisito.categoria_id,
                        categoria_nombre=requisitos.nombre_categoria(
                            requisito.categoria_id
                        ),
                        cantidad=requisito.cantidad,
                        modelo_equipo_id=modelo_de(orden),
                    )
                )
    return resultado


# --- Ordenes de compra -------------------------------------------------------


def listar_ordenes_compra(contexto: ApplicationContext) -> list[OrdenCompra]:
    with contexto.lectura():
        return _repo(contexto).listar_ordenes()


def obtener_orden_compra(
    contexto: ApplicationContext, orden_id: str
) -> OrdenCompra:
    with contexto.lectura():
        return _repo(contexto).obtener_orden(orden_id)


def crear_orden_compra(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    proveedor_id: str,
    items: Sequence[ItemOrdenCompra],
    solicitudes: Sequence[str] = (),
    observaciones: str | None = None,
) -> OrdenCompra:
    repo = _repo(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    validar_alguno_de(usuario, permisos.OC_CREAR)
    with contexto.transaccion():
        proveedores = {p.id: p for p in repo.listar_proveedores()}
        if proveedor_id not in proveedores:
            raise EntidadNoEncontradaError(
                f"No existe el proveedor {proveedor_id}"
            )
        incluidas = [repo.obtener_solicitud(s) for s in solicitudes]
        orden = nueva_orden_compra(
            orden_compra_id=repo.siguiente_codigo("OC"),
            proveedor=proveedores[proveedor_id],
            items=items,
            solicitudes=incluidas,
            insumos={i.id: i for i in contexto.catalogos.listar_insumos()},
            observaciones=observaciones,
            usuario=usuario,
            fecha=contexto.ahora(),
        )
        repo.agregar_orden(orden)
        for solicitud in incluidas:
            repo.actualizar_solicitud(
                solicitud.model_copy(
                    update={
                        "estado": EstadoSolicitud.EN_ORDEN,
                        "orden_compra_id": orden.id,
                    }
                )
            )
    return orden


def confirmar(
    contexto: ApplicationContext, *, usuario_id: str, orden_id: str
) -> OrdenCompra:
    repo = _repo(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    with contexto.transaccion():
        orden = confirmar_orden_compra(
            repo.obtener_orden(orden_id, bloquear=True),
            usuario=usuario,
            fecha=contexto.ahora(),
        )
        repo.actualizar_orden(orden)
    return orden


def cancelar(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    orden_id: str,
    motivo: str,
) -> OrdenCompra:
    """Sin recepciones; sus solicitudes vuelven a quedar pendientes."""
    repo = _repo(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    with contexto.transaccion():
        orden = cancelar_orden_compra(
            repo.obtener_orden(orden_id, bloquear=True),
            motivo=motivo,
            usuario=usuario,
            fecha=contexto.ahora(),
        )
        repo.actualizar_orden(orden)
        for codigo in orden.solicitudes:
            solicitud = repo.obtener_solicitud(codigo)
            repo.actualizar_solicitud(
                solicitud.model_copy(
                    update={
                        "estado": EstadoSolicitud.PENDIENTE,
                        "orden_compra_id": None,
                    }
                )
            )
    return orden


def recibir(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    orden_id: str,
    lineas: Sequence[LineaRecepcion],
    remito: str | None = None,
    observaciones: str | None = None,
) -> OrdenCompra:
    repo = _repo(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    with contexto.transaccion():
        orden = repo.obtener_orden(orden_id, bloquear=True)
        insumos = {i.id: i for i in contexto.catalogos.listar_insumos()}
        recepcion = nueva_recepcion(
            orden,
            recepcion_id=f"REC-{len(orden.recepciones) + 1:02d}",
            lineas=lineas,
            insumos=insumos,
            remito=remito,
            observaciones=observaciones,
            usuario=usuario,
            fecha=contexto.ahora(),
        )
        con_movimientos = []
        for posicion, linea in enumerate(recepcion.lineas, 1):
            base = f"{orden.id}/{recepcion.id}/{posicion}"
            partes = (
                [
                    (serie, Decimal("1"), f"{base}/{serie}")
                    for serie in linea.series
                ]
                if linea.series
                else [(linea.lote, linea.cantidad, base)]
            )
            movimientos = []
            for lote, cantidad, referencia in partes:
                resultado = _registrar_movimiento(
                    contexto,
                    insumo_id=linea.insumo_id,
                    usuario_id=usuario_id,
                    tipo=TipoMovimientoInsumo.INGRESO,
                    cantidad=cantidad,
                    motivo=f"Compra {orden.id} ({recepcion.id}).",
                    referencia=referencia,
                    operacion_id=None,
                    confirmado=True,
                    lote=lote,
                    origen_lote=OrigenLote.COMPRA,
                    roles=permisos.COMPRA_RECIBIR,
                )
                movimientos.append(resultado.movimiento.id)
            con_movimientos.append(
                linea.model_copy(update={"movimientos": movimientos})
            )
        recepcion = recepcion.model_copy(update={"lineas": con_movimientos})
        repo.agregar_recepcion(orden.id, recepcion)
        orden = orden.model_copy(
            update={"recepciones": [*orden.recepciones, recepcion]}
        )
    return orden


def costos_de_compra(
    contexto: ApplicationContext, insumo_id: str | None = None
) -> list[CostoCompra]:
    """Historico de costos; el primero es el ultimo costo de compra."""
    if contexto.compras is None:
        return []
    with contexto.lectura():
        return costos(contexto.compras.listar_ordenes(), insumo_id)


def ultimos_costos(contexto: ApplicationContext) -> dict[str, CostoCompra]:
    ultimos: dict[str, CostoCompra] = {}
    for costo in costos_de_compra(contexto):
        ultimos.setdefault(costo.insumo_id, costo)
    return ultimos
