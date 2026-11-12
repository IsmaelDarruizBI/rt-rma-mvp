"""``ConfiguracionRepository`` sobre PostgreSQL (DC23, DC23AUD).

El catalogo y su auditoria (``rma.cambio_configuracion``) se escriben en la
transaccion del comando: un cambio sin auditoria no queda.
"""

from collections.abc import Collection, Sequence
from datetime import timezone

from app.domain.models import (
    CambioConfiguracion,
    EntidadConfiguracion,
    TipoReparacion,
)
from app.repositories.exceptions import (
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
)

from .consultas import ESCRITURA, LECTURA, consulta
from .transaccion import UnidadDeTrabajoPostgres

_INSERTAR_TIPO = consulta(
    "configuracion.insertar_tipo",
    """
    INSERT INTO rma.tipo_reparacion
        (codigo, nombre, precio, puntaje, garantia_dias, activo)
    VALUES (%(codigo)s, %(nombre)s, %(precio)s, %(puntaje)s,
            %(garantia_dias)s, %(activo)s)
    ON CONFLICT (codigo) DO NOTHING
    RETURNING id
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_TIPO = consulta(
    "configuracion.actualizar_tipo",
    """
    UPDATE rma.tipo_reparacion
       SET nombre = %(nombre)s, precio = %(precio)s, puntaje = %(puntaje)s,
           garantia_dias = %(garantia_dias)s, activo = %(activo)s
     WHERE codigo = %(codigo)s
    """,
    modo=ESCRITURA,
)
_MESA = consulta(
    "configuracion.mesa",
    "SELECT id FROM rma.mesa_trabajo WHERE codigo = %(codigo)s FOR UPDATE",
    modo=ESCRITURA,
)
_QUITAR_TIPOS_DE_MESA = consulta(
    "configuracion.quitar_tipos_de_mesa",
    """
    DELETE FROM rma.mesa_tipo_reparacion mt
     USING rma.tipo_reparacion t
     WHERE mt.mesa_trabajo_id = %(mesa)s
       AND t.id = mt.tipo_reparacion_id
       AND NOT (t.codigo = ANY(%(tipos)s))
    """,
    modo=ESCRITURA,
)
_AGREGAR_TIPOS_A_MESA = consulta(
    "configuracion.agregar_tipos_a_mesa",
    """
    INSERT INTO rma.mesa_tipo_reparacion (mesa_trabajo_id, tipo_reparacion_id)
    SELECT %(mesa)s, t.id FROM rma.tipo_reparacion t
     WHERE t.codigo = ANY(%(tipos)s)
    ON CONFLICT DO NOTHING
    """,
    modo=ESCRITURA,
)
_INSERTAR_CAMBIO = consulta(
    "configuracion.insertar_cambio",
    """
    INSERT INTO rma.cambio_configuracion
        (entidad, clave, campo, valor_anterior, valor_nuevo, usuario_id,
         registrado_en)
    SELECT %(entidad)s, %(clave)s, %(campo)s, %(anterior)s, %(nuevo)s, u.id,
           %(fecha)s
      FROM rma.usuario u WHERE u.codigo = %(usuario)s
    """,
    modo=ESCRITURA,
)
_CAMBIOS = consulta(
    "configuracion.cambios",
    """
    SELECT c.entidad, c.clave, c.campo, c.valor_anterior, c.valor_nuevo,
           u.codigo AS usuario, c.registrado_en
      FROM rma.cambio_configuracion c
      JOIN rma.usuario u ON u.id = c.usuario_id
     WHERE (%(entidad)s::text IS NULL OR c.entidad = %(entidad)s)
       AND (%(clave)s::text IS NULL OR c.clave = %(clave)s)
     ORDER BY c.secuencia
    """,
    modo=LECTURA,
)


class PostgresConfiguracionRepository:
    def __init__(self, unidad: UnidadDeTrabajoPostgres) -> None:
        self._unidad = unidad

    def guardar_tipo_reparacion(
        self,
        tipo: TipoReparacion,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None:
        self._exigir_transaccion()
        ejecutor = self._unidad.ejecutor()
        parametros = {
            "codigo": tipo.id,
            "nombre": tipo.nombre,
            "precio": tipo.precio,
            "puntaje": tipo.puntaje,
            "garantia_dias": tipo.garantia_dias,
            "activo": tipo.activo,
        }
        if nuevo:
            if ejecutor.fila(_INSERTAR_TIPO, parametros) is None:
                raise PersistenciaError(
                    f"Ya existe un Tipo de Reparacion {tipo.id}."
                )
        elif ejecutor.ejecutar(_ACTUALIZAR_TIPO, parametros) != 1:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe el Tipo de Reparacion {tipo.id}"
            )
        self._auditar(ejecutor, cambios)

    def guardar_tipos_de_mesa(
        self,
        estacion_id: str,
        tipo_ids: Collection[str],
        cambio: CambioConfiguracion,
    ) -> None:
        self._exigir_transaccion()
        ejecutor = self._unidad.ejecutor()
        mesa = ejecutor.fila(_MESA, {"codigo": estacion_id})
        if mesa is None:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe la Mesa de trabajo {estacion_id}"
            )
        tipos = sorted(tipo_ids)
        ejecutor.ejecutar(
            _QUITAR_TIPOS_DE_MESA, {"mesa": mesa.id, "tipos": tipos}
        )
        ejecutor.ejecutar(
            _AGREGAR_TIPOS_A_MESA, {"mesa": mesa.id, "tipos": tipos}
        )
        self._auditar(ejecutor, [cambio])

    def listar_cambios(
        self,
        *,
        entidad: EntidadConfiguracion | None = None,
        clave: str | None = None,
    ) -> list[CambioConfiguracion]:
        with self._unidad.lectura() as lector:
            filas = lector.filas(
                _CAMBIOS,
                {
                    "entidad": entidad.value if entidad else None,
                    "clave": clave,
                },
            )
        return [
            CambioConfiguracion(
                entidad=f.entidad,
                clave=f.clave,
                campo=f.campo,
                valor_anterior=f.valor_anterior,
                valor_nuevo=f.valor_nuevo,
                usuario_id=f.usuario,
                fecha=f.registrado_en.astimezone(timezone.utc),
            )
            for f in filas
        ]

    def _auditar(
        self, ejecutor, cambios: Sequence[CambioConfiguracion]
    ) -> None:
        for cambio in cambios:
            insertadas = ejecutor.ejecutar(
                _INSERTAR_CAMBIO,
                {
                    "entidad": cambio.entidad.value,
                    "clave": cambio.clave,
                    "campo": cambio.campo,
                    "anterior": cambio.valor_anterior,
                    "nuevo": cambio.valor_nuevo,
                    "usuario": cambio.usuario_id,
                    "fecha": cambio.fecha,
                },
            )
            if insertadas != 1:
                raise PersistenciaError(
                    f"El usuario {cambio.usuario_id} no existe en la base."
                )

    def _exigir_transaccion(self) -> None:
        if not self._unidad.en_curso():
            raise PersistenciaError(
                "Administrar un catalogo exige una transaccion en curso."
            )
