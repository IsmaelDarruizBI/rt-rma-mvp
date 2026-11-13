"""Configuracion operativa sobre PostgreSQL: motivos y parametros, con su
auditoria en la misma transaccion (DEC-MI-13, 14 y 15)."""

from collections.abc import Sequence

from app.domain.models import CambioConfiguracion
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

    def _exigir_transaccion(self) -> None:
        if not self._unidad.en_curso():
            raise PersistenciaError(
                "Administrar la configuracion exige una transaccion en curso."
            )
