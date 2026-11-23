"""Entrega del equipo al cliente en una sola operacion (PROC-REP-270).

Ajustes funcionales, bloque 2 (23/11/2026):

- DEC-AJ-03: la entrega no exige el aviso al cliente (PROC-REP-260). Si la
  condicion de entrega (PROC-REP-265) todavia no se evaluo, se evalua aca,
  en la misma operacion; sin aviso, antes se registra la decision
  PROC-REP-250 (requiere entrega a cliente).
- DEC-AJ-04: el check-in que falta se registra en la misma confirmacion
  (PROC-REP-269) y despues se revalida la condicion (265), como dice el
  proceso. El cobro sigue aparte: para entregar el Saldo es exactamente 0.

Cada control se hace una sola vez, aca, antes de registrar nada: el rol, el
resultado de la Orden, la cuenta, la custodia, el trabajo abierto y el
check-in. Despues se registran 250, 269, 265, 280 y 270 con las versiones
"sin validar" de cada service (``registrar_condicion_entrega``,
``marcar_comprobante_final`` y ``registrar_entrega``). Los services
sueltos (``validar_condicion_entrega``, ``generar_comprobante_final`` y
``entregar_equipo``) conservan sus controles para quien los use por
separado. Si algo falla, la capa de aplicacion no guarda nada.
"""

from datetime import datetime, timezone, tzinfo

from app.domain.models import EstadoCustodia, OrdenReparacion, Usuario
from app.domain.politicas import politica_de

from .autorizacion import validar_alguno_de
from .custodia import (
    DatosRetiro,
    armar_entrega,
    estado_custodia,
    exigir_equipo_en_custodia,
)
from .documentos import marcar_comprobante_final
from .exceptions import PrecondicionInvalidaError
from .garantias import (
    checkin_pendiente_para_entrega,
    exigir_checkin_para_entrega,
    registrar_checkin_de_entrega,
)
from .ordenes import (
    ROLES_ENTREGA,
    exigir_sin_trabajo_abierto,
    registrar_entrega,
)
from .pagos import (
    condicion_entrega_cumplida,
    motivo_de_entrega_bloqueada,
    registrar_condicion_entrega,
)
from .revisiones import lista_para_cierre
from .workflow import registrar_paso

# El cierre por Origen ya empezo: hubo aviso (260) y se evaluo la condicion
# de entrega (265), con o sin saldo pendiente (266).
NODOS_CIERRE_INICIADO = frozenset(
    {"PROC-REP-260", "PROC-REP-265", "PROC-REP-266"}
)
OPERACION = "entregar el equipo"


def bloqueo_de_entrega(orden: OrdenReparacion) -> str | None:
    """Lo que impide entregar ahora aparte de la cuenta, para la pantalla.

    Es el ``bloqueo`` de la accion ENTREGAR: el frontend lo muestra tal
    cual y no lo deduce. Hoy es la custodia sin confirmar; el check-in
    faltante ya no bloquea: se registra en la misma entrega (DEC-AJ-04).
    """
    estado = estado_custodia(orden)
    if estado is EstadoCustodia.EN_CUSTODIA:
        return None
    if estado is EstadoCustodia.PENDIENTE_CONFIRMACION:
        return "Falta confirmar la recepción física del equipo"
    if estado is EstadoCustodia.SIN_REGISTRO:
        return (
            "Falta regularizar la recepción del equipo (Orden anterior al "
            "registro de custodia)"
        )
    return f"El equipo no está en custodia ({estado.value})"


def entregar_al_cliente(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
    retiro: DatosRetiro,
    checkin: bool | None = None,
    checkin_motivo: str | None = None,
    zona_horaria: tzinfo = timezone.utc,
) -> OrdenReparacion:
    """La entrega comercial completa: [250] [269] [265] 280 270.

    ``checkin``: la respuesta del formulario de entrega (si se pudieron
    verificar las funciones basicas). Si el check-in falta, se registra
    con ella; si ya estaba, se respeta su regla de siempre (mismo valor:
    nada; otro: correccion con ``checkin_motivo``, DEC-MI-05).
    """
    validar_alguno_de(usuario, ROLES_ENTREGA)
    if not politica_de(orden.origen).requiere_entrega_cliente:
        raise PrecondicionInvalidaError(
            f"{orden.origen.value} no se entrega a un cliente: el equipo se "
            "devuelve a Gestion RT."
        )
    if not lista_para_cierre(orden):
        raise PrecondicionInvalidaError(
            f"Solo se entrega una Orden con resultado (REPARACION_LISTA o "
            f"SIN_REPARACION); esta en {orden.estado_workflow.value}."
        )
    # BR-REP-017 y BR-REP-038: saldo exactamente cero.
    if not condicion_entrega_cumplida(orden):
        raise PrecondicionInvalidaError(
            f"No se puede entregar: {motivo_de_entrega_bloqueada(orden)}. "
            "Resolve la cuenta (cobro o devolucion) y volve a intentarlo."
        )
    exigir_equipo_en_custodia(orden, operacion=OPERACION)
    exigir_sin_trabajo_abierto(orden)
    entrega = armar_entrega(orden, usuario=usuario, fecha=fecha, retiro=retiro)

    falta_checkin = checkin_pendiente_para_entrega(orden)
    if checkin is not None:
        orden = registrar_checkin_de_entrega(
            orden,
            realizado=checkin,
            usuario=usuario,
            fecha=fecha,
            motivo=checkin_motivo,
        )
    exigir_checkin_para_entrega(orden)

    # DEC-AJ-03: sin aviso, la Orden sigue en 240 o 069.
    if orden.current_process not in NODOS_CIERRE_INICIADO:
        orden = registrar_paso(
            orden,
            process_id="PROC-REP-250",
            accion="REQUIERE_ENTREGA_A_CLIENTE",
            fecha=fecha,
            observacion=orden.origen.value,
        )
    checkin_en_la_entrega = falta_checkin and checkin is not None
    if checkin_en_la_entrega:
        # DEC-AJ-04: PROC-REP-269 -> check-in registrado -> se revalida 265.
        orden = registrar_paso(
            orden,
            process_id="PROC-REP-269",
            accion="REGISTRAR_CHECKIN_EN_LA_ENTREGA",
            fecha=fecha,
            usuario_id=usuario.id,
            observacion=(
                "Funciones basicas verificadas"
                if checkin
                else "No se pudieron verificar las funciones basicas"
            ),
        )
    if checkin_en_la_entrega or orden.current_process != "PROC-REP-265":
        orden = registrar_condicion_entrega(orden, fecha=fecha)

    orden = marcar_comprobante_final(
        orden, fecha=fecha, zona_horaria=zona_horaria
    )
    return registrar_entrega(
        orden, usuario=usuario, fecha=fecha, entrega=entrega
    )
