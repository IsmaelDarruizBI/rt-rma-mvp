"""Configuracion operativa sobre PostgreSQL: motivos y parametros, con su
auditoria en la misma transaccion (DEC-MI-13, 14 y 15)."""

from collections.abc import Sequence

from app.domain.models import CambioConfiguracion, Insumo
from app.domain.models.comunicaciones import PlantillaMensaje
from app.domain.models.operativa import MotivoOperativo, TipoMotivo
from app.repositories.exceptions import (
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
)

from .configuracion import PostgresConfiguracionRepository
from .consultas import ESCRITURA, LECTURA, consulta
from .transaccion import UnidadDeTrabajoPostgres

_MOTIVOS = consulta(
    "operativa.motivos",
    """
    SELECT codigo, tipo, nombre, activo, requiere_descripcion
      FROM rma.motivo_operativo
     WHERE (%(tipo)s::text IS NULL OR tipo = %(tipo)s)
     ORDER BY tipo, orden, codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_INSERTAR_MOTIVO = consulta(
    "operativa.insertar_motivo",
    """
    INSERT INTO rma.motivo_operativo
        (codigo, tipo, nombre, activo, requiere_descripcion, orden)
    SELECT %(codigo)s, %(tipo)s, %(nombre)s, %(activo)s, %(requiere)s,
           coalesce(max(orden), 0) + 1
      FROM rma.motivo_operativo
    ON CONFLICT (codigo) DO NOTHING
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_MOTIVO = consulta(
    "operativa.actualizar_motivo",
    """
    UPDATE rma.motivo_operativo
       SET nombre = %(nombre)s, activo = %(activo)s,
           requiere_descripcion = %(requiere)s, modificado_en = now()
     WHERE codigo = %(codigo)s AND tipo = %(tipo)s
    """,
    modo=ESCRITURA,
)
_PARAMETROS = consulta(
    "operativa.parametros",
    "SELECT clave, valor FROM rma.parametro ORDER BY clave",
    modo=LECTURA,
)
_GUARDAR_PARAMETRO = consulta(
    "operativa.guardar_parametro",
    """
    UPDATE rma.parametro SET valor = %(valor)s, modificado_en = now()
     WHERE clave = %(clave)s
    """,
    modo=ESCRITURA,
)

_PLANTILLAS = consulta(
    "operativa.plantillas",
    """
    SELECT codigo, nombre, finalidad, texto, activa
      FROM rma.plantilla_mensaje
     ORDER BY orden, codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_INSERTAR_PLANTILLA = consulta(
    "operativa.insertar_plantilla",
    """
    INSERT INTO rma.plantilla_mensaje
        (codigo, nombre, finalidad, texto, activa, orden)
    SELECT %(codigo)s, %(nombre)s, %(finalidad)s, %(texto)s, %(activa)s,
           coalesce(max(orden), 0) + 1
      FROM rma.plantilla_mensaje
    ON CONFLICT (codigo) DO NOTHING
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_PLANTILLA = consulta(
    "operativa.actualizar_plantilla",
    """
    UPDATE rma.plantilla_mensaje
       SET nombre = %(nombre)s, finalidad = %(finalidad)s,
           texto = %(texto)s, activa = %(activa)s, modificado_en = now()
     WHERE codigo = %(codigo)s
    """,
    modo=ESCRITURA,
)

_INSERTAR_INSUMO = consulta(
    "operativa.insertar_insumo",
    """
    INSERT INTO rma.insumo (clave, codigo, nombre, unidad, activo)
    VALUES (%(clave)s, %(codigo)s, %(nombre)s, %(unidad)s, %(activo)s)
    ON CONFLICT DO NOTHING
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_INSUMO = consulta(
    "operativa.actualizar_insumo",
    """
    UPDATE rma.insumo
       SET nombre = %(nombre)s, unidad = %(unidad)s, activo = %(activo)s
     WHERE clave = %(clave)s
    """,
    modo=ESCRITURA,
)


class PostgresConfiguracionOperativa:
    editable = True

    def __init__(self, unidad: UnidadDeTrabajoPostgres) -> None:
        self._unidad = unidad
        self._auditoria = PostgresConfiguracionRepository(unidad)

    def listar_motivos(
        self, tipo: TipoMotivo | None = None
    ) -> list[MotivoOperativo]:
        with self._unidad.lectura() as lector:
            filas = lector.filas(
                _MOTIVOS, {"tipo": tipo.value if tipo else None}
            )
        return [
            MotivoOperativo(
                codigo=f.codigo,
                tipo=f.tipo,
                nombre=f.nombre,
                activo=f.activo,
                requiere_descripcion=f.requiere_descripcion,
            )
            for f in filas
        ]

    def guardar_motivo(
        self,
        motivo: MotivoOperativo,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None:
        self._exigir_transaccion()
        ejecutor = self._unidad.ejecutor()
        parametros = {
            "codigo": motivo.codigo,
            "tipo": motivo.tipo.value,
            "nombre": motivo.nombre,
            "activo": motivo.activo,
            "requiere": motivo.requiere_descripcion,
        }
        if nuevo:
            if ejecutor.ejecutar(_INSERTAR_MOTIVO, parametros) != 1:
                raise PersistenciaError(
                    f"Ya existe el motivo {motivo.codigo}."
                )
        elif ejecutor.ejecutar(_ACTUALIZAR_MOTIVO, parametros) != 1:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe el motivo {motivo.codigo}"
            )
        self._auditoria._auditar(ejecutor, cambios)

    def parametros(self) -> dict[str, str]:
        with self._unidad.lectura() as lector:
            return {f.clave: f.valor for f in lector.filas(_PARAMETROS)}

    def guardar_parametro(
        self, clave: str, valor: str, cambio: CambioConfiguracion
    ) -> None:
        self._exigir_transaccion()
        ejecutor = self._unidad.ejecutor()
        if (
            ejecutor.ejecutar(
                _GUARDAR_PARAMETRO, {"clave": clave, "valor": valor}
            )
            != 1
        ):
            raise EntidadPersistidaNoEncontradaError(
                f"No existe el parametro {clave}"
            )
        self._auditoria._auditar(ejecutor, [cambio])

    def guardar_insumo(
        self,
        insumo: Insumo,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None:
        self._exigir_transaccion()
        ejecutor = self._unidad.ejecutor()
        parametros = {
            "clave": insumo.id,
            "codigo": insumo.codigo,
            "nombre": insumo.nombre,
            "unidad": insumo.unidad,
            "activo": insumo.activo,
        }
        consulta_sql = _INSERTAR_INSUMO if nuevo else _ACTUALIZAR_INSUMO
        if ejecutor.ejecutar(consulta_sql, parametros) != 1:
            raise PersistenciaError(
                f"No se pudo guardar el insumo {insumo.id}: el codigo o "
                "el identificador ya existe."
            )
        self._auditoria._auditar(ejecutor, cambios)

    def listar_plantillas(self) -> list[PlantillaMensaje]:
        with self._unidad.lectura() as lector:
            filas = lector.filas(_PLANTILLAS)
        return [
            PlantillaMensaje(
                codigo=f.codigo,
                nombre=f.nombre,
                finalidad=f.finalidad,
                texto=f.texto,
                activa=f.activa,
            )
            for f in filas
        ]

    def guardar_plantilla(
        self,
        plantilla: PlantillaMensaje,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None:
        self._exigir_transaccion()
        ejecutor = self._unidad.ejecutor()
        parametros = {
            "codigo": plantilla.codigo,
            "nombre": plantilla.nombre,
            "finalidad": plantilla.finalidad.value,
            "texto": plantilla.texto,
            "activa": plantilla.activa,
        }
        consulta_sql = _INSERTAR_PLANTILLA if nuevo else _ACTUALIZAR_PLANTILLA
        if ejecutor.ejecutar(consulta_sql, parametros) != 1:
            raise EntidadPersistidaNoEncontradaError(
                f"No se pudo guardar la plantilla {plantilla.codigo}"
            )
        self._auditoria._auditar(ejecutor, cambios)

    def _exigir_transaccion(self) -> None:
        if not self._unidad.en_curso():
            raise PersistenciaError(
                "Administrar la configuracion exige una transaccion en curso."
            )
