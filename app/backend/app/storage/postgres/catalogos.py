"""``CatalogosRepository`` sobre PostgreSQL (E3): solo las lecturas.

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

El stock (``actualizar_stock_insumo``, ``registrar_movimiento_stock`` y
``listar_movimientos_stock``) es de E5: aca lanza ``PersistenciaError``.
Todas las lecturas usan ``lectura()``: la transaccion del comando en
curso o una breve de solo lectura.
"""

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

from .consultas import LECTURA, consulta
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

    def actualizar_stock_insumo(
        self, insumo_id: str, nuevo_stock: Decimal
    ) -> Insumo:
        raise _stock_en_e5("actualizar_stock_insumo")

    # --- Movimientos operativos de stock (E5) ---

    def listar_movimientos_stock(self) -> list[MovimientoStock]:
        raise _stock_en_e5("listar_movimientos_stock")

    def registrar_movimiento_stock(
        self, movimiento: MovimientoStock
    ) -> Insumo:
        raise _stock_en_e5("registrar_movimiento_stock")

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


def _stock_en_e5(metodo: str) -> PersistenciaError:
    return PersistenciaError(
        f"{metodo} no esta disponible en PostgreSQL todavia: el stock y sus "
        "movimientos llegan en E5 (libro de inventario)."
    )
