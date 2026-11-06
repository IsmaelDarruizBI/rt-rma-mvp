"""``CatalogosRepository`` sobre PostgreSQL (E3, y el stock en E5).

Mismo contrato y mismos resultados que ``JsonCatalogosRepository``
(``docs/postgresql/e3-catalogos-diseno.md``, seccion 4):

- El ``id`` del dominio es la columna ``codigo``; el del insumo, la
  columna ``clave`` (DE3-1). El uuid tecnico no sale de aca.
- Orden explicito: por codigo, salvo usuarios y medios de pago, que
  conservan el orden de su catalogo de origen (columna ``orden``, DE3-2).
- Numeros sin ceros de mas (DE3-3): ``80000.00`` de la base es ``80000``,
  como en JSON.
- ``TR-OTROS`` es una fila tecnica (la necesita la clave foranea de los
  Detalles): no forma parte del catalogo, igual que en JSON.
- Medios de pago y empresa: sin filas, los predeterminados (DE3-7).
- Un usuario tiene exactamente un rol (DE3-6): el MVP no admite varios.

Stock (E5, A7). El libro ``rma.movimiento_inventario`` es la fuente de
verdad (DI-1): su trigger aplica cada movimiento al insumo.

- ``registrar_movimiento_stock`` inserta el ingreso o ajuste en el libro y
  verifica que el trigger llego a los mismos saldos que calculo el service.
- ``actualizar_stock_insumo`` no escribe: registra el stock que el service
  espera, y ``guardar`` de la Orden lo verifica despues de insertar los
  movimientos (``verificar_stock_esperado``). Una diferencia es un error
  explicito, nunca un saldo distinto en silencio.
- ``listar_movimientos_stock``: los ingresos y ajustes registrados por un
  usuario. Un saldo inicial cargado por el sistema (sin usuario) no es un
  movimiento del dominio, como en JSON, donde vive en el catalogo.
- El motivo de un ajuste es el texto libre (DI-8).

Todas las lecturas usan ``lectura()``: la transaccion del comando en
curso o una breve de solo lectura.
"""

from datetime import timezone
from decimal import Decimal

from app.domain.models import (
    DATOS_EMPRESA_PREDETERMINADOS,
    MEDIOS_PAGO_PREDETERMINADOS,
    TIPO_REPARACION_OTROS,
    DatosEmpresa,
    EstacionTrabajo,
    Insumo,
    MedioPago,
    MovimientoStock,
    RolUsuario,
    TipoReparacion,
    TipoReparacionEstacion,
    TipoReparacionInsumos,
    Usuario,
)
from app.repositories.exceptions import (
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
)

from .acciones import accion_del_comando
from .consultas import ESCRITURA, LECTURA, consulta
from .ejecutor import EjecutorSql
from .mapeo import decimal_sin_ceros
from .transaccion import UnidadDeTrabajoPostgres

_TIPOS = consulta(
    "catalogos.tipos_reparacion",
    """
    SELECT codigo, nombre, precio, puntaje, garantia_dias, activo
    FROM rma.tipo_reparacion
    WHERE codigo <> %(otros)s
    ORDER BY codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_TIPO = consulta(
    "catalogos.tipo_reparacion",
    """
    SELECT codigo, nombre, precio, puntaje, garantia_dias, activo
    FROM rma.tipo_reparacion
    WHERE codigo = %(codigo)s AND codigo <> %(otros)s
    """,
    modo=LECTURA,
)
_INSUMOS = consulta(
    "catalogos.insumos",
    """
    SELECT clave, codigo, nombre, unidad, stock_fisico, activo
    FROM rma.insumo
    ORDER BY clave COLLATE "C"
    """,
    modo=LECTURA,
)
_INSUMO = consulta(
    "catalogos.insumo",
    """
    SELECT clave, codigo, nombre, unidad, stock_fisico, activo
    FROM rma.insumo
    WHERE clave = %(clave)s
    """,
    modo=LECTURA,
)
_PREVISTOS = consulta(
    "catalogos.tipo_reparacion_insumos",
    """
    SELECT t.codigo AS tipo, i.clave AS insumo, ti.cantidad
    FROM rma.tipo_reparacion_insumo ti
    JOIN rma.tipo_reparacion t ON t.id = ti.tipo_reparacion_id
    JOIN rma.insumo i ON i.id = ti.insumo_id
    ORDER BY t.codigo COLLATE "C", i.clave COLLATE "C"
    """,
    modo=LECTURA,
)
_ESTACIONES = consulta(
    "catalogos.estaciones",
    """
    SELECT codigo, nombre, activa
    FROM rma.mesa_trabajo
    ORDER BY codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_ESTACION = consulta(
    "catalogos.estacion",
    """
    SELECT codigo, nombre, activa
    FROM rma.mesa_trabajo
    WHERE codigo = %(codigo)s
    """,
    modo=LECTURA,
)
_COMPATIBLES = consulta(
    "catalogos.tipo_reparacion_estaciones",
    """
    SELECT t.codigo AS tipo, m.codigo AS estacion
    FROM rma.mesa_tipo_reparacion mt
    JOIN rma.tipo_reparacion t ON t.id = mt.tipo_reparacion_id
    JOIN rma.mesa_trabajo m ON m.id = mt.mesa_trabajo_id
    ORDER BY t.codigo COLLATE "C", m.codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_COLUMNAS_USUARIO = """
    SELECT u.codigo, u.nombre, u.activo,
           coalesce(
               array_agg(r.codigo ORDER BY r.codigo)
                   FILTER (WHERE r.codigo IS NOT NULL),
               '{}'
           ) AS roles
    FROM rma.usuario u
    LEFT JOIN rma.usuario_rol ur ON ur.usuario_id = u.id
    LEFT JOIN rma.rol r ON r.id = ur.rol_id
"""
_USUARIOS = consulta(
    "catalogos.usuarios",
    _COLUMNAS_USUARIO
    + """
    GROUP BY u.id
    ORDER BY u.orden, u.codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_USUARIO = consulta(
    "catalogos.usuario",
    _COLUMNAS_USUARIO
    + """
    WHERE u.codigo = %(codigo)s
    GROUP BY u.id
    """,
    modo=LECTURA,
)
_MEDIOS = consulta(
    "catalogos.medios_pago",
    """
    SELECT codigo, nombre, activo, admite_devolucion
    FROM rma.medio_pago
    ORDER BY orden, codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_EMPRESA = consulta(
    "catalogos.empresa",
    """
    SELECT nombre, razon_social, cuit, direccion, telefono, email,
           condiciones_garantia
    FROM rma.empresa
    """,
    modo=LECTURA,
)


# DI-2 y QA-A2-M4: por ``clave`` ascendente, siempre en el mismo orden, asi
# dos comandos que toman los mismos insumos no se esperan en circulo. FOR NO
# KEY UPDATE: choca consigo mismo y con el trigger del libro, no con el KEY
# SHARE de las claves foraneas que referencian el insumo.
_BLOQUEAR_INSUMOS = consulta(
    "catalogos.bloquear_insumos",
    """
    SELECT clave FROM rma.insumo
    WHERE clave = ANY(%(claves)s)
    ORDER BY clave COLLATE "C"
    FOR NO KEY UPDATE
    """,
    modo=ESCRITURA,
)


def bloquear_insumos(ejecutor: EjecutorSql, claves) -> None:
    """Bloquea esos insumos por ``clave``, en orden (DI-2)."""
    if claves:
        ejecutor.filas(_BLOQUEAR_INSUMOS, {"claves": sorted(set(claves))})


# DI-1: stock que el service espera, por insumo, en la transaccion en curso.
_STOCK_ESPERADO = "inventario.stock_esperado"
_STOCK_DE = consulta(
    "catalogos.stock_de",
    "SELECT clave, stock_fisico FROM rma.insumo WHERE clave = ANY(%(claves)s)",
    modo=ESCRITURA,
)


def verificar_stock_esperado(
    unidad: UnidadDeTrabajoPostgres, ejecutor: EjecutorSql
) -> None:
    """Compara el stock que espera el service con el que dejo el libro.

    Lo llama ``guardar`` de la Orden despues de insertar sus movimientos.
    Lo verificado se descarta; una diferencia es ``PersistenciaError`` y
    el comando se revierte.
    """
    esperado: dict[str, Decimal] = unidad.datos_de_transaccion().pop(
        _STOCK_ESPERADO, {}
    )
    if not esperado:
        return
    reales = {
        f.clave: f.stock_fisico
        for f in ejecutor.filas(_STOCK_DE, {"claves": sorted(esperado)})
    }
    distintos = sorted(
        f"{clave}: esperado {valor}, libro {reales.get(clave)}"
        for clave, valor in esperado.items()
        if reales.get(clave) != valor
    )
    if distintos:
        raise PersistenciaError(
            "El stock del libro no coincide con el que calculo el service "
            f"(DI-1): {'; '.join(distintos)}."
        )


_MOVIMIENTOS_STOCK = consulta(
    "catalogos.movimientos_stock",
    """
    SELECT m.codigo, m.tipo, i.clave AS insumo, m.cantidad,
           m.stock_fisico_anterior, m.stock_fisico_resultante,
           m.stock_reservado_resultante, u.codigo AS usuario,
           m.registrado_en, m.motivo_texto, m.referencia, m.operacion_id
    FROM rma.movimiento_inventario m
    JOIN rma.insumo i ON i.id = m.insumo_id
    JOIN rma.usuario u ON u.id = m.usuario_id
    WHERE m.orden_id IS NULL
      AND m.tipo IN ('INGRESO', 'AJUSTE_POSITIVO', 'AJUSTE_NEGATIVO')
    ORDER BY m.secuencia NULLS FIRST, m.registrado_en, m.codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_INSERTAR_MOVIMIENTO_STOCK = consulta(
    "catalogos.insertar_movimiento_stock",
    """
    INSERT INTO rma.movimiento_inventario
        (codigo, tipo, insumo_id, cantidad, motivo_texto, referencia,
         operacion_id, usuario_id, accion_id, registrado_en)
    SELECT %(codigo)s, %(tipo)s, i.id, %(cantidad)s, %(motivo)s,
           %(referencia)s, %(operacion)s, u.id, %(accion)s, %(fecha)s
    FROM rma.insumo i, rma.usuario u
    WHERE i.clave = %(insumo)s AND u.codigo = %(usuario)s
    RETURNING stock_fisico_anterior, stock_fisico_resultante,
              stock_reservado_resultante
    """,
    modo=ESCRITURA,
)
_USUARIO_ID = consulta(
    "catalogos.usuario_id",
    "SELECT id FROM rma.usuario WHERE codigo = %(codigo)s",
    modo=ESCRITURA,
)


class PostgresCatalogosRepository:
    """Implementa las lecturas de ``CatalogosRepository`` sobre la base."""

    def __init__(self, unidad: UnidadDeTrabajoPostgres) -> None:
        self._unidad = unidad

    # --- Tipos de Reparacion ---

    def listar_tipos_reparacion(self) -> list[TipoReparacion]:
        return [
            _tipo(f)
            for f in self._filas(_TIPOS, {"otros": TIPO_REPARACION_OTROS})
        ]

    def obtener_tipo_reparacion(self, tipo_id: str) -> TipoReparacion:
        fila = self._fila(
            _TIPO, {"codigo": tipo_id, "otros": TIPO_REPARACION_OTROS}
        )
        return _tipo(_existente(fila, "Tipo de Reparacion", tipo_id))

    # --- Insumos ---

    def listar_insumos(self) -> list[Insumo]:
        return [_insumo(f) for f in self._filas(_INSUMOS)]

    def obtener_insumo(self, insumo_id: str) -> Insumo:
        fila = self._fila(_INSUMO, {"clave": insumo_id})
        return _insumo(_existente(fila, "Insumo", insumo_id))

    def bloquear_insumos(self, insumo_ids) -> None:
        self._exigir_transaccion("Bloquear insumos")
        bloquear_insumos(self._unidad.ejecutor(), insumo_ids)

    def actualizar_stock_insumo(
        self, insumo_id: str, nuevo_stock: Decimal
    ) -> Insumo:
        """No escribe (DI-1): el stock lo mueve el libro. Registra el que
        espera el service; ``guardar`` de la Orden lo verifica."""
        self._exigir_transaccion("Actualizar el stock de un insumo")
        insumo = self.obtener_insumo(insumo_id)
        self._unidad.datos_de_transaccion().setdefault(_STOCK_ESPERADO, {})[
            insumo_id
        ] = nuevo_stock
        return insumo.model_copy(update={"stock_fisico": nuevo_stock})

    # --- Movimientos operativos de stock (E5) ---

    def listar_movimientos_stock(self) -> list[MovimientoStock]:
        return [_movimiento_stock(f) for f in self._filas(_MOVIMIENTOS_STOCK)]

    def registrar_movimiento_stock(
        self, movimiento: MovimientoStock
    ) -> Insumo:
        """Inserta el ingreso o ajuste en el libro, despues de bloquear el
        insumo, y verifica los saldos del trigger contra los del service
        (DI-1). El motivo es el texto libre (DI-8)."""
        self._exigir_transaccion("Registrar un movimiento de stock")
        ejecutor = self._unidad.ejecutor()
        bloquear_insumos(ejecutor, [movimiento.insumo_id])
        usuario = ejecutor.fila(_USUARIO_ID, {"codigo": movimiento.usuario_id})
        if usuario is None:
            raise PersistenciaError(
                f"El usuario {movimiento.usuario_id} no existe en la base."
            )
        fila = ejecutor.fila(
            _INSERTAR_MOVIMIENTO_STOCK,
            {
                "codigo": movimiento.id,
                "tipo": movimiento.tipo.value,
                "insumo": movimiento.insumo_id,
                "cantidad": movimiento.cantidad,
                "motivo": movimiento.motivo,
                "referencia": movimiento.referencia,
                "operacion": movimiento.operacion_id,
                "usuario": movimiento.usuario_id,
                "accion": accion_del_comando(
                    self._unidad,
                    ejecutor,
                    operacion=f"REGISTRAR_{movimiento.tipo.value}",
                    usuario=usuario.id,
                    orden=None,
                ),
                "fecha": movimiento.fecha,
            },
        )
        if fila is None:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe el Insumo {movimiento.insumo_id}"
            )
        libro = (
            fila.stock_fisico_anterior,
            fila.stock_fisico_resultante,
            fila.stock_reservado_resultante,
        )
        dominio = (
            movimiento.stock_anterior,
            movimiento.stock_resultante,
            movimiento.reservado,
        )
        if libro != dominio:
            raise PersistenciaError(
                f"El movimiento {movimiento.id} deja en el libro (fisico "
                f"anterior, resultante, reservado) {libro} y el service "
                f"calculo {dominio} (DI-1)."
            )
        return self.obtener_insumo(movimiento.insumo_id)

    # --- Insumos previstos por Tipo de Reparacion ---

    def listar_tipo_reparacion_insumos(self) -> list[TipoReparacionInsumos]:
        return [
            TipoReparacionInsumos(
                tipo_reparacion_id=f.tipo,
                insumo_id=f.insumo,
                cantidad=decimal_sin_ceros(f.cantidad),
            )
            for f in self._filas(_PREVISTOS)
        ]

    # --- Estaciones de trabajo ---

    def listar_estaciones(self) -> list[EstacionTrabajo]:
        return [_estacion(f) for f in self._filas(_ESTACIONES)]

    def obtener_estacion(self, estacion_id: str) -> EstacionTrabajo:
        fila = self._fila(_ESTACION, {"codigo": estacion_id})
        return _estacion(_existente(fila, "Estacion de Trabajo", estacion_id))

    def listar_tipo_reparacion_estaciones(
        self,
    ) -> list[TipoReparacionEstacion]:
        return [
            TipoReparacionEstacion(
                tipo_reparacion_id=f.tipo, estacion_id=f.estacion
            )
            for f in self._filas(_COMPATIBLES)
        ]

    # --- Usuarios ---

    def listar_usuarios(self) -> list[Usuario]:
        return [_usuario(f) for f in self._filas(_USUARIOS)]

    def obtener_usuario(self, usuario_id: str) -> Usuario:
        fila = self._fila(_USUARIO, {"codigo": usuario_id})
        return _usuario(_existente(fila, "Usuario", usuario_id))

    # --- Medios de pago ---

    def listar_medios_pago(self) -> list[MedioPago]:
        filas = self._filas(_MEDIOS)
        if not filas:
            return list(MEDIOS_PAGO_PREDETERMINADOS)
        return [
            MedioPago(
                id=f.codigo,
                nombre=f.nombre,
                activo=f.activo,
                admite_devolucion=f.admite_devolucion,
            )
            for f in filas
        ]

    def obtener_medio_pago(self, medio_id: str) -> MedioPago:
        # Como en JSON: entre los configurados o, sin ninguno, los
        # predeterminados.
        for medio in self.listar_medios_pago():
            if medio.id == medio_id:
                return medio
        raise EntidadPersistidaNoEncontradaError(
            f"No existe el Medio de pago {medio_id}"
        )

    # --- Identificacion de la empresa en los documentos ---

    def obtener_datos_empresa(self) -> DatosEmpresa:
        fila = self._fila(_EMPRESA)
        if fila is None:
            return DATOS_EMPRESA_PREDETERMINADOS.model_copy()
        return DatosEmpresa(**fila._asdict())

    # --- Interno ---

    def _exigir_transaccion(self, operacion: str) -> None:
        if not self._unidad.en_curso():
            raise PersistenciaError(
                f"{operacion} exige una transaccion en curso: el caso de "
                "uso debe abrirla con contexto.transaccion()."
            )

    def _filas(self, consulta_, parametros=()) -> list:
        with self._unidad.lectura() as lector:
            return lector.filas(consulta_, parametros)

    def _fila(self, consulta_, parametros=()):
        with self._unidad.lectura() as lector:
            return lector.fila(consulta_, parametros)


def _existente(fila, etiqueta: str, entidad_id: str):
    if fila is None:
        raise EntidadPersistidaNoEncontradaError(
            f"No existe el {etiqueta} {entidad_id}"
        )
    return fila


def _tipo(f) -> TipoReparacion:
    return TipoReparacion(
        id=f.codigo,
        nombre=f.nombre,
        precio=decimal_sin_ceros(f.precio),
        puntaje=f.puntaje,
        garantia_dias=f.garantia_dias,
        activo=f.activo,
    )


def _insumo(f) -> Insumo:
    return Insumo(
        id=f.clave,
        codigo=f.codigo,
        nombre=f.nombre,
        unidad=f.unidad,
        stock_fisico=decimal_sin_ceros(f.stock_fisico),
        activo=f.activo,
    )


def _estacion(f) -> EstacionTrabajo:
    return EstacionTrabajo(id=f.codigo, nombre=f.nombre, activa=f.activa)


def _usuario(f) -> Usuario:
    if len(f.roles) != 1:
        raise PersistenciaError(
            f"El usuario {f.codigo} tiene {len(f.roles)} roles: el MVP "
            "admite exactamente uno (varios roles por usuario, DC27A, no "
            "esta implementado)."
        )
    return Usuario(
        id=f.codigo,
        nombre=f.nombre,
        rol=RolUsuario(f.roles[0]),
        activo=f.activo,
    )


def _movimiento_stock(f) -> MovimientoStock:
    return MovimientoStock(
        id=f.codigo,
        tipo=f.tipo,
        insumo_id=f.insumo,
        cantidad=decimal_sin_ceros(f.cantidad),
        stock_anterior=decimal_sin_ceros(f.stock_fisico_anterior),
        stock_resultante=decimal_sin_ceros(f.stock_fisico_resultante),
        reservado=decimal_sin_ceros(f.stock_reservado_resultante),
        disponible_resultante=decimal_sin_ceros(
            f.stock_fisico_resultante - f.stock_reservado_resultante
        ),
        usuario_id=f.usuario,
        fecha=f.registrado_en.astimezone(timezone.utc),
        motivo=f.motivo_texto,
        referencia=f.referencia,
        operacion_id=f.operacion_id,
    )
