"""Caracterizacion de ``progreso()`` y ``acciones_disponibles()``.

Congela el comportamiento observable de HP-REP-001 ANTES del refactor de
Slice 0 (MVP v2 Foundation), que separa esas dos funciones de
``application/happy_path.py`` -acoplado a HP-REP-001- hacia un resolver
de acciones y un progreso generalizables por Origen (ver
``application/acciones.py`` y ``application/progreso.py``).

Se importa desde ``app.application`` (el paquete), no desde el modulo
interno: as[i] el test no le importa donde vive la implementacion, solo
le importa lo que devuelve. Eso es lo que permite mover el codigo sin
romper esta red de seguridad.

Unica excepcion deliberada: ``REGISTRAR_PAGO`` deja de tener ``roles=()``
y pasa a exigir ``ROLES_PAGO`` = (ADMINISTRADOR, RECEPCION,
COORDINADOR_RMA), porque BR-REP-017 ya define que un Tecnico no puede
registrar un Pago. Los tests que cubren un estado con saldo pendiente
declaran el valor NUEVO esperado, no ``roles=()``.

No se caracteriza ``ejecucion_id``: es un ID generado (no determinista
entre corridas), asi que se compara contra la Ejecucion real de la
Orden en lugar de un valor hardcodeado.
"""

from app.application import acciones_disponibles, progreso
from app.domain.models import RolUsuario
from app.services import (
    habilitar_orden,
    marcar_reparacion_lista,
    validar_factibilidad_detalles,
)

from .fixtures import flujo_mvp
from .fixtures.catalogos_mvp import INSUMOS, INSUMOS_PREVISTOS, t

# Corregido BR-REP-017: este era el ``()`` viejo (sin rol definido) con
# el que se corrio este test la primera vez, contra la implementacion
# sin tocar (paso 2 del orden obligatorio de Slice 0). Ahora que el fix
# de Registrar Pago aterrizo (paso 11), esta es la unica excepcion
# deliberada del caracterizado: el resto de las aserciones son
# identicas a las de antes del refactor.
ROLES_PAGO_ANTES_DEL_FIX = (
    RolUsuario.ADMINISTRADOR,
    RolUsuario.RECEPCION,
    RolUsuario.COORDINADOR_RMA,
)

# Los 33 nodos de HP-REP-001, en el orden en que el recorrido los expone.
# Incluye PROC-REP-212 (transversal, Slice 1) entre 180 y 181.
_TOTAL_NODOS_HP1 = 33


def _orden_habilitada():
    """Entre PROC-REP-140 y PROC-REP-150: HABILITADA, todavia sin cola."""
    orden, _ = validar_factibilidad_detalles(
        flujo_mvp.orden_con_detalle(),
        insumos=INSUMOS,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(15),
    )
    return habilitar_orden(orden, fecha=t(20))


def _orden_reparacion_lista_sin_notificar():
    """Entre PROC-REP-240 y PROC-REP-250: lista, cliente sin avisar."""
    return marcar_reparacion_lista(flujo_mvp.orden_controlada(), fecha=t(170))


def _codigos_y_roles(orden):
    return [
        (accion.codigo, accion.roles, accion.detalle_id)
        for accion in acciones_disponibles(orden)
    ]


def _alcanzados(orden):
    pasos = progreso(orden)
    assert len(pasos) == _TOTAL_NODOS_HP1
    return [paso.process_id for paso in pasos if paso.alcanzado]


def test_requerimiento_sin_detalles():
    orden = flujo_mvp.orden_creada()

    assert _codigos_y_roles(orden) == [
        ("AGREGAR_DETALLE", (RolUsuario.RECEPCION,), None),
        # Slice 4: la otra rama de PROC-REP-045 (Detalles no conocidos).
        ("ENVIAR_A_REVISION", (RolUsuario.RECEPCION,), None),
    ]
    assert _alcanzados(orden) == [
        "PROC-REP-010",
        "PROC-REP-030",
        "PROC-REP-040",
    ]


def test_habilitada():
    orden = _orden_habilitada()

    assert _codigos_y_roles(orden) == [
        (
            "ENCOLAR",
            (RolUsuario.COORDINADOR_RMA, RolUsuario.RECEPCION),
            None,
        ),
        ("REGISTRAR_PAGO", ROLES_PAGO_ANTES_DEL_FIX, None),
    ]
    assert _alcanzados(orden) == [
        "PROC-REP-010",
        "PROC-REP-030",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-070",
        "PROC-REP-050",
        "PROC-REP-060",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
    ]


def test_en_cola():
    orden = flujo_mvp.orden_en_cola()

    assert _codigos_y_roles(orden) == [
        ("TOMAR", (RolUsuario.TECNICO,), None),
        ("REGISTRAR_PAGO", ROLES_PAGO_ANTES_DEL_FIX, None),
    ]
    assert _alcanzados(orden) == [
        "PROC-REP-010",
        "PROC-REP-030",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-070",
        "PROC-REP-050",
        "PROC-REP-060",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
        "PROC-REP-150",
        "PROC-REP-170",
    ]


def test_toma_activa_sin_ejecucion():
    orden = flujo_mvp.orden_tomada()

    # Multi-Detalle (Slice 1): con una toma activa y ninguna Ejecucion en
    # curso, PROC-REP-212/213 ya estan implementados, asi que
    # LIBERAR_ORDEN pasa a ser una accion disponible mas -antes de este
    # slice no existia ningun comando que la produjera-.
    assert _codigos_y_roles(orden) == [
        ("INICIAR_DETALLE", (RolUsuario.TECNICO,), flujo_mvp.DETALLE_ID),
        ("LIBERAR_ORDEN", (RolUsuario.TECNICO,), None),
        ("REGISTRAR_PAGO", ROLES_PAGO_ANTES_DEL_FIX, None),
    ]
    assert _alcanzados(orden) == [
        "PROC-REP-010",
        "PROC-REP-030",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-070",
        "PROC-REP-050",
        "PROC-REP-060",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
        "PROC-REP-150",
        "PROC-REP-170",
        "PROC-REP-172",
        "PROC-REP-180",
        "PROC-REP-212",
        "PROC-REP-181",
        "PROC-REP-174",
    ]


def test_en_reparacion():
    orden = flujo_mvp.orden_con_ejecucion_iniciada()
    ejecucion_id = orden.ejecuciones[0].id

    acciones = acciones_disponibles(orden)
    assert [
        (accion.codigo, accion.roles, accion.detalle_id, accion.ejecucion_id)
        for accion in acciones
    ] == [
        (
            "COMPLETAR_EJECUCION",
            (RolUsuario.TECNICO,),
            flujo_mvp.DETALLE_ID,
            ejecucion_id,
        ),
        # Slice 5 (VAR-REP-003): la otra salida de PROC-REP-200.
        (
            "INTERRUMPIR_EJECUCION",
            (RolUsuario.TECNICO,),
            flujo_mvp.DETALLE_ID,
            ejecucion_id,
        ),
        # Slice 9 (EXC-REP-004): el tercer resultado de PROC-REP-200.
        (
            "REQUIERE_REDEFINICION",
            (RolUsuario.TECNICO,),
            flujo_mvp.DETALLE_ID,
            ejecucion_id,
        ),
        ("REGISTRAR_PAGO", ROLES_PAGO_ANTES_DEL_FIX, None, None),
    ]
    assert _alcanzados(orden) == [
        "PROC-REP-010",
        "PROC-REP-030",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-070",
        "PROC-REP-050",
        "PROC-REP-060",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
        "PROC-REP-150",
        "PROC-REP-170",
        "PROC-REP-172",
        "PROC-REP-180",
        "PROC-REP-212",
        "PROC-REP-181",
        "PROC-REP-174",
        "PROC-REP-185",
        "PROC-REP-190",
    ]


def test_espera_control():
    orden = flujo_mvp.orden_evaluada()

    # Multi-Detalle (Slice 1): el control tecnico ahora es granular por
    # Detalle (PROC-REP-230), asi que APROBAR_CONTROL declara el
    # detalle_id que aprobaria -antes, con la aprobacion en bloque, este
    # campo siempre viajaba en None-.
    assert _codigos_y_roles(orden) == [
        (
            "APROBAR_CONTROL",
            (RolUsuario.RECEPCION,),
            flujo_mvp.DETALLE_ID,
        ),
        ("REGISTRAR_PAGO", ROLES_PAGO_ANTES_DEL_FIX, None),
    ]
    assert _alcanzados(orden) == [
        "PROC-REP-010",
        "PROC-REP-030",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-070",
        "PROC-REP-050",
        "PROC-REP-060",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
        "PROC-REP-150",
        "PROC-REP-170",
        "PROC-REP-172",
        "PROC-REP-180",
        "PROC-REP-212",
        "PROC-REP-181",
        "PROC-REP-174",
        "PROC-REP-185",
        "PROC-REP-190",
        "PROC-REP-200",
        "PROC-REP-210",
        "PROC-REP-211",
    ]


def test_reparacion_lista_sin_notificar():
    orden = _orden_reparacion_lista_sin_notificar()

    assert _codigos_y_roles(orden) == [
        ("NOTIFICAR", (RolUsuario.RECEPCION,), None),
        ("REGISTRAR_PAGO", ROLES_PAGO_ANTES_DEL_FIX, None),
    ]
    assert _alcanzados(orden) == [
        "PROC-REP-010",
        "PROC-REP-030",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-070",
        "PROC-REP-050",
        "PROC-REP-060",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
        "PROC-REP-150",
        "PROC-REP-170",
        "PROC-REP-172",
        "PROC-REP-180",
        "PROC-REP-212",
        "PROC-REP-181",
        "PROC-REP-174",
        "PROC-REP-185",
        "PROC-REP-190",
        "PROC-REP-200",
        "PROC-REP-210",
        "PROC-REP-211",
        "PROC-REP-220",
        "PROC-REP-230",
        "PROC-REP-245",
        "PROC-REP-240",
    ]


def test_reparacion_lista_con_saldo():
    orden = flujo_mvp.orden_reparacion_lista()

    assert _codigos_y_roles(orden) == [
        ("REGISTRAR_PAGO", ROLES_PAGO_ANTES_DEL_FIX, None),
    ]
    assert _alcanzados(orden) == [
        "PROC-REP-010",
        "PROC-REP-030",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-070",
        "PROC-REP-050",
        "PROC-REP-060",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
        "PROC-REP-150",
        "PROC-REP-170",
        "PROC-REP-172",
        "PROC-REP-180",
        "PROC-REP-212",
        "PROC-REP-181",
        "PROC-REP-174",
        "PROC-REP-185",
        "PROC-REP-190",
        "PROC-REP-200",
        "PROC-REP-210",
        "PROC-REP-211",
        "PROC-REP-220",
        "PROC-REP-230",
        "PROC-REP-245",
        "PROC-REP-240",
        "PROC-REP-250",
        "PROC-REP-260",
    ]


def test_reparacion_lista_sin_saldo():
    orden = flujo_mvp.orden_pagada()

    assert _codigos_y_roles(orden) == [
        (
            "ENTREGAR",
            (RolUsuario.ADMINISTRADOR, RolUsuario.RECEPCION),
            None,
        ),
    ]
    assert _alcanzados(orden) == [
        "PROC-REP-010",
        "PROC-REP-030",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-070",
        "PROC-REP-050",
        "PROC-REP-060",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
        "PROC-REP-150",
        "PROC-REP-170",
        "PROC-REP-172",
        "PROC-REP-180",
        "PROC-REP-212",
        "PROC-REP-181",
        "PROC-REP-174",
        "PROC-REP-185",
        "PROC-REP-190",
        "PROC-REP-200",
        "PROC-REP-210",
        "PROC-REP-211",
        "PROC-REP-220",
        "PROC-REP-230",
        "PROC-REP-245",
        "PROC-REP-240",
        "PROC-REP-250",
        "PROC-REP-260",
        "PROC-REP-265",
        "PROC-REP-266",
    ]


def test_entregada():
    orden = flujo_mvp.orden_entregada()

    # HP-REP-003: una Orden ENTREGADA con Cliente ofrece a Recepcion
    # iniciar UNA garantia RMA (eligiendo 1..N Detalles en el formulario).
    assert _codigos_y_roles(orden) == [
        ("INICIAR_GARANTIA_RMA", (RolUsuario.RECEPCION,), None),
    ]
    assert _alcanzados(orden) == [
        "PROC-REP-010",
        "PROC-REP-030",
        "PROC-REP-040",
        "PROC-REP-045",
        "PROC-REP-070",
        "PROC-REP-050",
        "PROC-REP-060",
        "PROC-REP-080",
        "PROC-REP-090",
        "PROC-REP-140",
        "PROC-REP-150",
        "PROC-REP-170",
        "PROC-REP-172",
        "PROC-REP-180",
        "PROC-REP-212",
        "PROC-REP-181",
        "PROC-REP-174",
        "PROC-REP-185",
        "PROC-REP-190",
        "PROC-REP-200",
        "PROC-REP-210",
        "PROC-REP-211",
        "PROC-REP-220",
        "PROC-REP-230",
        "PROC-REP-245",
        "PROC-REP-240",
        "PROC-REP-250",
        "PROC-REP-260",
        "PROC-REP-265",
        "PROC-REP-266",
        "PROC-REP-280",
        "PROC-REP-270",
        "EVT-REP-999",
    ]


def test_hp1_212_queda_entre_180_y_181():
    ruta = [paso.process_id for paso in progreso(flujo_mvp.orden_creada())]

    assert ruta.index("PROC-REP-212") == ruta.index("PROC-REP-180") + 1
    assert ruta.index("PROC-REP-181") == ruta.index("PROC-REP-212") + 1


def test_la_fachada_happy_path_sigue_importable_y_reexporta_lo_mismo():
    """``application/happy_path.py`` sigue siendo la fachada del refactor.

    Excepcion deliberada al import por paquete: lo que se protege aca es
    justamente que el modulo interno siga importando y re-exportando los
    mismos objetos que ``acciones`` y ``progreso``.
    """
    from app.application import acciones, happy_path

    for nombre in happy_path.__all__:
        assert hasattr(happy_path, nombre), nombre
    assert happy_path.acciones_disponibles is acciones.acciones_disponibles
    assert happy_path.progreso is progreso
    assert happy_path.ACCION_AGREGAR_DETALLE == "AGREGAR_DETALLE"
