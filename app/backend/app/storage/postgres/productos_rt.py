# ruff: noqa: E501  (clase de espacios del SQL)
"""``ProductosRtRepository`` sobre PostgreSQL (Reparacion RT, etapa 1).

La copia vive en ``rma.producto_rt`` y cada intento en
``rma.sincronizacion_origen`` (copia ``PRODUCTOS_RT``): sobreviven a
reinicios y al escalado a cero, y la reserva vale entre instancias.
Migracion ``20261119000100``; el registro y la reserva son los del bloque C
(``20261117000100`` y ``20261117000200``).

- ``reservar_sincronizacion``: ``rma.reservar_sincronizacion`` en una
  transaccion corta. Con otra vigente: ``ReservaOcupadaError``.
- ``aplicar_sincronizacion``: en UNA transaccion, el upsert de toda la copia
  (nunca ``DELETE``) y el intento EXITOSA.
- ``registrar_sincronizacion``: el intento FALLIDA o RECHAZADA; la copia no
  se toca.

Cada escritura lleva el secreto de la reserva en la columna transitoria
``propietario``: solo quien reservo escribe la copia y finaliza el intento.

Las coincidencias sugeridas se calculan al consultar, sin columnas en
``orden``: por referencia RT (Orden ``RT_INTERNO`` cuya ``referencia_rt``,
sin espacios al borde, es el ``producto_id``) y por IMEI (Orden de
cualquier origen cuyo ``equipo_imei`` normalizado -sin espacios, en
mayusculas, como ``domain.identidad.normalizar``- es el IMEI valido y no
repetido del producto). Nunca son vinculos (DEC-RT-03).

La normalizacion en SQL quita los mismos espacios que ``str.split()`` de
Python (la clase de espacios de la expresion regular, el NBSP, los
espacios Unicode y los separadores U+001C a U+001F y U+0085), con los
escapes de caracter Unicode de las expresiones regulares de PostgreSQL
(QA, menor 2).
"""

import json
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from app.domain.models import (
    CoincidenciaSugerida,
    CriterioCoincidencia,
    ProductoRt,
    ReservaSincronizacion,
    ResultadoSincronizacion,
    SincronizacionProductosRt,
)
from app.repositories.exceptions import (
    ConflictoDeEscrituraError,
    PersistenciaError,
    ReservaOcupadaError,
    ReservaPerdidaError,
    RestriccionDeIntegridadError,
)
from app.repositories.productos_rt import (
    FiltroProductosRt,
    PaginaProductosRt,
    ProductoListado,
)

from .consultas import ESCRITURA, LECTURA, consulta
from .transaccion import UnidadDeTrabajoPostgres

COPIA = "PRODUCTOS_RT"
INDICE_RESERVA = "sincronizacion_origen_en_curso"
# restrict_violation: el trigger rechaza escribir con un intento que ya no
# esta EN_CURSO (su reserva vencio y otra la tomo).
SQLSTATE_INTENTO_TERMINADO = "23001"
# Clave de los avisos dentro de ``contadores`` (jsonb).
CLAVE_AVISOS = "avisos"

# Las columnas de ``ProductoRt`` que se guardan tal cual.
CAMPOS = (
    "producto_id",
    "estado_gestion_rt",
    "en_reparacion",
    "en_reparacion_desde",
    "salio_de_reparacion_en",
    "eliminado_en_origen",
    "presente_en_origen",
    "sede",
    "imei",
    "imei_normalizado",
    "imei_valido",
    "imei_luhn_valido",
    "imei_repetido",
    "tipo_producto_id",
    "tipo_producto_encontrado",
    "tipo_producto_eliminado",
    "descripcion_tipo",
    "modelo",
    "categoria",
    "subcategoria",
    "capacidad",
    "color",
    "bateria",
    "detalle_estetico",
    "defecto",
    "toma_rt",
    "tipo_reparacion_origen",
    "repuesto",
    "creado_en_origen",
    "conflicto_origen",
    "cambio_identidad",
    "identidad_anterior",
    "texto_busqueda",
    "huella",
    "primera_vez_visto_en",
    "sincronizado_en",
)
_FECHAS = (
    "en_reparacion_desde",
    "salio_de_reparacion_en",
    "creado_en_origen",
    "primera_vez_visto_en",
    "sincronizado_en",
)

_RESERVAR = consulta(
    "productos_rt.reservar",
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
    "productos_rt.finalizar",
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
_GUARDAR = consulta(
    "productos_rt.guardar",
    """
    INSERT INTO rma.producto_rt (
        producto_id, estado_gestion_rt, en_reparacion, en_reparacion_desde,
        salio_de_reparacion_en, eliminado_en_origen, presente_en_origen,
        sede, imei, imei_normalizado, imei_valido, imei_luhn_valido,
        imei_repetido, tipo_producto_id, tipo_producto_encontrado,
        tipo_producto_eliminado, descripcion_tipo, modelo, categoria,
        subcategoria, capacidad, color, bateria, detalle_estetico, defecto,
        toma_rt, tipo_reparacion_origen, repuesto, creado_en_origen,
        conflicto_origen, cambio_identidad, identidad_anterior,
        texto_busqueda, huella, primera_vez_visto_en, sincronizado_en,
        sincronizacion_id, propietario
    ) VALUES (
        %(producto_id)s, %(estado_gestion_rt)s, %(en_reparacion)s,
        %(en_reparacion_desde)s, %(salio_de_reparacion_en)s,
        %(eliminado_en_origen)s, %(presente_en_origen)s, %(sede)s, %(imei)s,
        %(imei_normalizado)s, %(imei_valido)s, %(imei_luhn_valido)s,
        %(imei_repetido)s, %(tipo_producto_id)s,
        %(tipo_producto_encontrado)s, %(tipo_producto_eliminado)s,
        %(descripcion_tipo)s, %(modelo)s, %(categoria)s, %(subcategoria)s,
        %(capacidad)s, %(color)s, %(bateria)s, %(detalle_estetico)s,
        %(defecto)s, %(toma_rt)s, %(tipo_reparacion_origen)s, %(repuesto)s,
        %(creado_en_origen)s, %(conflicto_origen)s, %(cambio_identidad)s,
        %(identidad_anterior)s::jsonb, %(texto_busqueda)s, %(huella)s,
        %(primera_vez_visto_en)s, %(sincronizado_en)s, %(sincronizacion_id)s,
        %(propietario)s
    )
    ON CONFLICT (producto_id) DO UPDATE SET
        estado_gestion_rt = EXCLUDED.estado_gestion_rt,
        en_reparacion = EXCLUDED.en_reparacion,
        en_reparacion_desde = EXCLUDED.en_reparacion_desde,
        salio_de_reparacion_en = EXCLUDED.salio_de_reparacion_en,
        eliminado_en_origen = EXCLUDED.eliminado_en_origen,
        presente_en_origen = EXCLUDED.presente_en_origen,
        sede = EXCLUDED.sede,
        imei = EXCLUDED.imei,
        imei_normalizado = EXCLUDED.imei_normalizado,
        imei_valido = EXCLUDED.imei_valido,
        imei_luhn_valido = EXCLUDED.imei_luhn_valido,
        imei_repetido = EXCLUDED.imei_repetido,
        tipo_producto_id = EXCLUDED.tipo_producto_id,
        tipo_producto_encontrado = EXCLUDED.tipo_producto_encontrado,
        tipo_producto_eliminado = EXCLUDED.tipo_producto_eliminado,
        descripcion_tipo = EXCLUDED.descripcion_tipo,
        modelo = EXCLUDED.modelo,
        categoria = EXCLUDED.categoria,
        subcategoria = EXCLUDED.subcategoria,
        capacidad = EXCLUDED.capacidad,
        color = EXCLUDED.color,
        bateria = EXCLUDED.bateria,
        detalle_estetico = EXCLUDED.detalle_estetico,
        defecto = EXCLUDED.defecto,
        toma_rt = EXCLUDED.toma_rt,
        tipo_reparacion_origen = EXCLUDED.tipo_reparacion_origen,
        repuesto = EXCLUDED.repuesto,
        creado_en_origen = EXCLUDED.creado_en_origen,
        conflicto_origen = EXCLUDED.conflicto_origen,
        cambio_identidad = EXCLUDED.cambio_identidad,
        identidad_anterior = EXCLUDED.identidad_anterior,
        texto_busqueda = EXCLUDED.texto_busqueda,
        huella = EXCLUDED.huella,
        sincronizado_en = EXCLUDED.sincronizado_en,
        sincronizacion_id = EXCLUDED.sincronizacion_id,
        propietario = %(propietario)s
    """,
    modo=ESCRITURA,
)
_COLUMNAS = """
    SELECT producto_id, estado_gestion_rt, en_reparacion, en_reparacion_desde,
           salio_de_reparacion_en, eliminado_en_origen, presente_en_origen,
           sede, imei, imei_normalizado, imei_valido, imei_luhn_valido,
           imei_repetido, tipo_producto_id, tipo_producto_encontrado,
           tipo_producto_eliminado, descripcion_tipo, modelo, categoria,
           subcategoria, capacidad, color, bateria, detalle_estetico, defecto,
           toma_rt, tipo_reparacion_origen, repuesto, creado_en_origen,
           conflicto_origen, cambio_identidad, identidad_anterior,
           texto_busqueda, huella, primera_vez_visto_en, sincronizado_en
"""
_TODOS = consulta(
    "productos_rt.todos",
    _COLUMNAS
    + """
    FROM rma.producto_rt
    ORDER BY producto_id COLLATE "C"
    """,
    modo=LECTURA,
)
_UNO = consulta(
    "productos_rt.uno",
    _COLUMNAS
    + """
    FROM rma.producto_rt
    WHERE producto_id = %(producto_id)s
    """,
    modo=LECTURA,
)

# Los productos que pasan los filtros (sin el de sede) y si tienen alguna
# coincidencia sugerida. Cada termino debe aparecer en ``texto_busqueda``.
_FILTRADOS = """
    WITH base AS (
        SELECT p.*
        FROM rma.producto_rt p
        WHERE (
            %(incluir_fuera)s
            OR (p.en_reparacion AND p.presente_en_origen
                AND NOT p.eliminado_en_origen)
        )
        AND NOT EXISTS (
            SELECT 1 FROM unnest(%(terminos)s::text[]) AS t(termino)
            WHERE strpos(p.texto_busqueda, t.termino) = 0
        )
    ),
    coincidentes AS (
        SELECT b.producto_id
        FROM base b
        JOIN rma.orden o
          ON o.origen = 'RT_INTERNO' AND btrim(o.referencia_rt) = b.producto_id
        UNION
        SELECT b.producto_id
        FROM base b
        JOIN rma.orden o
          ON b.imei_valido AND NOT b.imei_repetido
         AND upper(regexp_replace(coalesce(o.equipo_imei, ''), '[\\s\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\u001c-\\u001f]', '', 'g'))
             = b.imei_normalizado
    ),
    filtrados AS (
        SELECT b.*,
               b.producto_id IN (SELECT producto_id FROM coincidentes)
                 AS con_sugerencias
        FROM base b
    )
"""
_CONDICION_ORDEN_RMA = """
    WHERE (%(orden_rma)s::text IS NULL
           OR (%(orden_rma)s::text = 'CON_SUGERENCIAS') = con_sugerencias)
"""
_CONDICION_SEDE = """
    AND (
        (cardinality(%(sedes)s::text[]) = 0 AND NOT %(sin_sede)s)
        OR sede = ANY(%(sedes)s::text[])
        OR (sede IS NULL AND %(sin_sede)s)
    )
"""
_POR_SEDE = consulta(
    "productos_rt.por_sede",
    _FILTRADOS
    + """
    SELECT sede, count(*) AS cantidad
    FROM filtrados
    """
    + _CONDICION_ORDEN_RMA
    + """
    GROUP BY sede
    ORDER BY sede NULLS LAST
    """,
    modo=LECTURA,
)
_TOTAL = consulta(
    "productos_rt.total",
    _FILTRADOS
    + """
    SELECT count(*) AS total
    FROM filtrados
    """
    + _CONDICION_ORDEN_RMA
    + _CONDICION_SEDE,
    modo=LECTURA,
)
_PAGINA = consulta(
    "productos_rt.pagina",
    _FILTRADOS
    + """
    SELECT producto_id, estado_gestion_rt, en_reparacion, en_reparacion_desde,
           salio_de_reparacion_en, eliminado_en_origen, presente_en_origen,
           sede, imei, imei_normalizado, imei_valido, imei_luhn_valido,
           imei_repetido, tipo_producto_id, tipo_producto_encontrado,
           tipo_producto_eliminado, descripcion_tipo, modelo, categoria,
           subcategoria, capacidad, color, bateria, detalle_estetico, defecto,
           toma_rt, tipo_reparacion_origen, repuesto, creado_en_origen,
           conflicto_origen, cambio_identidad, identidad_anterior,
           texto_busqueda, huella, primera_vez_visto_en, sincronizado_en
    FROM filtrados
    """
    + _CONDICION_ORDEN_RMA
    + _CONDICION_SEDE
    + """
    ORDER BY en_reparacion_desde NULLS LAST, producto_id COLLATE "C"
    LIMIT %(limite)s OFFSET %(desde)s
    """,
    modo=LECTURA,
)
# Las Ordenes que coinciden con cada producto pedido, una vez por Orden y
# con todos sus criterios.
_COINCIDENCIAS = consulta(
    "productos_rt.coincidencias",
    """
    WITH productos AS (
        SELECT p.producto_id, p.imei_normalizado, p.imei_valido,
               p.imei_repetido
        FROM rma.producto_rt p
        WHERE p.producto_id = ANY(%(ids)s::text[])
    ),
    pares AS (
        SELECT p.producto_id, o.id AS orden_id, 'REFERENCIA_RT' AS criterio
        FROM productos p
        JOIN rma.orden o
          ON o.origen = 'RT_INTERNO' AND btrim(o.referencia_rt) = p.producto_id
        UNION ALL
        SELECT p.producto_id, o.id, 'IMEI'
        FROM productos p
        JOIN rma.orden o
          ON p.imei_valido AND NOT p.imei_repetido
         AND upper(regexp_replace(coalesce(o.equipo_imei, ''), '[\\s\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\u001c-\\u001f]', '', 'g'))
             = p.imei_normalizado
    )
    SELECT pr.producto_id, o.codigo, o.origen, o.estado_workflow,
           (o.cerrada_en IS NOT NULL OR o.estado_workflow = 'ENTREGADA'
            OR o.posicion_proceso = 'EVT-REP-999') AS cerrada,
           o.creada_en,
           array_agg(DISTINCT pr.criterio ORDER BY pr.criterio) AS criterios
    FROM pares pr
    JOIN rma.orden o ON o.id = pr.orden_id
    GROUP BY pr.producto_id, o.id
    ORDER BY pr.producto_id, o.creada_en DESC, o.codigo
    """,
    modo=LECTURA,
)
_SINCRONIZACIONES = consulta(
    "productos_rt.sincronizaciones",
    """
    SELECT s.id, u.codigo AS usuario, s.origen, s.filtro, s.iniciada_en,
           s.finalizada_en, s.resultado, s.mensaje, s.contadores
    FROM rma.sincronizacion_origen s
    JOIN rma.usuario u ON u.id = s.usuario_id
    WHERE s.copia = %(copia)s AND s.resultado <> 'EN_CURSO'
    ORDER BY s.finalizada_en DESC, s.id DESC
    LIMIT %(limite)s
    """,
    modo=LECTURA,
)
_ULTIMA_EXITOSA = consulta(
    "productos_rt.ultima_exitosa",
    """
    SELECT s.id, u.codigo AS usuario, s.origen, s.filtro, s.iniciada_en,
           s.finalizada_en, s.resultado, s.mensaje, s.contadores
    FROM rma.sincronizacion_origen s
    JOIN rma.usuario u ON u.id = s.usuario_id
    WHERE s.copia = %(copia)s AND s.resultado = 'EXITOSA'
    ORDER BY s.finalizada_en DESC, s.id DESC
    LIMIT 1
    """,
    modo=LECTURA,
)


class PostgresProductosRtRepository:
    """Implementa ``ProductosRtRepository`` sobre la base."""

    def __init__(self, unidad: UnidadDeTrabajoPostgres) -> None:
        self._unidad = unidad

    # --- Lecturas -------------------------------------------------------

    def listar_productos(self) -> list[ProductoRt]:
        with self._unidad.lectura() as lector:
            return [_producto(f) for f in lector.filas(_TODOS)]

    def obtener_producto(self, producto_id: str) -> ProductoRt | None:
        with self._unidad.lectura() as lector:
            fila = lector.fila(_UNO, {"producto_id": producto_id})
        return _producto(fila) if fila is not None else None

    def buscar(self, filtro: FiltroProductosRt) -> PaginaProductosRt:
        tamano = max(1, filtro.tamano)
        pagina = max(1, filtro.pagina)
        parametros = {
            "incluir_fuera": filtro.incluir_fuera,
            "terminos": list(filtro.terminos),
            "orden_rma": filtro.orden_rma.value if filtro.orden_rma else None,
            "sedes": [s for s in filtro.sedes if s is not None],
            "sin_sede": None in filtro.sedes,
            "limite": tamano,
            "desde": (pagina - 1) * tamano,
        }
        with self._unidad.lectura() as lector:
            sedes = tuple(
                (f.sede, int(f.cantidad))
                for f in lector.filas(_POR_SEDE, parametros)
            )
            total = int(lector.fila(_TOTAL, parametros).total)
            productos = [
                _producto(f) for f in lector.filas(_PAGINA, parametros)
            ]
            coincidencias = _agrupar(
                lector.filas(
                    _COINCIDENCIAS,
                    {"ids": [p.producto_id for p in productos]},
                )
                if productos
                else []
            )
        return PaginaProductosRt(
            sedes=sedes,
            total=total,
            productos=tuple(
                ProductoListado(
                    producto=p,
                    coincidencias=tuple(coincidencias.get(p.producto_id, ())),
                )
                for p in productos
            ),
        )

    def coincidencias(
        self, producto_id: str
    ) -> tuple[CoincidenciaSugerida, ...]:
        with self._unidad.lectura() as lector:
            filas = lector.filas(_COINCIDENCIAS, {"ids": [producto_id]})
        return tuple(_agrupar(filas).get(producto_id, ()))

    def listar_sincronizaciones(
        self, limite: int = 10
    ) -> list[SincronizacionProductosRt]:
        with self._unidad.lectura() as lector:
            filas = lector.filas(
                _SINCRONIZACIONES, {"copia": COPIA, "limite": max(1, limite)}
            )
        return [_sincronizacion(f) for f in filas]

    def ultima_exitosa(self) -> SincronizacionProductosRt | None:
        with self._unidad.lectura() as lector:
            fila = lector.fila(_ULTIMA_EXITOSA, {"copia": COPIA})
        return _sincronizacion(fila) if fila is not None else None

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
                    "Ya hay una sincronización de Productos RT en curso."
                ) from None
            raise
        return ReservaSincronizacion(
            id=fila.id,
            copia=COPIA,
            usuario_id=usuario_id,
            origen=origen,
            filtro=filtro,
            iniciada_en=_utc(fila.iniciada_en),
            vence_en=_utc(fila.vence_en),
            propietario=propietario,
        )

    def registrar_sincronizacion(
        self,
        sincronizacion: SincronizacionProductosRt,
        reserva: ReservaSincronizacion,
    ) -> None:
        _exigir(reserva, sincronizacion)
        with self._unidad.transaccion():
            self._finalizar(self._unidad.ejecutor(), sincronizacion, reserva)

    def aplicar_sincronizacion(
        self,
        sincronizacion: SincronizacionProductosRt,
        productos: Sequence[ProductoRt],
        reserva: ReservaSincronizacion,
    ) -> None:
        _exigir(reserva, sincronizacion)
        if sincronizacion.resultado is not ResultadoSincronizacion.EXITOSA:
            raise PersistenciaError(
                "Solo una sincronización EXITOSA cambia la copia."
            )
        try:
            with self._unidad.transaccion():
                ejecutor = self._unidad.ejecutor()
                if productos:
                    ejecutor.ejecutar_lote(
                        _GUARDAR,
                        [_parametros(p, reserva) for p in productos],
                    )
                self._finalizar(ejecutor, sincronizacion, reserva)
        except RestriccionDeIntegridadError as error:
            if getattr(error, "sqlstate", None) == SQLSTATE_INTENTO_TERMINADO:
                raise ReservaPerdidaError(
                    _PERDIDA.format(reserva.id)
                ) from None
            raise

    @staticmethod
    def _finalizar(
        ejecutor,
        sincronizacion: SincronizacionProductosRt,
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
                    {
                        **sincronizacion.contadores,
                        CLAVE_AVISOS: list(sincronizacion.avisos),
                    },
                    ensure_ascii=False,
                ),
                "propietario": reserva.propietario,
            },
        )
        if finalizados != 1:
            raise ReservaPerdidaError(_PERDIDA.format(reserva.id))


_PERDIDA = (
    "El intento {} ya no está en curso: su reserva venció y otra "
    "sincronización la tomó. No se aplicó nada."
)


def _utc(momento: datetime | None) -> datetime | None:
    """Siempre en UTC, sea cual sea la zona horaria de la sesion."""
    return momento.astimezone(timezone.utc) if momento is not None else None


def _exigir(
    reserva: ReservaSincronizacion | None,
    sincronizacion: SincronizacionProductosRt,
) -> None:
    """En la base, solo quien reservo finaliza: sin reserva no hay como."""
    if (
        reserva is None
        or reserva.id != sincronizacion.id
        or reserva.copia != COPIA
    ):
        raise PersistenciaError(
            "Para finalizar una sincronización hace falta su reserva."
        )


def _parametros(producto: ProductoRt, reserva: ReservaSincronizacion) -> dict:
    datos = {campo: getattr(producto, campo) for campo in CAMPOS}
    datos["identidad_anterior"] = (
        json.dumps(producto.identidad_anterior, ensure_ascii=False)
        if producto.identidad_anterior is not None
        else None
    )
    datos["sincronizacion_id"] = reserva.id
    datos["propietario"] = reserva.propietario
    return datos


def _producto(f) -> ProductoRt:
    datos = {campo: getattr(f, campo) for campo in CAMPOS}
    for campo in _FECHAS:
        datos[campo] = _utc(datos[campo])
    if datos["identidad_anterior"] is not None:
        datos["identidad_anterior"] = dict(datos["identidad_anterior"])
    return ProductoRt(**datos)


def _agrupar(filas) -> dict[str, list[CoincidenciaSugerida]]:
    resultado: dict[str, list[CoincidenciaSugerida]] = {}
    for f in filas:
        resultado.setdefault(f.producto_id, []).append(
            CoincidenciaSugerida(
                orden_id=f.codigo,
                criterios=[CriterioCoincidencia(c) for c in f.criterios],
                origen=f.origen,
                estado_workflow=f.estado_workflow,
                cerrada=bool(f.cerrada),
                creada_en=_utc(f.creada_en),
            )
        )
    return resultado


def _sincronizacion(f) -> SincronizacionProductosRt:
    contadores = dict(f.contadores or {})
    avisos = contadores.pop(CLAVE_AVISOS, []) or []
    return SincronizacionProductosRt(
        id=f.id,
        usuario_id=f.usuario,
        origen=f.origen,
        filtro=f.filtro,
        iniciada_en=_utc(f.iniciada_en),
        finalizada_en=_utc(f.finalizada_en),
        resultado=ResultadoSincronizacion(f.resultado),
        mensaje=f.mensaje,
        contadores={
            clave: int(valor)
            for clave, valor in contadores.items()
            if isinstance(valor, int | float) and not isinstance(valor, bool)
        },
        avisos=[str(aviso) for aviso in avisos],
    )
