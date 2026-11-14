"""Compras sobre PostgreSQL (DEC-MI-09).

Proveedores con auditoria (cambio_configuracion), solicitudes, ordenes de
compra con sus items y recepciones con sus lineas. La base impide recibir
mas de lo pedido (trigger) y cambiar lo confirmado; aca se escribe cada
comando en la transaccion en curso.
"""

from collections.abc import Sequence
from datetime import timezone

from app.domain.models import CambioConfiguracion
from app.domain.models.compras import (
    ItemOrdenCompra,
    LineaRecepcion,
    OrdenCompra,
    Proveedor,
    RecepcionCompra,
    SolicitudCompra,
)
from app.repositories.exceptions import (
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
)

from .configuracion import PostgresConfiguracionRepository
from .consultas import ESCRITURA, LECTURA, consulta
from .mapeo import decimal_sin_ceros
from .transaccion import UnidadDeTrabajoPostgres

_TABLAS = {"PRV": "proveedor", "SC": "solicitud_compra", "OC": "orden_compra"}
_ULTIMOS = {
    prefijo: consulta(
        f"compras.ultimo_{tabla}",
        f"SELECT max(codigo) AS codigo FROM rma.{tabla}",
        modo=LECTURA,
    )
    for prefijo, tabla in _TABLAS.items()
}
_PROVEEDORES = consulta(
    "compras.proveedores",
    """
    SELECT codigo, nombre, cuit, telefono, email, contacto, activo
      FROM rma.proveedor ORDER BY codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_INSERTAR_PROVEEDOR = consulta(
    "compras.insertar_proveedor",
    """
    INSERT INTO rma.proveedor
        (codigo, nombre, cuit, telefono, email, contacto, activo)
    VALUES (%(codigo)s, %(nombre)s, %(cuit)s, %(telefono)s, %(email)s,
            %(contacto)s, %(activo)s)
    ON CONFLICT (codigo) DO NOTHING
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_PROVEEDOR = consulta(
    "compras.actualizar_proveedor",
    """
    UPDATE rma.proveedor
       SET nombre = %(nombre)s, cuit = %(cuit)s, telefono = %(telefono)s,
           email = %(email)s, contacto = %(contacto)s, activo = %(activo)s,
           modificado_en = now()
     WHERE codigo = %(codigo)s
    """,
    modo=ESCRITURA,
)
_SOLICITUDES = consulta(
    "compras.solicitudes",
    """
    SELECT s.codigo, i.clave AS insumo, s.cantidad, s.origen, s.motivo,
           s.ordenes, u.codigo AS usuario, s.registrada_en, s.estado,
           oc.codigo AS orden_compra, ud.codigo AS descartada_por,
           s.descartada_en, s.motivo_descarte
      FROM rma.solicitud_compra s
      JOIN rma.insumo i ON i.id = s.insumo_id
      JOIN rma.usuario u ON u.id = s.usuario_id
      LEFT JOIN rma.orden_compra oc ON oc.id = s.orden_compra_id
      LEFT JOIN rma.usuario ud ON ud.id = s.descartada_por
     WHERE (%(codigo)s::text IS NULL OR s.codigo = %(codigo)s)
     ORDER BY s.codigo DESC
    """,
    modo=LECTURA,
)
_INSERTAR_SOLICITUD = consulta(
    "compras.insertar_solicitud",
    """
    INSERT INTO rma.solicitud_compra
        (codigo, insumo_id, cantidad, origen, motivo, ordenes, usuario_id,
         registrada_en)
    SELECT %(codigo)s, i.id, %(cantidad)s, %(origen)s, %(motivo)s,
           %(ordenes)s, u.id, %(fecha)s
      FROM rma.insumo i, rma.usuario u
     WHERE i.clave = %(insumo)s AND u.codigo = %(usuario)s
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_SOLICITUD = consulta(
    "compras.actualizar_solicitud",
    """
    UPDATE rma.solicitud_compra
       SET estado = %(estado)s,
           orden_compra_id = (
               SELECT id FROM rma.orden_compra WHERE codigo = %(orden)s),
           descartada_por = (
               SELECT id FROM rma.usuario WHERE codigo = %(descartada_por)s),
           descartada_en = %(descartada_en)s,
           motivo_descarte = %(motivo_descarte)s
     WHERE codigo = %(codigo)s
    """,
    modo=ESCRITURA,
)
_ORDENES = consulta(
    "compras.ordenes",
    """
    SELECT oc.id, oc.codigo, p.codigo AS proveedor, uc.codigo AS creada_por,
           oc.creada_en, uf.codigo AS confirmada_por, oc.confirmada_en,
           ux.codigo AS cancelada_por, oc.cancelada_en, oc.motivo_cancelacion,
           oc.observaciones,
           ARRAY(SELECT s.codigo FROM rma.solicitud_compra s
                  WHERE s.orden_compra_id = oc.id ORDER BY s.codigo)
             AS solicitudes
      FROM rma.orden_compra oc
      JOIN rma.proveedor p ON p.id = oc.proveedor_id
      JOIN rma.usuario uc ON uc.id = oc.creada_por
      LEFT JOIN rma.usuario uf ON uf.id = oc.confirmada_por
      LEFT JOIN rma.usuario ux ON ux.id = oc.cancelada_por
     WHERE (%(codigo)s::text IS NULL OR oc.codigo = %(codigo)s)
     ORDER BY oc.codigo DESC
    """,
    modo=LECTURA,
)
_BLOQUEAR_ORDEN = consulta(
    "compras.bloquear_orden",
    "SELECT id FROM rma.orden_compra WHERE codigo = %(codigo)s FOR UPDATE",
    modo=ESCRITURA,
)
_ITEMS = consulta(
    "compras.items",
    """
    SELECT it.orden_compra_id, i.clave AS insumo, it.cantidad,
           it.costo_unitario
      FROM rma.orden_compra_item it
      JOIN rma.insumo i ON i.id = it.insumo_id
     WHERE it.orden_compra_id = ANY(%(ids)s)
     ORDER BY it.orden_compra_id, it.posicion
    """,
    modo=LECTURA,
)
_RECEPCIONES = consulta(
    "compras.recepciones",
    """
    SELECT r.id, r.orden_compra_id, r.codigo, u.codigo AS usuario,
           r.registrada_en, r.remito, r.observaciones
      FROM rma.recepcion_compra r
      JOIN rma.usuario u ON u.id = r.usuario_id
     WHERE r.orden_compra_id = ANY(%(ids)s)
     ORDER BY r.orden_compra_id, r.codigo
    """,
    modo=LECTURA,
)
_LINEAS = consulta(
    "compras.lineas",
    """
    SELECT l.recepcion_id, i.clave AS insumo, l.cantidad, l.costo_unitario,
           l.lote, l.series, l.movimientos, l.diferencia
      FROM rma.recepcion_compra_linea l
      JOIN rma.insumo i ON i.id = l.insumo_id
     WHERE l.recepcion_id = ANY(%(ids)s)
     ORDER BY l.recepcion_id, l.posicion
    """,
    modo=LECTURA,
)
_INSERTAR_ORDEN = consulta(
    "compras.insertar_orden",
    """
    INSERT INTO rma.orden_compra
        (codigo, proveedor_id, creada_por, creada_en, observaciones)
    SELECT %(codigo)s, p.id, u.id, %(fecha)s, %(observaciones)s
      FROM rma.proveedor p, rma.usuario u
     WHERE p.codigo = %(proveedor)s AND u.codigo = %(usuario)s
    RETURNING id
    """,
    modo=ESCRITURA,
)
_INSERTAR_ITEM = consulta(
    "compras.insertar_item",
    """
    INSERT INTO rma.orden_compra_item
        (orden_compra_id, insumo_id, cantidad, costo_unitario, posicion)
    SELECT %(orden)s, i.id, %(cantidad)s, %(costo)s, %(posicion)s
      FROM rma.insumo i WHERE i.clave = %(insumo)s
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_ORDEN = consulta(
    "compras.actualizar_orden",
    """
    UPDATE rma.orden_compra
       SET confirmada_por = (
               SELECT id FROM rma.usuario WHERE codigo = %(confirmada_por)s),
           confirmada_en = %(confirmada_en)s,
           cancelada_por = (
               SELECT id FROM rma.usuario WHERE codigo = %(cancelada_por)s),
           cancelada_en = %(cancelada_en)s,
           motivo_cancelacion = %(motivo)s
     WHERE codigo = %(codigo)s
    """,
    modo=ESCRITURA,
)
_INSERTAR_RECEPCION = consulta(
    "compras.insertar_recepcion",
    """
    INSERT INTO rma.recepcion_compra
        (orden_compra_id, codigo, usuario_id, registrada_en, remito,
         observaciones)
    SELECT oc.id, %(codigo)s, u.id, %(fecha)s, %(remito)s, %(observaciones)s
      FROM rma.orden_compra oc, rma.usuario u
     WHERE oc.codigo = %(orden)s AND u.codigo = %(usuario)s
    RETURNING id
    """,
    modo=ESCRITURA,
)
_INSERTAR_LINEA = consulta(
    "compras.insertar_linea",
    """
    INSERT INTO rma.recepcion_compra_linea
        (recepcion_id, posicion, insumo_id, cantidad, costo_unitario, lote,
         series, movimientos, diferencia)
    SELECT %(recepcion)s, %(posicion)s, i.id, %(cantidad)s, %(costo)s,
           %(lote)s, %(series)s, %(movimientos)s, %(diferencia)s
      FROM rma.insumo i WHERE i.clave = %(insumo)s
    """,
    modo=ESCRITURA,
)


def _utc(valor):
    return None if valor is None else valor.astimezone(timezone.utc)


class PostgresComprasRepository:
    def __init__(self, unidad: UnidadDeTrabajoPostgres) -> None:
        self._unidad = unidad
        self._auditoria = PostgresConfiguracionRepository(unidad)

    def _ejecutor(self):
        if not self._unidad.en_curso():
            raise PersistenciaError("Compras exige una transaccion en curso.")
        return self._unidad.ejecutor()

    def siguiente_codigo(self, prefijo: str) -> str:
        with self._unidad.lectura() as lector:
            fila = lector.fila(_ULTIMOS[prefijo])
        ultimo = fila.codigo if fila and fila.codigo else None
        numero = int(ultimo.split("-")[-1]) if ultimo else 0
        ancho = 4 if prefijo == "PRV" else 6
        return f"{prefijo}-{numero + 1:0{ancho}d}"

    # --- Proveedores ---------------------------------------------------------

    def listar_proveedores(self) -> list[Proveedor]:
        with self._unidad.lectura() as lector:
            filas = lector.filas(_PROVEEDORES)
        return [
            Proveedor(
                id=f.codigo,
                nombre=f.nombre,
                cuit=f.cuit,
                telefono=f.telefono,
                email=f.email,
                contacto=f.contacto,
                activo=f.activo,
            )
            for f in filas
        ]

    def guardar_proveedor(
        self,
        proveedor: Proveedor,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None:
        ejecutor = self._ejecutor()
        parametros = {"codigo": proveedor.id, **proveedor.model_dump()}
        parametros.pop("id")
        consulta_sql = _INSERTAR_PROVEEDOR if nuevo else _ACTUALIZAR_PROVEEDOR
        if ejecutor.ejecutar(consulta_sql, parametros) != 1:
            raise PersistenciaError(
                f"No se pudo guardar el proveedor {proveedor.id}."
            )
        self._auditoria._auditar(ejecutor, cambios)

    # --- Solicitudes ---------------------------------------------------------

    def _solicitudes(self, codigo: str | None) -> list[SolicitudCompra]:
        with self._unidad.lectura() as lector:
            filas = lector.filas(_SOLICITUDES, {"codigo": codigo})
        return [
            SolicitudCompra(
                id=f.codigo,
                insumo_id=f.insumo,
                cantidad=decimal_sin_ceros(f.cantidad),
                origen=f.origen,
                motivo=f.motivo,
                ordenes=list(f.ordenes),
                usuario_id=f.usuario,
                fecha=_utc(f.registrada_en),
                estado=f.estado,
                orden_compra_id=f.orden_compra,
                descartada_por=f.descartada_por,
                descartada_en=_utc(f.descartada_en),
                motivo_descarte=f.motivo_descarte,
            )
            for f in filas
        ]

    def listar_solicitudes(self) -> list[SolicitudCompra]:
        return self._solicitudes(None)

    def obtener_solicitud(self, codigo: str) -> SolicitudCompra:
        encontradas = self._solicitudes(codigo)
        if not encontradas:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe la solicitud {codigo}"
            )
        return encontradas[0]

    def agregar_solicitud(self, solicitud: SolicitudCompra) -> None:
        insertadas = self._ejecutor().ejecutar(
            _INSERTAR_SOLICITUD,
            {
                "codigo": solicitud.id,
                "insumo": solicitud.insumo_id,
                "cantidad": solicitud.cantidad,
                "origen": solicitud.origen.value,
                "motivo": solicitud.motivo,
                "ordenes": solicitud.ordenes,
                "usuario": solicitud.usuario_id,
                "fecha": solicitud.fecha,
            },
        )
        if insertadas != 1:
            raise PersistenciaError(
                f"No se pudo registrar la solicitud {solicitud.id}."
            )

    def actualizar_solicitud(self, solicitud: SolicitudCompra) -> None:
        if (
            self._ejecutor().ejecutar(
                _ACTUALIZAR_SOLICITUD,
                {
                    "codigo": solicitud.id,
                    "estado": solicitud.estado.value,
                    "orden": solicitud.orden_compra_id,
                    "descartada_por": solicitud.descartada_por,
                    "descartada_en": solicitud.descartada_en,
                    "motivo_descarte": solicitud.motivo_descarte,
                },
            )
            != 1
        ):
            raise EntidadPersistidaNoEncontradaError(
                f"No existe la solicitud {solicitud.id}"
            )

    # --- Ordenes de compra ---------------------------------------------------

    def _ordenes(self, codigo: str | None) -> list[OrdenCompra]:
        with self._unidad.lectura() as lector:
            filas = lector.filas(_ORDENES, {"codigo": codigo})
            ids = [f.id for f in filas]
            items = lector.filas(_ITEMS, {"ids": ids}) if ids else []
            recepciones = (
                lector.filas(_RECEPCIONES, {"ids": ids}) if ids else []
            )
            ids_rec = [r.id for r in recepciones]
            lineas = lector.filas(_LINEAS, {"ids": ids_rec}) if ids_rec else []
        por_orden_items: dict = {}
        for it in items:
            por_orden_items.setdefault(it.orden_compra_id, []).append(
                ItemOrdenCompra(
                    insumo_id=it.insumo,
                    cantidad=decimal_sin_ceros(it.cantidad),
                    costo_unitario=decimal_sin_ceros(it.costo_unitario),
                )
            )
        por_recepcion: dict = {}
        for ln in lineas:
            por_recepcion.setdefault(ln.recepcion_id, []).append(
                LineaRecepcion(
                    insumo_id=ln.insumo,
                    cantidad=decimal_sin_ceros(ln.cantidad),
                    costo_unitario=decimal_sin_ceros(ln.costo_unitario),
                    lote=ln.lote,
                    series=list(ln.series),
                    movimientos=list(ln.movimientos),
                    diferencia=ln.diferencia,
                )
            )
        por_orden_rec: dict = {}
        for r in recepciones:
            por_orden_rec.setdefault(r.orden_compra_id, []).append(
                RecepcionCompra(
                    id=r.codigo,
                    usuario_id=r.usuario,
                    fecha=_utc(r.registrada_en),
                    remito=r.remito,
                    observaciones=r.observaciones,
                    lineas=por_recepcion.get(r.id, []),
                )
            )
        return [
            OrdenCompra(
                id=f.codigo,
                proveedor_id=f.proveedor,
                items=por_orden_items.get(f.id, []),
                solicitudes=list(f.solicitudes),
                creada_por=f.creada_por,
                creada_en=_utc(f.creada_en),
                confirmada_por=f.confirmada_por,
                confirmada_en=_utc(f.confirmada_en),
                cancelada_por=f.cancelada_por,
                cancelada_en=_utc(f.cancelada_en),
                motivo_cancelacion=f.motivo_cancelacion,
                observaciones=f.observaciones,
                recepciones=por_orden_rec.get(f.id, []),
            )
            for f in filas
        ]

    def listar_ordenes(self) -> list[OrdenCompra]:
        return self._ordenes(None)

    def obtener_orden(
        self, codigo: str, *, bloquear: bool = False
    ) -> OrdenCompra:
        if bloquear:
            self._ejecutor().fila(_BLOQUEAR_ORDEN, {"codigo": codigo})
        encontradas = self._ordenes(codigo)
        if not encontradas:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe la orden de compra {codigo}"
            )
        return encontradas[0]

    def agregar_orden(self, orden: OrdenCompra) -> None:
        ejecutor = self._ejecutor()
        fila = ejecutor.fila(
            _INSERTAR_ORDEN,
            {
                "codigo": orden.id,
                "proveedor": orden.proveedor_id,
                "usuario": orden.creada_por,
                "fecha": orden.creada_en,
                "observaciones": orden.observaciones,
            },
        )
        if fila is None:
            raise PersistenciaError(
                f"No se pudo registrar la orden de compra {orden.id}."
            )
        for posicion, item in enumerate(orden.items, 1):
            ejecutor.ejecutar(
                _INSERTAR_ITEM,
                {
                    "orden": fila.id,
                    "insumo": item.insumo_id,
                    "cantidad": item.cantidad,
                    "costo": item.costo_unitario,
                    "posicion": posicion,
                },
            )

    def actualizar_orden(self, orden: OrdenCompra) -> None:
        if (
            self._ejecutor().ejecutar(
                _ACTUALIZAR_ORDEN,
                {
                    "codigo": orden.id,
                    "confirmada_por": orden.confirmada_por,
                    "confirmada_en": orden.confirmada_en,
                    "cancelada_por": orden.cancelada_por,
                    "cancelada_en": orden.cancelada_en,
                    "motivo": orden.motivo_cancelacion,
                },
            )
            != 1
        ):
            raise EntidadPersistidaNoEncontradaError(
                f"No existe la orden de compra {orden.id}"
            )

    def agregar_recepcion(
        self, orden_id: str, recepcion: RecepcionCompra
    ) -> None:
        ejecutor = self._ejecutor()
        fila = ejecutor.fila(
            _INSERTAR_RECEPCION,
            {
                "orden": orden_id,
                "codigo": recepcion.id,
                "usuario": recepcion.usuario_id,
                "fecha": recepcion.fecha,
                "remito": recepcion.remito,
                "observaciones": recepcion.observaciones,
            },
        )
        if fila is None:
            raise PersistenciaError(
                f"No se pudo registrar la recepcion de {orden_id}."
            )
        for posicion, linea in enumerate(recepcion.lineas, 1):
            ejecutor.ejecutar(
                _INSERTAR_LINEA,
                {
                    "recepcion": fila.id,
                    "posicion": posicion,
                    "insumo": linea.insumo_id,
                    "cantidad": linea.cantidad,
                    "costo": linea.costo_unitario,
                    "lote": linea.lote,
                    "series": linea.series,
                    "movimientos": linea.movimientos,
                    "diferencia": linea.diferencia,
                },
            )
