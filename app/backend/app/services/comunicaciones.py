"""Reglas de las comunicaciones asistidas y el consentimiento (DEC-MI-08).

- El mensaje sale de una plantilla vigente con variables de la Orden; el
  usuario lo revisa y puede editarlo antes de abrir WhatsApp. Lo que se
  registra es el mensaje que efectivamente se preparo.
- Abrir WhatsApp es un intento: no se marca como enviado. La confirmacion
  manual (enviado o no) se registra una sola vez. Nunca «entregado» ni
  «leido».
- Finalidad comercial: exige un consentimiento expreso vigente para el
  canal. Operativa: se envia salvo que el cliente la haya rechazado.
- El consentimiento es un historial: otorgar y revocar agregan registros.
"""

import re
from collections.abc import Iterable, Sequence
from datetime import datetime, tzinfo

from app.domain.garantia import vencimiento_garantia
from app.domain.models import (
    CambioConfiguracion,
    EntidadConfiguracion,
    EstadoControl,
    OrdenReparacion,
    Usuario,
)
from app.domain.models.comunicaciones import (
    VARIABLES,
    CanalMensaje,
    ComunicacionCliente,
    ConfirmacionEnvio,
    ConsentimientoComunicacion,
    FinalidadComunicacion,
    PlantillaMensaje,
)

from . import permisos
from .autorizacion import validar_alguno_de
from .configuracion import texto
from .exceptions import PrecondicionInvalidaError
from .ordenes import fecha_de_entrega

_VARIABLE = re.compile(r"\{([a-z_]+)\}")
CAMPOS_PLANTILLA = ("nombre", "finalidad", "texto", "activa")


def _pesos(valor) -> str:
    entero, _, decimales = f"{valor:,.2f}".partition(".")
    return (
        "$ "
        + entero.replace(",", ".")
        + ("" if decimales == "00" else "," + decimales)
    )


def variables_de_la_orden(
    orden: OrdenReparacion, *, empresa: str, zona_horaria: tzinfo
) -> dict[str, str]:
    """Los valores disponibles para la plantilla (los que se conocen)."""
    equipo = " ".join(
        parte
        for parte in (
            orden.equipo.marca,
            orden.equipo.modelo,
            orden.equipo.variante,
        )
        if parte
    )
    valores = {
        "orden": orden.id,
        "equipo": equipo,
        "total": _pesos(orden.total),
        "saldo": _pesos(max(orden.saldo, 0)),
        "empresa": empresa,
    }
    if orden.cliente is not None:
        valores["cliente"] = orden.cliente.nombre_apellido
    entrega = fecha_de_entrega(orden)
    vencimientos = [
        vence
        for detalle in orden.reparaciones_detail
        if detalle.control_estado is EstadoControl.APROBADO
        and (
            vence := vencimiento_garantia(
                entrega, detalle.garantia_dias, zona_horaria
            )
        )
        is not None
    ]
    if vencimientos:
        valores["garantia_hasta"] = max(vencimientos).strftime("%d/%m/%Y")
    return valores


def variables_de(texto_plantilla: str) -> list[str]:
    return list(dict.fromkeys(_VARIABLE.findall(texto_plantilla)))


def preparar_mensaje(
    plantilla: PlantillaMensaje, valores: dict[str, str]
) -> tuple[str, list[str]]:
    """El texto con las variables reemplazadas y las que no tienen valor
    (quedan escritas entre llaves para que el usuario las complete)."""
    faltantes = [v for v in variables_de(plantilla.texto) if v not in valores]
    mensaje = _VARIABLE.sub(
        lambda m: valores.get(m.group(1), m.group(0)), plantilla.texto
    )
    return mensaje, faltantes


def consentimiento_vigente(
    historial: Iterable[ConsentimientoComunicacion],
    finalidad: FinalidadComunicacion,
    canal: CanalMensaje,
) -> ConsentimientoComunicacion | None:
    """El ultimo registro para esa finalidad y canal (o ninguno)."""
    vigente = None
    for registro in sorted(historial, key=lambda r: r.fecha):
        if registro.finalidad is finalidad and registro.canal is canal:
            vigente = registro
    return vigente


def impedimento_de_consentimiento(
    historial: Iterable[ConsentimientoComunicacion],
    finalidad: FinalidadComunicacion,
    canal: CanalMensaje,
) -> str | None:
    """Por que no se puede enviar (o ``None`` si se puede)."""
    vigente = consentimiento_vigente(historial, finalidad, canal)
    if finalidad is FinalidadComunicacion.COMERCIAL:
        if vigente is None or not vigente.otorgado:
            return (
                "Un mensaje comercial exige el consentimiento expreso del "
                "cliente para este canal."
            )
        return None
    if vigente is not None and not vigente.otorgado:
        return (
            "El cliente pidio no recibir avisos por este canal: respeta su "
            "preferencia."
        )
    return None


def registrar_intento(
    orden: OrdenReparacion,
    *,
    plantilla: PlantillaMensaje | None,
    mensaje: str,
    destinatario: str | None,
    historial: Sequence[ConsentimientoComunicacion],
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """Se abrio WhatsApp con el mensaje preparado. No es un envio."""
    validar_alguno_de(usuario, permisos.COMUNICACION_ENVIAR)
    mensaje = (mensaje or "").strip()
    if not mensaje:
        raise PrecondicionInvalidaError("El mensaje no puede estar vacio.")
    if plantilla is not None and not plantilla.activa:
        raise PrecondicionInvalidaError(
            f"La plantilla «{plantilla.nombre}» no esta vigente."
        )
    if orden.cliente is None:
        raise PrecondicionInvalidaError(
            "La Orden no tiene un cliente externo a quien escribir."
        )
    finalidad = (
        plantilla.finalidad if plantilla else FinalidadComunicacion.OPERATIVA
    )
    impedimento = impedimento_de_consentimiento(
        historial, finalidad, CanalMensaje.WHATSAPP
    )
    if impedimento:
        raise PrecondicionInvalidaError(impedimento)
    nueva = orden.model_copy(deep=True)
    nueva.comunicaciones.append(
        ComunicacionCliente(
            id=f"COM-{len(nueva.comunicaciones) + 1:03d}",
            plantilla_codigo=plantilla.codigo if plantilla else None,
            finalidad=finalidad,
            destinatario=(destinatario or "").strip() or None,
            mensaje=mensaje,
            usuario_id=usuario.id,
            fecha=fecha,
        )
    )
    nueva.updated_at = fecha
    return nueva


def confirmar_envio(
    orden: OrdenReparacion,
    comunicacion_id: str,
    *,
    enviado: bool,
    nota: str | None,
    usuario: Usuario,
    fecha: datetime,
) -> OrdenReparacion:
    """Confirmacion manual: se envio o no. Una sola vez."""
    validar_alguno_de(usuario, permisos.COMUNICACION_ENVIAR)
    nueva = orden.model_copy(deep=True)
    comunicacion = next(
        (c for c in nueva.comunicaciones if c.id == comunicacion_id), None
    )
    if comunicacion is None:
        raise PrecondicionInvalidaError(
            f"No existe la comunicacion {comunicacion_id} en la Orden."
        )
    if comunicacion.confirmacion is not None:
        raise PrecondicionInvalidaError(
            "Esa comunicacion ya se confirmo: no se modifica."
        )
    comunicacion.confirmacion = ConfirmacionEnvio(
        enviado=enviado,
        usuario_id=usuario.id,
        fecha=fecha,
        nota=(nota or "").strip() or None,
    )
    nueva.updated_at = fecha
    return nueva


def nuevo_consentimiento(
    *,
    cliente_id: str,
    finalidad: FinalidadComunicacion,
    canal: CanalMensaje,
    otorgado: bool,
    origen: str,
    usuario: Usuario,
    fecha: datetime,
) -> ConsentimientoComunicacion:
    validar_alguno_de(usuario, permisos.CONSENTIMIENTO_REGISTRAR)
    origen = (origen or "").strip()
    if not origen:
        raise PrecondicionInvalidaError(
            "Indica el origen del consentimiento (como se obtuvo)."
        )
    return ConsentimientoComunicacion(
        cliente_id=cliente_id,
        finalidad=finalidad,
        canal=canal,
        otorgado=otorgado,
        origen=origen,
        usuario_id=usuario.id,
        fecha=fecha,
    )


def cambios_de_plantilla(
    anterior: PlantillaMensaje | None,
    nueva: PlantillaMensaje,
    *,
    usuario: Usuario,
    fecha: datetime,
) -> list[CambioConfiguracion]:
    validar_alguno_de(usuario, permisos.PLANTILLA_GESTIONAR)
    desconocidas = [v for v in variables_de(nueva.texto) if v not in VARIABLES]
    if desconocidas:
        raise PrecondicionInvalidaError(
            "Variables desconocidas: "
            + ", ".join("{" + v + "}" for v in desconocidas)
            + ". Disponibles: "
            + ", ".join("{" + v + "}" for v in VARIABLES)
            + "."
        )
    cambios = [
        CambioConfiguracion(
            entidad=EntidadConfiguracion.PLANTILLA,
            clave=nueva.codigo,
            campo=campo,
            valor_anterior=texto(getattr(anterior, campo))
            if anterior
            else None,
            valor_nuevo=texto(getattr(nueva, campo)),
            usuario_id=usuario.id,
            fecha=fecha,
        )
        for campo in CAMPOS_PLANTILLA
        if anterior is None
        or texto(getattr(anterior, campo)) != texto(getattr(nueva, campo))
    ]
    if not cambios:
        raise PrecondicionInvalidaError(
            f"La plantilla {nueva.codigo} ya tiene esos valores: no hay "
            "cambios."
        )
    return cambios
