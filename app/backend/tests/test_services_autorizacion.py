"""Los services hacen cumplir los actores que PROC-REP V1.3 define.

    ACT-RECEP            -> 030/040, 070, 220/230, 260
    ACT-COORD/ACT-RECEP  -> 150  (actores_alternativos)
    ACT-TECH             -> 172, 180, 181, 190, 200
    ACT-ADMIN/ACT-RECEP  -> 270  (actores_alternativos)

Los nodos ACT-SYSTEM (060, 140, 170, 174, 185, 210, 211, 240, 245, 265,
266, 280) no exigen rol: como mucho, que el usuario que dispara la
operacion este activo.
"""

from decimal import Decimal
from inspect import signature

import pytest

from app.domain.models import (
    EstadoControl,
    EstadoEjecucion,
    EstadoTomaOrden,
    EstadoWorkflow,
    InsumoUtilizado,
    RolUsuario,
)
from app.services import (
    PrecondicionInvalidaError,
    actor_valido,
    aprobar_control_tecnico,
    crear_orden_cliente_externo,
    definir_prioridad,
    definir_reparacion_detail,
    ejecutar_detalle,
    entregar_equipo,
    generar_comprobante_recepcion,
    habilitar_orden,
    ingresar_a_cola,
    marcar_reparacion_lista,
    notificar_cliente,
    registrar_ejecucion_completada,
    registrar_pago,
    reservar_insumos_e_iniciar_ejecucion,
    seleccionar_detalle,
    toma_activa,
    tomar_orden,
    validar_actor,
    validar_estacion_trabajo,
    validar_usuario_activo,
)
from tests.fixtures import flujo_mvp
from tests.fixtures.catalogos_mvp import (
    ADMINISTRADOR,
    CLIENTE,
    COMPATIBILIDADES,
    COORDINADOR,
    EQUIPO,
    ESTACION,
    ESTACIONES,
    INSUMOS,
    INSUMOS_PREVISTOS,
    RECEPCION,
    TECNICO,
    TECNICO_DOS,
    TIPO_BATERIA,
    t,
)

DETALLE_ID = flujo_mvp.DETALLE_ID

RECEPCION_INACTIVA = RECEPCION.model_copy(update={"activo": False})
TECNICO_INACTIVO = TECNICO.model_copy(update={"activo": False})
COORDINADOR_INACTIVO = COORDINADOR.model_copy(update={"activo": False})
ADMINISTRADOR_INACTIVO = ADMINISTRADOR.model_copy(update={"activo": False})


# --- Helper ------------------------------------------------------------


def test_validar_actor_acepta_el_rol_correcto():
    assert validar_actor(RECEPCION, RolUsuario.RECEPCION) is None


def test_validar_actor_rechaza_un_rol_distinto():
    with pytest.raises(PrecondicionInvalidaError):
        validar_actor(TECNICO, RolUsuario.RECEPCION)


def test_validar_actor_rechaza_un_usuario_inactivo():
    with pytest.raises(PrecondicionInvalidaError):
        validar_actor(RECEPCION_INACTIVA, RolUsuario.RECEPCION)


def test_actor_valido_no_lanza_y_devuelve_bool():
    assert actor_valido(TECNICO, RolUsuario.TECNICO) is True
    assert actor_valido(RECEPCION, RolUsuario.TECNICO) is False
    assert actor_valido(TECNICO_INACTIVO, RolUsuario.TECNICO) is False


def test_validar_usuario_activo_solo_mira_el_estado():
    assert validar_usuario_activo(TECNICO) is None
    assert validar_usuario_activo(ADMINISTRADOR) is None

    with pytest.raises(PrecondicionInvalidaError):
        validar_usuario_activo(TECNICO_INACTIVO)


# 1) y 2) PROC-REP-030/040: ACT-RECEP.


def test_recepcion_puede_crear_orden():
    orden = crear_orden_cliente_externo(
        orden_id="OR-001",
        cliente=CLIENTE,
        equipo=EQUIPO,
        usuario=RECEPCION,
        fecha=t(0),
    )

    assert orden.estado_workflow is EstadoWorkflow.REQUERIMIENTO


@pytest.mark.parametrize(
    "usuario", [TECNICO, COORDINADOR, ADMINISTRADOR, RECEPCION_INACTIVA]
)
def test_solo_recepcion_puede_crear_orden(usuario):
    with pytest.raises(PrecondicionInvalidaError):
        crear_orden_cliente_externo(
            orden_id="OR-001",
            cliente=CLIENTE,
            equipo=EQUIPO,
            usuario=usuario,
            fecha=t(0),
        )


# 3) PROC-REP-070: ACT-RECEP.


def test_recepcion_puede_definir_detalle():
    orden = definir_reparacion_detail(
        flujo_mvp.orden_creada(),
        detalle_id="DET-001",
        tipo_reparacion=TIPO_BATERIA,
        usuario=RECEPCION,
        fecha=t(5),
    )

    assert len(orden.reparaciones_detail) == 1


@pytest.mark.parametrize("usuario", [TECNICO, COORDINADOR, RECEPCION_INACTIVA])
def test_solo_recepcion_puede_definir_detalle(usuario):
    with pytest.raises(PrecondicionInvalidaError):
        definir_reparacion_detail(
            flujo_mvp.orden_creada(),
            detalle_id="DET-001",
            tipo_reparacion=TIPO_BATERIA,
            usuario=usuario,
            fecha=t(5),
        )


# 4) y 5) PROC-REP-150: ACT-COORD o ACT-RECEP.


def test_coordinador_puede_definir_prioridad():
    habilitada = flujo_mvp.orden_habilitada()

    orden = definir_prioridad(
        habilitada, prioridad=2, usuario=COORDINADOR, fecha=t(25)
    )

    assert orden.prioridad == 2


def test_recepcion_tambien_puede_definir_prioridad():
    """PROC-REP-150 declara actores_alternativos: [ACT-RECEP]."""
    habilitada = flujo_mvp.orden_habilitada()

    orden = definir_prioridad(
        habilitada, prioridad=3, usuario=RECEPCION, fecha=t(25)
    )

    assert orden.prioridad == 3
    assert orden.historial[-1].usuario_id == RECEPCION.id


@pytest.mark.parametrize(
    "usuario",
    [TECNICO, ADMINISTRADOR, COORDINADOR_INACTIVO, RECEPCION_INACTIVA],
)
def test_solo_coordinacion_o_recepcion_definen_prioridad(usuario):
    """Ampliar a dos actores no abre la accion a cualquiera."""
    habilitada = flujo_mvp.orden_habilitada()

    with pytest.raises(PrecondicionInvalidaError):
        definir_prioridad(
            habilitada, prioridad=2, usuario=usuario, fecha=t(25)
        )


# 6) y 7) PROC-REP-180: ACT-TECH.


def test_tecnico_puede_tomar_orden():
    orden = tomar_orden(
        flujo_mvp.orden_en_cola(),
        usuario=TECNICO,
        estacion_id=ESTACION.id,
        fecha=t(60),
    )

    toma = toma_activa(orden)
    assert toma is not None
    assert toma.estado is EstadoTomaOrden.ACTIVA


@pytest.mark.parametrize(
    "usuario", [RECEPCION, COORDINADOR, ADMINISTRADOR, TECNICO_INACTIVO]
)
def test_solo_un_tecnico_puede_tomar_orden(usuario):
    with pytest.raises(PrecondicionInvalidaError):
        tomar_orden(
            flujo_mvp.orden_en_cola(),
            usuario=usuario,
            estacion_id=ESTACION.id,
            fecha=t(60),
        )


# PROC-REP-172: ACT-TECH, sin excepcion (devuelve el resultado).


@pytest.mark.parametrize(
    "usuario", [RECEPCION, ADMINISTRADOR, TECNICO_INACTIVO]
)
def test_la_validacion_de_estacion_rechaza_a_quien_no_es_tecnico(usuario):
    _, valida = validar_estacion_trabajo(
        flujo_mvp.orden_en_cola(),
        usuario=usuario,
        estacion_id=ESTACION.id,
        estaciones=ESTACIONES,
        compatibilidades=COMPATIBILIDADES,
        fecha=t(58),
    )

    assert valida is False


# PROC-REP-181: ACT-TECH.


@pytest.mark.parametrize("usuario", [RECEPCION, COORDINADOR, TECNICO_INACTIVO])
def test_solo_un_tecnico_puede_seleccionar_detalle(usuario):
    tomada = flujo_mvp.orden_en_cola()
    tomada = tomar_orden(
        tomada, usuario=TECNICO, estacion_id=ESTACION.id, fecha=t(60)
    )

    with pytest.raises(PrecondicionInvalidaError):
        seleccionar_detalle(
            tomada, detalle_id=DETALLE_ID, usuario=usuario, fecha=t(62)
        )


# PROC-REP-190: ACT-TECH.


@pytest.mark.parametrize(
    "usuario", [RECEPCION, ADMINISTRADOR, TECNICO_INACTIVO]
)
def test_solo_un_tecnico_puede_ejecutar_el_detalle(usuario):
    orden = reservar_insumos_e_iniciar_ejecucion(
        flujo_mvp.orden_tomada(),
        detalle_id=DETALLE_ID,
        usuario=TECNICO,
        insumos=INSUMOS,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(65),
    )

    with pytest.raises(PrecondicionInvalidaError):
        ejecutar_detalle(
            orden, detalle_id=DETALLE_ID, usuario=usuario, fecha=t(70)
        )


# 8) PROC-REP-200: ACT-TECH.


def test_tecnico_puede_registrar_la_ejecucion():
    orden = flujo_mvp.orden_con_ejecucion_iniciada()

    orden = registrar_ejecucion_completada(
        orden,
        ejecucion_id=orden.ejecuciones[0].id,
        insumos_utilizados=[
            InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal("1"))
        ],
        usuario=TECNICO,
        fecha=t(145),
    )

    assert orden.ejecuciones[0].fin == t(145)
    # El historial atribuye el paso a quien lo registro.
    paso = orden.historial[-1]
    assert paso.process_id == "PROC-REP-200"
    assert paso.usuario_id == TECNICO.id


@pytest.mark.parametrize(
    "usuario", [RECEPCION, ADMINISTRADOR, TECNICO_INACTIVO]
)
def test_solo_un_tecnico_puede_registrar_la_ejecucion(usuario):
    orden = flujo_mvp.orden_con_ejecucion_iniciada()

    with pytest.raises(PrecondicionInvalidaError):
        registrar_ejecucion_completada(
            orden,
            ejecucion_id=orden.ejecuciones[0].id,
            insumos_utilizados=[
                InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal("1"))
            ],
            usuario=usuario,
            fecha=t(145),
        )


# 9) y 10) PROC-REP-220/230: ACT-RECEP.


def test_recepcion_puede_realizar_el_control_tecnico():
    orden = aprobar_control_tecnico(
        flujo_mvp.orden_evaluada(), usuario=RECEPCION, fecha=t(160)
    )

    assert orden.reparaciones_detail[0].control_estado is (
        EstadoControl.APROBADO
    )


@pytest.mark.parametrize(
    "usuario", [TECNICO, COORDINADOR, ADMINISTRADOR, RECEPCION_INACTIVA]
)
def test_el_tecnico_no_puede_aprobar_su_propio_control(usuario):
    with pytest.raises(PrecondicionInvalidaError):
        aprobar_control_tecnico(
            flujo_mvp.orden_evaluada(), usuario=usuario, fecha=t(160)
        )


# 11) PROC-REP-260: ACT-RECEP.


def test_recepcion_puede_notificar_al_cliente():
    lista = marcar_reparacion_lista(flujo_mvp.orden_controlada(), fecha=t(170))

    orden = notificar_cliente(lista, usuario=RECEPCION, fecha=t(175))

    assert orden.current_process == "PROC-REP-260"


@pytest.mark.parametrize("usuario", [TECNICO, COORDINADOR, RECEPCION_INACTIVA])
def test_solo_recepcion_puede_notificar_al_cliente(usuario):
    lista = marcar_reparacion_lista(flujo_mvp.orden_controlada(), fecha=t(170))

    with pytest.raises(PrecondicionInvalidaError):
        notificar_cliente(lista, usuario=usuario, fecha=t(175))


# 12) y 13) PROC-REP-270: ACT-ADMIN o ACT-RECEP.


def test_administrador_puede_entregar_el_equipo():
    orden = entregar_equipo(
        flujo_mvp.orden_documentada(), usuario=ADMINISTRADOR, fecha=t(195)
    )

    assert orden.estado_workflow is EstadoWorkflow.ENTREGADA
    assert orden.current_process == "EVT-REP-999"


def test_recepcion_tambien_puede_entregar_el_equipo():
    """PROC-REP-270 declara actores_alternativos: [ACT-RECEP]."""
    orden = entregar_equipo(
        flujo_mvp.orden_documentada(), usuario=RECEPCION, fecha=t(195)
    )

    assert orden.estado_workflow is EstadoWorkflow.ENTREGADA
    assert orden.current_process == "EVT-REP-999"


@pytest.mark.parametrize(
    "usuario",
    [TECNICO, COORDINADOR, ADMINISTRADOR_INACTIVO, RECEPCION_INACTIVA],
)
def test_solo_administracion_o_recepcion_entregan(usuario):
    with pytest.raises(PrecondicionInvalidaError):
        entregar_equipo(
            flujo_mvp.orden_documentada(), usuario=usuario, fecha=t(195)
        )


def test_recepcion_no_puede_saltear_la_condicion_de_entrega():
    """Ampliar el actor no relaja la regla comercial (BR-REP-017-B)."""
    con_saldo = flujo_mvp.orden_reparacion_lista()

    with pytest.raises(PrecondicionInvalidaError):
        entregar_equipo(con_saldo, usuario=RECEPCION, fecha=t(195))


# 14) Un usuario inactivo falla aunque tenga el rol correcto.


@pytest.mark.parametrize(
    ("usuario", "operacion"),
    [
        (RECEPCION_INACTIVA, "crear"),
        (TECNICO_INACTIVO, "tomar"),
        (COORDINADOR_INACTIVO, "prioridad"),
        (ADMINISTRADOR_INACTIVO, "entregar"),
    ],
)
def test_un_usuario_inactivo_no_puede_operar(usuario, operacion):
    """El rol correcto no alcanza: la sesion tiene que estar activa."""
    if operacion == "crear":
        with pytest.raises(PrecondicionInvalidaError):
            crear_orden_cliente_externo(
                orden_id="OR-001",
                cliente=CLIENTE,
                equipo=EQUIPO,
                usuario=usuario,
                fecha=t(0),
            )
    elif operacion == "tomar":
        with pytest.raises(PrecondicionInvalidaError):
            tomar_orden(
                flujo_mvp.orden_en_cola(),
                usuario=usuario,
                estacion_id=ESTACION.id,
                fecha=t(60),
            )
    elif operacion == "prioridad":
        habilitada = flujo_mvp.orden_habilitada()
        with pytest.raises(PrecondicionInvalidaError):
            definir_prioridad(
                habilitada, prioridad=1, usuario=usuario, fecha=t(25)
            )
    else:
        with pytest.raises(PrecondicionInvalidaError):
            entregar_equipo(
                flujo_mvp.orden_documentada(), usuario=usuario, fecha=t(195)
            )


@pytest.mark.parametrize(
    "servicio",
    [
        generar_comprobante_recepcion,
        habilitar_orden,
        ingresar_a_cola,
        marcar_reparacion_lista,
    ],
)
def test_los_nodos_de_sistema_no_reciben_usuario(servicio):
    """ACT-SYSTEM no lo ejecuta una persona: no hay parametro usuario."""
    assert "usuario" not in signature(servicio).parameters


def test_los_nodos_de_sistema_corren_sin_actor_humano():
    """PROC-REP-060/140/170 avanzan sin que nadie los firme."""
    con_factibilidad = flujo_mvp.orden_con_factibilidad()

    habilitada = habilitar_orden(con_factibilidad, fecha=t(20))
    assert habilitada.estado_workflow is EstadoWorkflow.HABILITADA

    en_cola = ingresar_a_cola(habilitada, fecha=t(30))
    assert en_cola.estado_workflow is EstadoWorkflow.EN_COLA


def test_el_historial_de_los_nodos_de_sistema_no_tiene_usuario():
    orden = flujo_mvp.orden_entregada()
    por_nodo = {paso.process_id: paso.usuario_id for paso in orden.historial}

    for process_id in (
        "PROC-REP-060",
        "PROC-REP-140",
        "PROC-REP-170",
        "PROC-REP-240",
    ):
        assert por_nodo[process_id] is None, process_id


# Registrar Pago (BR-REP-017): usuario ACTIVO AND rol != TECNICO.
# Corrige el bug del MVP anterior, donde cualquier usuario activo -un
# Tecnico incluido- podia registrar un Pago.


@pytest.mark.parametrize("usuario", [ADMINISTRADOR, RECEPCION, COORDINADOR])
def test_registrar_pago_permite_administrador_recepcion_y_coordinador(
    usuario,
):
    """BR-REP-017: los tres roles no-Tecnico pueden cobrar."""
    orden = registrar_pago(
        flujo_mvp.orden_reparacion_lista(),
        monto=Decimal("80000"),
        metodo="EFECTIVO",
        usuario=usuario,
        fecha=t(185),
    )

    assert orden.saldo == Decimal("0")


def test_registrar_pago_rechaza_al_tecnico():
    """BR-REP-017: un Tecnico nunca puede registrar un Pago."""
    with pytest.raises(PrecondicionInvalidaError):
        registrar_pago(
            flujo_mvp.orden_reparacion_lista(),
            monto=Decimal("80000"),
            metodo="EFECTIVO",
            usuario=TECNICO,
            fecha=t(185),
        )


def test_registrar_pago_rechaza_un_usuario_inactivo():
    with pytest.raises(PrecondicionInvalidaError):
        registrar_pago(
            flujo_mvp.orden_reparacion_lista(),
            monto=Decimal("80000"),
            metodo="EFECTIVO",
            usuario=ADMINISTRADOR_INACTIVO,
            fecha=t(185),
        )


# No-mutacion ante una validacion fallida.


def test_una_autorizacion_fallida_no_modifica_la_orden():
    original = flujo_mvp.orden_en_cola()
    antes = original.model_dump(mode="json")

    with pytest.raises(PrecondicionInvalidaError):
        tomar_orden(
            original,
            usuario=RECEPCION,
            estacion_id=ESTACION.id,
            fecha=t(60),
        )

    assert original.model_dump(mode="json") == antes
    assert original.tomas == []
    assert original.historial[-1].process_id == "PROC-REP-170"


def test_un_control_rechazado_por_rol_no_aprueba_nada():
    original = flujo_mvp.orden_evaluada()
    antes = original.model_dump(mode="json")

    with pytest.raises(PrecondicionInvalidaError):
        aprobar_control_tecnico(original, usuario=TECNICO, fecha=t(160))

    assert original.model_dump(mode="json") == antes
    assert original.reparaciones_detail[0].control_estado is (
        EstadoControl.PENDIENTE
    )


# 15) El E2E sigue pasando con los cuatro actores correctos.


def test_el_happy_path_usa_los_cuatro_actores_correctos():
    orden = flujo_mvp.orden_entregada()

    assert orden.estado_workflow is EstadoWorkflow.ENTREGADA
    assert orden.current_process == "EVT-REP-999"

    por_nodo = {paso.process_id: paso.usuario_id for paso in orden.historial}

    assert por_nodo["PROC-REP-030"] == RECEPCION.id
    assert por_nodo["PROC-REP-040"] == RECEPCION.id
    assert por_nodo["PROC-REP-070"] == RECEPCION.id
    assert por_nodo["PROC-REP-150"] == COORDINADOR.id
    assert por_nodo["PROC-REP-180"] == TECNICO.id
    assert por_nodo["PROC-REP-181"] == TECNICO.id
    assert por_nodo["PROC-REP-190"] == TECNICO.id
    assert por_nodo["PROC-REP-200"] == TECNICO.id
    assert por_nodo["PROC-REP-220"] == RECEPCION.id
    assert por_nodo["PROC-REP-260"] == RECEPCION.id
    assert por_nodo["PROC-REP-270"] == ADMINISTRADOR.id

    # Los nodos ACT-SYSTEM no tienen actor humano asignado.
    assert por_nodo["PROC-REP-210"] is None
    assert por_nodo["PROC-REP-211"] is None
    assert por_nodo["PROC-REP-245"] is None
    assert por_nodo["PROC-REP-265"] is None
    assert por_nodo["PROC-REP-280"] is None


# --- Identidad: la Ejecucion pertenece al tecnico que la inicio --------


def test_el_tecnico_propietario_puede_ejecutar_y_completar():
    """HP-REP-001: TECH-001 toma, inicia, ejecuta y completa."""
    orden = flujo_mvp.orden_con_ejecucion_iniciada()
    ejecucion_id = orden.ejecuciones[0].id

    orden = registrar_ejecucion_completada(
        orden,
        ejecucion_id=ejecucion_id,
        insumos_utilizados=[
            InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal("1"))
        ],
        usuario=TECNICO,
        fecha=t(145),
    )

    assert orden.ejecuciones[0].usuario_id == TECNICO.id
    assert orden.ejecuciones[0].fin == t(145)

    por_nodo = {paso.process_id: paso.usuario_id for paso in orden.historial}
    assert por_nodo["PROC-REP-185"] == TECNICO.id
    assert por_nodo["PROC-REP-190"] == TECNICO.id
    assert por_nodo["PROC-REP-200"] == TECNICO.id


def test_otro_tecnico_no_puede_ejecutar_la_ejecucion_activa():
    """PROC-REP-190: la Ejecucion es de quien la inicio."""
    orden = reservar_insumos_e_iniciar_ejecucion(
        flujo_mvp.orden_tomada(),
        detalle_id=DETALLE_ID,
        usuario=TECNICO,
        insumos=INSUMOS,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(65),
    )

    with pytest.raises(PrecondicionInvalidaError):
        ejecutar_detalle(
            orden, detalle_id=DETALLE_ID, usuario=TECNICO_DOS, fecha=t(70)
        )


def test_otro_tecnico_no_puede_completar_la_ejecucion_activa():
    """PROC-REP-200: continuarla exige una Ejecucion nueva.

    Nunca cerrar la del tecnico anterior.
    """
    orden = flujo_mvp.orden_con_ejecucion_iniciada()

    with pytest.raises(PrecondicionInvalidaError):
        registrar_ejecucion_completada(
            orden,
            ejecucion_id=orden.ejecuciones[0].id,
            insumos_utilizados=[
                InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal("1"))
            ],
            usuario=TECNICO_DOS,
            fecha=t(145),
        )


def test_un_fallo_de_identidad_no_muta_la_orden():
    original = flujo_mvp.orden_con_ejecucion_iniciada()
    antes = original.model_dump(mode="json")

    with pytest.raises(PrecondicionInvalidaError):
        ejecutar_detalle(
            original, detalle_id=DETALLE_ID, usuario=TECNICO_DOS, fecha=t(70)
        )

    with pytest.raises(PrecondicionInvalidaError):
        registrar_ejecucion_completada(
            original,
            ejecucion_id=original.ejecuciones[0].id,
            insumos_utilizados=[
                InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal("1"))
            ],
            usuario=TECNICO_DOS,
            fecha=t(145),
        )

    assert original.model_dump(mode="json") == antes
    assert original.ejecuciones[0].estado is EstadoEjecucion.EN_PROGRESO
    assert original.ejecuciones[0].fin is None


def test_la_ejecucion_debe_pertenecer_a_la_toma_activa():
    """La Ejecucion, la toma y el tecnico son la misma identidad."""
    orden = flujo_mvp.orden_con_ejecucion_iniciada()

    # Se cierra la toma dejando la Ejecucion abierta: estado imposible en
    # el flujo, pero la invariante debe detectarlo igual.
    orden = orden.model_copy(deep=True)
    orden.tomas[0].estado = EstadoTomaOrden.CERRADA

    with pytest.raises(PrecondicionInvalidaError):
        ejecutar_detalle(
            orden, detalle_id=DETALLE_ID, usuario=TECNICO, fecha=t(70)
        )
