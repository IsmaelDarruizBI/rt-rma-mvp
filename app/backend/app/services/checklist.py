"""Reglas del checklist de recepcion y de la advertencia por informacion
faltante (DC12; BR-REP-024/025/040)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.domain.models import (
    CambioConfiguracion,
    EntidadConfiguracion,
    EstadoWorkflow,
    OrdenReparacion,
    ProductoInformado,
    Usuario,
)
from app.domain.models.checklist import (
    ConfirmacionInformacionFaltante,
    PreguntaChecklist,
    RegistroChecklist,
    RespuestaChecklist,
    TipoEquipo,
)

from . import permisos
from .autorizacion import validar_alguno_de
from .configuracion import texto
from .exceptions import PrecondicionInvalidaError

CAMPOS_TIPO = ("nombre", "activo", "campo_origen")
CAMPOS_PREGUNTA = ("tipo_equipo_id", "texto", "opciones", "activa", "orden")

# Columnas de Ventas que pueden ser el Tipo de Equipo, y el dato del
# producto informado que les corresponde. Cual rige lo decide negocio
# (``RMA_TIPO_EQUIPO_CAMPO``); el codigo no elige ninguna.
CAMPOS_TIPO_EQUIPO = {
    "tp_categoria": "categoria",
    "tp_subcat_1": "subcategoria",
    "tp_gp": "grupo",
}


def _valor(objeto, campo):
    valor = getattr(objeto, campo)
    return " | ".join(valor) if isinstance(valor, list) else texto(valor)


def _cambios(entidad_clave, campos, anterior, nuevo, usuario, fecha):
    validar_alguno_de(usuario, permisos.CONFIGURACION_ADMINISTRAR)
    cambios = [
        CambioConfiguracion(
            entidad=EntidadConfiguracion.CHECKLIST,
            clave=entidad_clave,
            campo=campo,
            valor_anterior=_valor(anterior, campo) if anterior else None,
            valor_nuevo=_valor(nuevo, campo),
            usuario_id=usuario.id,
            fecha=fecha,
        )
        for campo in campos
        if anterior is None or _valor(anterior, campo) != _valor(nuevo, campo)
    ]
    if not cambios:
        raise PrecondicionInvalidaError(
            f"{entidad_clave} ya tiene esos valores: no hay cambios."
        )
    return cambios


def tipos_informados(
    productos: Sequence[ProductoInformado], campo: str
) -> list[str]:
    """Los Tipos de Equipo que informa el catalogo de Ventas en ``campo``:
    sus valores distintos, tal cual (sin espacios al borde), de los
    productos que son equipos (no generadores) y no estan eliminados.

    Rechaza (``PrecondicionInvalidaError``) un campo desconocido, una
    lectura sin ningun tipo (nunca se da de baja todo por una respuesta
    vacia) y dos valores que solo difieren en mayusculas (no se puede
    saber si son el mismo tipo).
    """
    atributo = CAMPOS_TIPO_EQUIPO.get(campo)
    if atributo is None:
        raise PrecondicionInvalidaError(
            f"{campo} no es una columna del catalogo de Ventas que pueda "
            "dar el tipo de equipo."
        )
    valores: dict[str, str] = {}
    for producto in productos:
        if producto.generador or producto.eliminado:
            continue
        valor = (getattr(producto, atributo) or "").strip()
        if not valor:
            continue
        previo = valores.setdefault(valor.casefold(), valor)
        if previo != valor:
            raise PrecondicionInvalidaError(
                f"El catalogo de Ventas tiene «{previo}» y «{valor}» en "
                f"{campo}: no se puede saber si son el mismo tipo de equipo."
            )
    if not valores:
        raise PrecondicionInvalidaError(
            f"El catalogo de Ventas no informo ningun valor en {campo}: "
            "los tipos de equipo no cambian."
        )
    return sorted(valores.values())


@dataclass(frozen=True)
class FusionTiposEquipo:
    """Resultado de copiar los tipos de Ventas sobre los que tenia RMA."""

    tipos: list[TipoEquipo]
    cambios: list[CambioConfiguracion]
    nuevos: int
    reactivados: int
    dados_de_baja: int
    sin_cambios: int


def fusionar_tipos_equipo(
    existentes: Sequence[TipoEquipo],
    informados: Sequence[str],
    *,
    campo: str,
    usuario: Usuario,
    fecha: datetime,
) -> FusionTiposEquipo:
    """Los tipos a guardar y su auditoria. Los informados quedan vigentes
    (nuevos o reactivados) con la fecha de esta sincronizacion; los que
    ya no vienen, o venian de otra columna, quedan no vigentes. Nada se
    borra: las preguntas y los checklists siguen referenciandolos."""
    validar_alguno_de(usuario, permisos.CONFIGURACION_ADMINISTRAR)
    anteriores = {tipo.id: tipo for tipo in existentes}
    vigentes = set(informados)
    tipos: list[TipoEquipo] = []
    cambios: list[CambioConfiguracion] = []
    nuevos = reactivados = bajas = iguales = 0

    def auditar(anterior: TipoEquipo | None, nuevo: TipoEquipo) -> bool:
        propios = [
            CambioConfiguracion(
                entidad=EntidadConfiguracion.CHECKLIST,
                clave=nuevo.id,
                campo=c,
                valor_anterior=_valor(anterior, c) if anterior else None,
                valor_nuevo=_valor(nuevo, c),
                usuario_id=usuario.id,
                fecha=fecha,
            )
            for c in CAMPOS_TIPO
            if anterior is None or _valor(anterior, c) != _valor(nuevo, c)
        ]
        cambios.extend(propios)
        return bool(propios)

    for valor in informados:
        anterior = anteriores.get(valor)
        tipo = TipoEquipo(
            id=valor,
            nombre=valor,
            activo=True,
            campo_origen=campo,
            sincronizado_en=fecha,
        )
        cambio = auditar(anterior, tipo)
        if anterior is None:
            nuevos += 1
        elif not anterior.activo:
            reactivados += 1
        elif not cambio:
            iguales += 1
        tipos.append(tipo)
    for anterior in existentes:
        if anterior.id in vigentes or not anterior.activo:
            continue
        baja = anterior.model_copy(update={"activo": False})
        auditar(anterior, baja)
        bajas += 1
        tipos.append(baja)
    return FusionTiposEquipo(
        tipos=tipos,
        cambios=cambios,
        nuevos=nuevos,
        reactivados=reactivados,
        dados_de_baja=bajas,
        sin_cambios=iguales,
    )


def cambios_de_pregunta(
    anterior: PreguntaChecklist | None,
    nueva: PreguntaChecklist,
    *,
    usuario: Usuario,
    fecha: datetime,
) -> list[CambioConfiguracion]:
    if (
        anterior is not None
        and anterior.tipo_equipo_id != nueva.tipo_equipo_id
    ):
        raise PrecondicionInvalidaError(
            "Una pregunta no cambia de tipo de equipo: da de alta otra."
        )
    return _cambios(
        f"{nueva.tipo_equipo_id}/{nueva.id}",
        CAMPOS_PREGUNTA,
        anterior,
        nueva,
        usuario,
        fecha,
    )


def registrar_checklist(
    orden: OrdenReparacion,
    *,
    tipo: TipoEquipo,
    preguntas: Sequence[PreguntaChecklist],
    respuestas: Sequence[tuple[str, str | None, bool]],
    motivo: str | None,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """``respuestas``: (pregunta, opcion o None, no realizada). Todas son
    opcionales. Una correccion (ya habia un checklist) exige motivo y
    agrega una version: la anterior no se modifica."""
    validar_alguno_de(usuario, permisos.CHECKLIST_REGISTRAR)
    if not tipo.activo:
        raise PrecondicionInvalidaError(
            f"El tipo de equipo {tipo.nombre} no esta vigente."
        )
    motivo = (motivo or "").strip() or None
    if orden.checklists_recepcion and motivo is None:
        raise PrecondicionInvalidaError(
            "La Orden ya tiene un checklist: corregirlo exige un motivo."
        )
    vigentes = {
        p.id: p for p in preguntas if p.tipo_equipo_id == tipo.id and p.activa
    }
    registradas: list[RespuestaChecklist] = []
    vistas: set[str] = set()
    for pregunta_id, respuesta, no_realizada in respuestas:
        pregunta = vigentes.get(pregunta_id)
        if pregunta is None:
            raise PrecondicionInvalidaError(
                f"{pregunta_id} no es una pregunta vigente de {tipo.nombre}."
            )
        if pregunta_id in vistas:
            raise PrecondicionInvalidaError(
                f"{pregunta_id} esta respondida dos veces."
            )
        vistas.add(pregunta_id)
        try:
            registradas.append(
                RespuestaChecklist(
                    pregunta_id=pregunta.id,
                    texto=pregunta.texto,
                    opciones=list(pregunta.opciones),
                    respuesta=None if no_realizada else respuesta,
                    no_realizada=no_realizada,
                )
            )
        except ValueError as error:
            raise PrecondicionInvalidaError(str(error)) from error
    nueva = orden.model_copy(deep=True)
    nueva.checklists_recepcion.append(
        RegistroChecklist(
            tipo_equipo_id=tipo.id,
            tipo_equipo_nombre=tipo.nombre,
            respuestas=registradas,
            sin_registrar=[
                p.texto
                for p in sorted(vigentes.values(), key=lambda p: p.orden)
                if p.id not in vistas
            ],
            usuario_id=usuario.id,
            fecha=fecha,
            motivo=motivo,
        )
    )
    nueva.updated_at = fecha
    return nueva


def informacion_faltante(
    orden: OrdenReparacion, *, checklist_disponible: bool = True
) -> list[str]:
    """Lo que falta registrar al pasar de la recepcion a definir los
    trabajos (BR-REP-025). Solo en REQUERIMIENTO; nunca bloquea.

    ``checklist_disponible`` en falso (no hay ningun tipo de equipo
    vigente: el catalogo de Ventas no esta definido o no se sincronizo):
    no se pide un checklist que no se puede completar."""
    if orden.estado_workflow is not EstadoWorkflow.REQUERIMIENTO:
        return []
    faltantes = []
    if not orden.fotos:
        faltantes.append("Fotografias")
    datos = orden.recepcion.datos if orden.recepcion else None
    if datos is None or not (datos.observaciones or "").strip():
        faltantes.append("Observaciones del equipo")
    if not orden.checklists_recepcion:
        if checklist_disponible:
            faltantes.append("Checklist de recepcion")
    elif orden.checklists_recepcion[-1].sin_registrar:
        cantidad = len(orden.checklists_recepcion[-1].sin_registrar)
        faltantes.append(
            f"Verificaciones del checklist sin registrar ({cantidad})"
        )
    return faltantes


def advertencia_pendiente(
    orden: OrdenReparacion, *, checklist_disponible: bool = True
) -> list[str]:
    """Los faltantes que Recepcion todavia no confirmo."""
    faltantes = informacion_faltante(
        orden, checklist_disponible=checklist_disponible
    )
    if not faltantes:
        return []
    for confirmacion in orden.confirmaciones_informacion_faltante:
        if set(faltantes) <= set(confirmacion.faltantes):
            return []
    return faltantes


def confirmar_informacion_faltante(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
    checklist_disponible: bool = True,
) -> OrdenReparacion:
    """Recepcion continua igualmente: queda registrado que y quien."""
    validar_alguno_de(usuario, permisos.CHECKLIST_REGISTRAR)
    faltantes = informacion_faltante(
        orden, checklist_disponible=checklist_disponible
    )
    if not faltantes:
        raise PrecondicionInvalidaError("No falta informacion de recepcion.")
    nueva = orden.model_copy(deep=True)
    nueva.confirmaciones_informacion_faltante.append(
        ConfirmacionInformacionFaltante(
            faltantes=faltantes, usuario_id=usuario.id, fecha=fecha
        )
    )
    nueva.updated_at = fecha
    return nueva
