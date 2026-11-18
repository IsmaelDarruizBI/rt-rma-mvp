"""``CatalogoEquiposRepository`` sobre PostgreSQL (bloque C, C4).

La copia del catalogo de Ventas vive en ``rma.catalogo_producto`` y cada
intento en ``rma.sincronizacion_origen`` (copia ``CATALOGO_VENTAS``):
sobreviven a reinicios, redespliegues y al escalado a cero, y la reserva
vale entre instancias. Migraciones ``20261117000100`` y ``20261117000200``.

- ``reservar_sincronizacion``: ``rma.reservar_sincronizacion`` en una
  transaccion corta (se confirma enseguida). La hora la pone la base. Con
  otra vigente, el indice unico de la reserva la rechaza:
  ``ReservaOcupadaError``.
- ``aplicar_sincronizacion``: en UNA transaccion, el upsert de toda la copia
  (nunca ``DELETE``) y el intento EXITOSA. Si algo falla, no cambia nada.
- ``registrar_sincronizacion``: el intento FALLIDA o RECHAZADA, en su propia
  transaccion; la copia no se toca.

Cada escritura lleva el secreto de la reserva en la columna transitoria
``propietario``: la base solo deja escribir la copia y finalizar el intento
a quien reservo (QA C1, M3). El secreto nunca se guarda ni se registra.
"""

import json
from collections.abc import Sequence
from datetime import timedelta

from app.domain.models import (
    MotivoBaja,
    MotivoNoSeleccionable,
    ProductoCatalogo,
    ReservaSincronizacion,
    ResultadoSincronizacion,
    SincronizacionCatalogo,
)
from app.repositories.exceptions import (
    ConflictoDeEscrituraError,
    PersistenciaError,
    ReservaOcupadaError,
)

from .consultas import ESCRITURA, LECTURA, consulta
from .transaccion import UnidadDeTrabajoPostgres

COPIA = "CATALOGO_VENTAS"
INDICE_RESERVA = "sincronizacion_origen_en_curso"
# Como la copia JSON: el estado mira los ultimos intentos.
MAX_SINCRONIZACIONES = 100
CONTADORES = (
    "leidos",
    "filtrados",
    "descartados",
    "nuevos",
    "actualizados",
    "sin_cambios",
    "reactivados",
    "dados_de_baja",
    "vigentes",
    "elegibles",
)

_RESERVAR = consulta(
    "catalogo_equipos.reservar",
    """
    SELECT r.id, r.iniciada_en, r.vence_en
    FROM rma.reservar_sincronizacion(
        %(id)s, %(copia)s,
        (SELECT u.id FROM rma.usuario u WHERE u.codigo = %(usuario)s),
        %(origen)s, %(filtro)s, %(duracion)s, %(propietario)s
    ) r
    """,
    modo=ESCRITURA,
)
_FINALIZAR = consulta(
    "catalogo_equipos.finalizar",
    """
    UPDATE rma.sincronizacion_origen
    SET resultado = %(resultado)s,
        mensaje = %(mensaje)s,
        contadores = %(contadores)s::jsonb,
        propietario = %(propietario)s
    WHERE id = %(id)s AND copia = %(copia)s AND resultado = 'EN_CURSO'
    """,
    modo=ESCRITURA,
)
_GUARDAR_PRODUCTO = consulta(
    "catalogo_equipos.guardar_producto",
    """
    INSERT INTO rma.catalogo_producto (
        tipo_producto_id, descripcion, categoria, subcategoria, grupo,
        marca, modelo, variante, capacidad, color, color_generico,
        seleccionable, motivo_no_seleccionable, vigente, motivo_baja,
        valores_origen, primera_sincronizacion, ultima_sincronizacion,
        sincronizacion_id, propietario
    ) VALUES (
        %(tipo_producto_id)s, %(descripcion)s, %(categoria)s,
        %(subcategoria)s, %(grupo)s, %(marca)s, %(modelo)s, %(variante)s,
        %(capacidad)s, %(color)s, %(color_generico)s, %(seleccionable)s,
        %(motivo_no_seleccionable)s, %(vigente)s, %(motivo_baja)s,
        %(valores_origen)s::jsonb, %(primera_sincronizacion)s,
        %(ultima_sincronizacion)s, %(sincronizacion_id)s, %(propietario)s
    )
    ON CONFLICT (tipo_producto_id) DO UPDATE SET
        descripcion = EXCLUDED.descripcion,
        categoria = EXCLUDED.categoria,
        subcategoria = EXCLUDED.subcategoria,
        grupo = EXCLUDED.grupo,
        marca = EXCLUDED.marca,
        modelo = EXCLUDED.modelo,
        variante = EXCLUDED.variante,
        capacidad = EXCLUDED.capacidad,
        color = EXCLUDED.color,
        color_generico = EXCLUDED.color_generico,
        seleccionable = EXCLUDED.seleccionable,
        motivo_no_seleccionable = EXCLUDED.motivo_no_seleccionable,
        vigente = EXCLUDED.vigente,
        motivo_baja = EXCLUDED.motivo_baja,
        valores_origen = EXCLUDED.valores_origen,
        ultima_sincronizacion = EXCLUDED.ultima_sincronizacion,
        sincronizacion_id = EXCLUDED.sincronizacion_id,
        propietario = %(propietario)s
    """,
    modo=ESCRITURA,
)
_COLUMNAS_PRODUCTO = """
    SELECT tipo_producto_id, descripcion, categoria, subcategoria, grupo,
           marca, modelo, variante, capacidad, color, color_generico,
           seleccionable, motivo_no_seleccionable, vigente, motivo_baja,
           valores_origen, primera_sincronizacion, ultima_sincronizacion
    FROM rma.catalogo_producto
"""
_PRODUCTOS = consulta(
    "catalogo_equipos.productos",
    _COLUMNAS_PRODUCTO
    + """
    ORDER BY tipo_producto_id COLLATE "C"
    """,
    modo=LECTURA,
)
_PRODUCTO = consulta(
    "catalogo_equipos.producto",
    _COLUMNAS_PRODUCTO
    + """
    WHERE tipo_producto_id = %(tipo_producto_id)s
    """,
    modo=LECTURA,
)
_SINCRONIZACIONES = consulta(
    "catalogo_equipos.sincronizaciones",
    """
    SELECT ultimas.* FROM (
        SELECT s.id, u.codigo AS usuario, s.origen, s.filtro, s.iniciada_en,
               s.finalizada_en, s.resultado, s.mensaje, s.contadores
        FROM rma.sincronizacion_origen s
        JOIN rma.usuario u ON u.id = s.usuario_id
        WHERE s.copia = %(copia)s AND s.resultado <> 'EN_CURSO'
        ORDER BY s.finalizada_en DESC, s.id DESC
        LIMIT %(limite)s
    ) ultimas
    ORDER BY ultimas.finalizada_en, ultimas.id
    """,
    modo=LECTURA,
)


class PostgresCatalogoEquiposRepository:
    """Implementa ``CatalogoEquiposRepository`` sobre la base."""

    def __init__(self, unidad: UnidadDeTrabajoPostgres) -> None:
        self._unidad = unidad

    # --- Lecturas -------------------------------------------------------

    def listar_productos(self) -> list[ProductoCatalogo]:
        with self._unidad.lectura() as lector:
            return [_producto(f) for f in lector.filas(_PRODUCTOS)]

    def obtener_producto(
        self, tipo_producto_id: str
    ) -> ProductoCatalogo | None:
        with self._unidad.lectura() as lector:
            fila = lector.fila(
                _PRODUCTO, {"tipo_producto_id": tipo_producto_id}
            )
        return _producto(fila) if fila is not None else None

    def listar_sincronizaciones(self) -> list[SincronizacionCatalogo]:
        with self._unidad.lectura() as lector:
            filas = lector.filas(
                _SINCRONIZACIONES,
                {"copia": COPIA, "limite": MAX_SINCRONIZACIONES},
            )
        return [_sincronizacion(f) for f in filas]

    # --- Ciclo de una sincronizacion ------------------------------------

    def reservar_sincronizacion(
        self,
        *,
        id: str,
        usuario_id: str,
        origen: str,
        filtro: str,
        duracion: timedelta,
        propietario: str,
    ) -> ReservaSincronizacion:
        try:
            with self._unidad.transaccion():
                fila = self._unidad.ejecutor().fila(
                    _RESERVAR,
                    {
                        "id": id,
                        "copia": COPIA,
                        "usuario": usuario_id,
                        "origen": origen,
                        "filtro": filtro,
                        "duracion": duracion,
                        "propietario": propietario,
                    },
                )
        except ConflictoDeEscrituraError as error:
            if getattr(error, "restriccion", None) == INDICE_RESERVA:
                raise ReservaOcupadaError(
                    "Ya hay una sincronización del catálogo en curso."
                ) from None
            raise
        return ReservaSincronizacion(
            id=fila.id,
            copia=COPIA,
            usuario_id=usuario_id,
            origen=origen,
            filtro=filtro,
            iniciada_en=fila.iniciada_en,
            vence_en=fila.vence_en,
            propietario=propietario,
        )

    def registrar_sincronizacion(
        self,
        sincronizacion: SincronizacionCatalogo,
        reserva: ReservaSincronizacion | None = None,
    ) -> None:
        reserva = _exigir(reserva, sincronizacion)
        with self._unidad.transaccion():
            self._finalizar(self._unidad.ejecutor(), sincronizacion, reserva)

    def aplicar_sincronizacion(
        self,
        sincronizacion: SincronizacionCatalogo,
        productos: Sequence[ProductoCatalogo],
        reserva: ReservaSincronizacion | None = None,
    ) -> None:
        reserva = _exigir(reserva, sincronizacion)
        if sincronizacion.resultado is not ResultadoSincronizacion.EXITOSA:
            raise PersistenciaError(
                "Solo una sincronización EXITOSA cambia la copia."
            )
        with self._unidad.transaccion():
            ejecutor = self._unidad.ejecutor()
            if productos:
                ejecutor.ejecutar_lote(
                    _GUARDAR_PRODUCTO,
                    [_parametros(p, reserva) for p in productos],
                )
            self._finalizar(ejecutor, sincronizacion, reserva)

    # --- Internos -------------------------------------------------------

    @staticmethod
    def _finalizar(
        ejecutor,
        sincronizacion: SincronizacionCatalogo,
        reserva: ReservaSincronizacion,
    ) -> None:
        finalizados = ejecutor.ejecutar(
            _FINALIZAR,
            {
                "id": reserva.id,
                "copia": COPIA,
                "resultado": sincronizacion.resultado.value,
                "mensaje": sincronizacion.mensaje,
                "contadores": json.dumps(
                    {c: getattr(sincronizacion, c) for c in CONTADORES}
                ),
                "propietario": reserva.propietario,
            },
        )
        if finalizados != 1:
            raise PersistenciaError(
                f"El intento {reserva.id} ya no está en curso: no se "
                "finalizó (su reserva venció y otra sincronización la "
                "interrumpió)."
            )


def _exigir(
    reserva: ReservaSincronizacion | None,
    sincronizacion: SincronizacionCatalogo,
) -> ReservaSincronizacion:
    """En la base, solo quien reservo finaliza: sin reserva no hay como."""
    if reserva is None or reserva.id != sincronizacion.id:
        raise PersistenciaError(
            "Para finalizar una sincronización hace falta su reserva."
        )
    return reserva


def _parametros(
    producto: ProductoCatalogo, reserva: ReservaSincronizacion
) -> dict:
    return {
        "tipo_producto_id": producto.tipo_producto_id,
        "descripcion": producto.descripcion,
        "categoria": producto.categoria,
        "subcategoria": producto.subcategoria,
        "grupo": producto.grupo,
        "marca": producto.marca,
        "modelo": producto.modelo,
        "variante": producto.variante,
        "capacidad": producto.capacidad,
        "color": producto.color,
        "color_generico": producto.color_generico,
        "seleccionable": producto.seleccionable,
        "motivo_no_seleccionable": (
            producto.motivo_no_seleccionable.value
            if producto.motivo_no_seleccionable
            else None
        ),
        "vigente": producto.vigente,
        "motivo_baja": (
            producto.motivo_baja.value if producto.motivo_baja else None
        ),
        "valores_origen": json.dumps(producto.valores_origen),
        "primera_sincronizacion": producto.primera_sincronizacion,
        "ultima_sincronizacion": producto.ultima_sincronizacion,
        "sincronizacion_id": reserva.id,
        "propietario": reserva.propietario,
    }


def _producto(f) -> ProductoCatalogo:
    return ProductoCatalogo(
        tipo_producto_id=f.tipo_producto_id,
        descripcion=f.descripcion,
        categoria=f.categoria,
        subcategoria=f.subcategoria,
        grupo=f.grupo,
        marca=f.marca,
        modelo=f.modelo,
        variante=f.variante,
        capacidad=f.capacidad,
        color=f.color,
        color_generico=f.color_generico,
        seleccionable=f.seleccionable,
        motivo_no_seleccionable=(
            MotivoNoSeleccionable(f.motivo_no_seleccionable)
            if f.motivo_no_seleccionable
            else None
        ),
        vigente=f.vigente,
        motivo_baja=MotivoBaja(f.motivo_baja) if f.motivo_baja else None,
        valores_origen=dict(f.valores_origen),
        primera_sincronizacion=f.primera_sincronizacion,
        ultima_sincronizacion=f.ultima_sincronizacion,
    )


def _sincronizacion(f) -> SincronizacionCatalogo:
    contadores = f.contadores or {}
    return SincronizacionCatalogo(
        id=f.id,
        usuario_id=f.usuario,
        origen=f.origen,
        filtro=f.filtro,
        iniciada_en=f.iniciada_en,
        finalizada_en=f.finalizada_en,
        resultado=ResultadoSincronizacion(f.resultado),
        mensaje=f.mensaje,
        **{c: int(contadores.get(c, 0)) for c in CONTADORES},
    )
