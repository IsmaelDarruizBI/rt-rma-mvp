"""Configuracion operativa sobre PostgreSQL: motivos y parametros, con su
auditoria en la misma transaccion (DEC-MI-13, 14 y 15)."""

from collections.abc import Sequence
from decimal import Decimal

from app.domain.models import CambioConfiguracion, Insumo
from app.domain.models.checklist import PreguntaChecklist, TipoEquipo
from app.domain.models.comunicaciones import PlantillaMensaje
from app.domain.models.operativa import MotivoOperativo, TipoMotivo
from app.repositories.exceptions import (
    CodigoExistenteError,
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
)

from .codigos import reservar_codigo
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
    ON CONFLICT DO NOTHING
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
    ON CONFLICT DO NOTHING
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
    INSERT INTO rma.insumo
        (clave, codigo, nombre, unidad, activo, control, precio)
    VALUES (%(clave)s, %(codigo)s, %(nombre)s, %(unidad)s, %(activo)s,
            %(control)s, %(precio)s)
    ON CONFLICT DO NOTHING
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_INSUMO = consulta(
    "operativa.actualizar_insumo",
    """
    UPDATE rma.insumo
       SET nombre = %(nombre)s, unidad = %(unidad)s, activo = %(activo)s,
           control = %(control)s, precio = %(precio)s
     WHERE clave = %(clave)s
    """,
    modo=ESCRITURA,
)

_RECARGO_MEDIO_PAGO = consulta(
    "operativa.recargo_medio_pago",
    """
    UPDATE rma.medio_pago SET recargo_porcentaje = %(porcentaje)s
     WHERE codigo = %(codigo)s
    """,
    modo=ESCRITURA,
)
_TIPOS_EQUIPO = consulta(
    "operativa.tipos_equipo",
    "SELECT codigo, nombre, activo, campo_origen, sincronizado_en "
    'FROM rma.tipo_equipo ORDER BY nombre, codigo COLLATE "C"',
    modo=LECTURA,
)
# DC12: copia del catalogo de Ventas. El identificador es el de Ventas;
# una sincronizacion actualiza lo que ya estaba y nunca borra.
_APLICAR_TIPO_EQUIPO = consulta(
    "operativa.aplicar_tipo_equipo",
    """
    INSERT INTO rma.tipo_equipo
        (codigo, nombre, activo, campo_origen, sincronizado_en)
    VALUES (%(codigo)s, %(nombre)s, %(activo)s, %(campo)s, %(fecha)s)
    ON CONFLICT (codigo) DO UPDATE
       SET nombre = excluded.nombre, activo = excluded.activo,
           campo_origen = excluded.campo_origen,
           sincronizado_en = excluded.sincronizado_en,
           modificado_en = now()
    """,
    modo=ESCRITURA,
)
_PREGUNTAS = consulta(
    "operativa.preguntas_checklist",
    """
    SELECT p.codigo, t.codigo AS tipo, p.texto, p.opciones, p.activa,
           p.orden
      FROM rma.checklist_pregunta p
      JOIN rma.tipo_equipo t ON t.id = p.tipo_equipo_id
     ORDER BY t.codigo, p.orden, p.codigo COLLATE "C"
    """,
    modo=LECTURA,
)
_INSERTAR_PREGUNTA = consulta(
    "operativa.insertar_pregunta",
    """
    INSERT INTO rma.checklist_pregunta
        (codigo, tipo_equipo_id, texto, opciones, activa, orden)
    SELECT %(codigo)s, t.id, %(texto)s, %(opciones)s, %(activa)s,
           %(orden)s
      FROM rma.tipo_equipo t WHERE t.codigo = %(tipo)s
    ON CONFLICT DO NOTHING
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_PREGUNTA = consulta(
    "operativa.actualizar_pregunta",
    """
    UPDATE rma.checklist_pregunta
       SET texto = %(texto)s, opciones = %(opciones)s, activa = %(activa)s,
           orden = %(orden)s, modificado_en = now()
     WHERE codigo = %(codigo)s
    """,
    modo=ESCRITURA,
)


class PostgresConfiguracionOperativa:
    editable = True

    def __init__(self, unidad: UnidadDeTrabajoPostgres) -> None:
        self._unidad = unidad
        self._auditoria = PostgresConfiguracionRepository(unidad)

    def reservar_codigo(self, prefijo: str) -> str:
        """CFG-01: el codigo siguiente libre del prefijo (CANC, INT, INS,
        CHK), generado por la base dentro de la transaccion del alta."""
        self._exigir_transaccion()
        return reservar_codigo(self._unidad, prefijo)

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
                raise CodigoExistenteError(
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
            "control": insumo.control.value,
            "precio": insumo.precio,
        }
        if nuevo:
            if ejecutor.ejecutar(_INSERTAR_INSUMO, parametros) != 1:
                raise CodigoExistenteError(
                    f"No se pudo dar de alta el insumo {insumo.id}: el "
                    "codigo o el identificador ya existe."
                )
        elif ejecutor.ejecutar(_ACTUALIZAR_INSUMO, parametros) != 1:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe el insumo {insumo.id}"
            )
        self._auditoria._auditar(ejecutor, cambios)

    def guardar_recargo_medio_pago(
        self, medio_id: str, porcentaje: Decimal, cambio: CambioConfiguracion
    ) -> None:
        self._exigir_transaccion()
        ejecutor = self._unidad.ejecutor()
        if (
            ejecutor.ejecutar(
                _RECARGO_MEDIO_PAGO,
                {"codigo": medio_id, "porcentaje": porcentaje},
            )
            != 1
        ):
            raise EntidadPersistidaNoEncontradaError(
                f"No existe el medio de pago {medio_id}"
            )
        self._auditoria._auditar(ejecutor, [cambio])

    def listar_tipos_equipo(self) -> list[TipoEquipo]:
        with self._unidad.lectura() as lector:
            filas = lector.filas(_TIPOS_EQUIPO)
        return [
            TipoEquipo(
                id=f.codigo,
                nombre=f.nombre,
                activo=f.activo,
                campo_origen=f.campo_origen,
                sincronizado_en=f.sincronizado_en,
            )
            for f in filas
        ]

    def aplicar_tipos_equipo(
        self,
        tipos: Sequence[TipoEquipo],
        cambios: Sequence[CambioConfiguracion],
    ) -> None:
        self._exigir_transaccion()
        ejecutor = self._unidad.ejecutor()
        for tipo in tipos:
            parametros = {
                "codigo": tipo.id,
                "nombre": tipo.nombre,
                "activo": tipo.activo,
                "campo": tipo.campo_origen,
                "fecha": tipo.sincronizado_en,
            }
            if ejecutor.ejecutar(_APLICAR_TIPO_EQUIPO, parametros) != 1:
                raise PersistenciaError(
                    f"No se pudo guardar el tipo de equipo {tipo.id}."
                )
        self._auditoria._auditar(ejecutor, cambios)

    def listar_preguntas_checklist(self) -> list[PreguntaChecklist]:
        with self._unidad.lectura() as lector:
            filas = lector.filas(_PREGUNTAS)
        return [
            PreguntaChecklist(
                id=f.codigo,
                tipo_equipo_id=f.tipo,
                texto=f.texto,
                opciones=list(f.opciones),
                activa=f.activa,
                orden=f.orden,
            )
            for f in filas
        ]

    def guardar_pregunta_checklist(
        self,
        pregunta: PreguntaChecklist,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None:
        self._exigir_transaccion()
        ejecutor = self._unidad.ejecutor()
        consulta_sql = _INSERTAR_PREGUNTA if nuevo else _ACTUALIZAR_PREGUNTA
        parametros = {
            "codigo": pregunta.id,
            "tipo": pregunta.tipo_equipo_id,
            "texto": pregunta.texto,
            "opciones": pregunta.opciones,
            "activa": pregunta.activa,
            "orden": pregunta.orden,
        }
        if ejecutor.ejecutar(consulta_sql, parametros) != 1:
            if nuevo:
                raise CodigoExistenteError(
                    f"No se pudo dar de alta la pregunta {pregunta.id}: el "
                    "codigo ya existe o el tipo de equipo no existe."
                )
            raise EntidadPersistidaNoEncontradaError(
                f"No existe la pregunta {pregunta.id}"
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
        if nuevo:
            if ejecutor.ejecutar(_INSERTAR_PLANTILLA, parametros) != 1:
                raise CodigoExistenteError(
                    f"Ya existe la plantilla {plantilla.codigo}."
                )
        elif ejecutor.ejecutar(_ACTUALIZAR_PLANTILLA, parametros) != 1:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe la plantilla {plantilla.codigo}"
            )
        self._auditoria._auditar(ejecutor, cambios)

    def _exigir_transaccion(self) -> None:
        if not self._unidad.en_curso():
            raise PersistenciaError(
                "Administrar la configuracion exige una transaccion en curso."
            )
