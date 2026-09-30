"""Slice 0: `completar_ejecucion` ya no arriesga persistencia parcial.

Contexto (ver el analisis de gap de MVP v2): ``taller.completar_ejecucion``
llama a ``aplicar_movimientos_inventario`` -que ya GUARDA la Orden y
descuenta stock fisico- y recien despues llama a
``evaluar_situacion_orden``. Con la implementacion anterior, esa segunda
llamada lanzaba ``PrecondicionInvalidaError`` para cualquier situacion
que no fuera "todos los Detalles COMPLETO", dejando el inventario ya
persistido pero el comando entero devolviendo un error 409: exactamente
el riesgo de persistencia parcial que Slice 0 debia eliminar.

Con el resolver completo de BR-REP-012 (``app.services.resolucion``),
``evaluar_situacion_orden`` clasifica cualquier situacion tecnica
legitima sin lanzar. Completar la Ejecucion de UN Detalle en una Orden
con DOS ya no puede fallar despues de haber persistido: el resultado es
``ABIERTA_TRABAJABLE``, no una excepcion.

La Orden se arma componiendo services directamente -multi-Detalle
operativo por API todavia no existe, ``application.ingreso.definir_reparacion``
sigue aceptando un unico Detalle por llamada (fuera del scope de Slice
0)-, pero el comando bajo prueba (``application.taller.completar_ejecucion``)
es el real, con repositories JSON reales, igual que en
``test_hp_rep_001_persistido.py``.
"""

from decimal import Decimal
from itertools import count

from app.application import ApplicationContext, completar_ejecucion
from app.application.taller import iniciar_detalle, tomar_orden_en_estacion
from app.domain.models import (
    EstadoReparacionDetail,
    EstadoTomaOrden,
    InsumoUtilizado,
)
from app.services import (
    ResultadoEvaluacionOrden,
    crear_orden_cliente_externo,
    definir_prioridad,
    definir_reparacion_detail,
    generar_comprobante_recepcion,
    habilitar_orden,
    ingresar_a_cola,
    validar_factibilidad_detalles,
)
from app.storage import JsonCatalogosRepository, JsonOrdenReparacionRepository
from app.storage.json.base import escribir_json_atomico
from tests.fixtures.catalogos_mvp import (
    ADMINISTRADOR,
    CLIENTE,
    COMPATIBILIDADES,
    COORDINADOR,
    EQUIPO,
    ESTACION,
    ESTACIONES,
    INSUMO_BATERIA,
    INSUMOS,
    INSUMOS_PREVISTOS,
    RECEPCION,
    TECNICO,
    TIPO_BATERIA,
    t,
)

ORDEN_ID = "OR-000001"
DETALLE_1 = "DET-001"
DETALLE_2 = "DET-002"


def _contexto(tmp_path) -> ApplicationContext:
    ordenes_repo = JsonOrdenReparacionRepository(tmp_path / "ordenes")
    catalogos_repo = JsonCatalogosRepository(tmp_path / "catalogs")

    catalogos = {
        "tipos_reparacion.json": [TIPO_BATERIA],
        "insumos.json": [INSUMO_BATERIA],
        "tipo_reparacion_insumos.json": INSUMOS_PREVISTOS,
        "estaciones.json": ESTACIONES,
        "tipo_reparacion_estaciones.json": COMPATIBILIDADES,
        "usuarios.json": [RECEPCION, COORDINADOR, TECNICO, ADMINISTRADOR],
    }
    for archivo, entidades in catalogos.items():
        escribir_json_atomico(
            catalogos_repo.directorio / archivo,
            [entidad.model_dump(mode="json") for entidad in entidades],
        )

    minutos = count(0)
    return ApplicationContext(
        ordenes=ordenes_repo,
        catalogos=catalogos_repo,
        ahora=lambda: t(next(minutos)),
    )


def _orden_en_cola_con_dos_detalles():
    """Compone los services -no la API- para tener 2 Detalles EN_COLA.

    El stock de INS-001 (2 unidades) alcanza para los dos Detalles: cada
    uno preve consumir 1 (``INSUMOS_PREVISTOS``).
    """
    orden = crear_orden_cliente_externo(
        orden_id=ORDEN_ID,
        cliente=CLIENTE,
        equipo=EQUIPO,
        usuario=RECEPCION,
        fecha=t(0),
    )
    orden = definir_reparacion_detail(
        orden,
        detalle_id=DETALLE_1,
        tipo_reparacion=TIPO_BATERIA,
        usuario=RECEPCION,
        fecha=t(1),
    )
    orden = definir_reparacion_detail(
        orden,
        detalle_id=DETALLE_2,
        tipo_reparacion=TIPO_BATERIA,
        usuario=RECEPCION,
        fecha=t(2),
    )
    orden = generar_comprobante_recepcion(orden, fecha=t(3))
    orden, factible = validar_factibilidad_detalles(
        orden,
        insumos=INSUMOS,
        insumos_previstos=INSUMOS_PREVISTOS,
        fecha=t(4),
    )
    assert factible is True

    orden = habilitar_orden(orden, fecha=t(5))
    orden = definir_prioridad(
        orden, prioridad=1, usuario=COORDINADOR, fecha=t(6)
    )
    return ingresar_a_cola(orden, fecha=t(7))


def test_completar_un_detalle_con_otro_pendiente_no_lanza(tmp_path):
    """Antes: PrecondicionInvalidaError tras persistir el inventario.

    Ahora: ``ABIERTA_TRABAJABLE``, sin excepcion, con el inventario y la
    Orden en un estado coherente entre si.
    """
    contexto = _contexto(tmp_path)
    contexto.ordenes.guardar(_orden_en_cola_con_dos_detalles())

    tomar_orden_en_estacion(
        contexto,
        orden_id=ORDEN_ID,
        usuario_id=TECNICO.id,
        estacion_id=ESTACION.id,
    )
    orden = iniciar_detalle(
        contexto,
        orden_id=ORDEN_ID,
        detalle_id=DETALLE_1,
        usuario_id=TECNICO.id,
    )
    ejecucion_id = orden.ejecuciones[0].id

    # Antes de Slice 0 esta linea lanzaba PrecondicionInvalidaError
    # DESPUES de que aplicar_movimientos_inventario ya habia guardado la
    # Orden y descontado el stock: el riesgo de persistencia parcial.
    orden, resultado = completar_ejecucion(
        contexto,
        orden_id=ORDEN_ID,
        ejecucion_id=ejecucion_id,
        usuario_id=TECNICO.id,
        insumos_utilizados=[
            InsumoUtilizado(insumo_id="INS-001", cantidad=Decimal("1")),
        ],
    )

    assert resultado is ResultadoEvaluacionOrden.ABIERTA_TRABAJABLE

    detalle_1 = next(
        d for d in orden.reparaciones_detail if d.id == DETALLE_1
    )
    detalle_2 = next(
        d for d in orden.reparaciones_detail if d.id == DETALLE_2
    )
    assert detalle_1.estado is EstadoReparacionDetail.COMPLETO
    assert detalle_2.estado is EstadoReparacionDetail.DEFINIDO

    # BR-REP-018: con un Detalle todavia trabajable, la toma NO se
    # cierra automaticamente (a diferencia de COMPLETA/TODO_CANCELADO).
    assert orden.tomas[0].estado is EstadoTomaOrden.ACTIVA

    # La Orden persistida coincide exactamente con lo que devolvio el
    # comando: no quedo ningun efecto a medio aplicar.
    persistida = contexto.ordenes.obtener(ORDEN_ID)
    assert persistida == orden

    # Se consumio solo lo del Detalle 1: 2 - 1 = 1.
    assert contexto.catalogos.obtener_insumo(
        "INS-001"
    ).stock_fisico == Decimal("1")
