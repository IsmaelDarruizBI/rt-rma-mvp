"""Casos de uso del MVP de Rosario Tecno RMA App.

Cada service es una funcion que recibe la Orden, no la modifica y
devuelve una Orden nueva. No hay un caso de uso "ejecutar HP-REP-001":
el escenario se compone invocando estos services en orden, igual que
hara la API mas adelante.

Alcance: el camino de HP-REP-001 sobre PROC-REP V1.3. Las rutas
alternativas del proceso (revision, overrides, reserva fallida,
retrabajo, cancelacion) no estan implementadas y fallan con un error de
dominio explicito.

Los services no leen ``business/``: esa sigue siendo la fuente de verdad
funcional. Lo unico que comparten con ella son los IDs
(``PROC-REP-*``), citados en los docstrings y guardados en el historial.
"""

from .autorizacion import (
    actor_valido,
    validar_actor,
    validar_alguno_de,
    validar_usuario_activo,
)
from .documentos import (
    generar_comprobante_final,
    generar_comprobante_recepcion,
)
from .ejecuciones import (
    ejecucion_activa,
    ejecutar_detalle,
    registrar_ejecucion_completada,
    reservar_insumos_e_iniciar_ejecucion,
)
from .exceptions import (
    DomainError,
    EntidadNoEncontradaError,
    PrecondicionInvalidaError,
    RecursoNoDisponibleError,
)
from .identificadores import nuevo_id
from .inventario import (
    cantidad_pendiente,
    generar_movimientos_inventario,
    hay_reservas_activas,
    insumos_previstos_de,
    inventario_aplicado,
    reservas_activas,
    stock_disponible,
)
from .inventario_global import (
    aplicar_movimientos_inventario,
    cantidad_reservada_global,
    cargar_reservas_externas,
    reservas_activas_globales,
    reservas_externas_a,
    stock_disponible_global,
    stock_disponible_por_insumo,
)
from .ordenes import (
    crear_orden_cliente_externo,
    definir_prioridad,
    entregar_equipo,
    evaluar_situacion_orden,
    habilitar_orden,
    ingresar_a_cola,
    marcar_reparacion_lista,
    notificar_cliente,
)
from .pagos import (
    ROLES_PAGO,
    registrar_pago,
    registrar_saldo_pendiente,
    tipo_de_pago_para,
    validar_condicion_entrega,
)
from .reparaciones import (
    aprobar_control_tecnico,
    calcular_puntaje,
    definir_reparacion_detail,
    validar_factibilidad_detalles,
)
from .resolucion import ResultadoEvaluacionOrden, resolver_situacion_orden
from .tomas import (
    hay_ejecucion_activa,
    seleccionar_detalle,
    toma_activa,
    tomar_orden,
    validar_compatibilidad_detalle,
    validar_estacion_trabajo,
)
from .workflow import registrar_accion_funcional, registrar_paso

__all__ = [
    # Autorizacion funcional
    "actor_valido",
    "validar_actor",
    "validar_alguno_de",
    "validar_usuario_activo",
    # Errores de dominio
    "DomainError",
    "EntidadNoEncontradaError",
    "PrecondicionInvalidaError",
    "RecursoNoDisponibleError",
    # Trazabilidad e identificadores
    "nuevo_id",
    "registrar_accion_funcional",
    "registrar_paso",
    # Ciclo de vida de la Orden
    "crear_orden_cliente_externo",
    "definir_prioridad",
    "entregar_equipo",
    "evaluar_situacion_orden",
    "habilitar_orden",
    "ingresar_a_cola",
    "marcar_reparacion_lista",
    "notificar_cliente",
    # Resolver puro de BR-REP-012
    "ResultadoEvaluacionOrden",
    "resolver_situacion_orden",
    # Detalles de Reparacion
    "aprobar_control_tecnico",
    "calcular_puntaje",
    "definir_reparacion_detail",
    "validar_factibilidad_detalles",
    # Toma y seleccion
    "hay_ejecucion_activa",
    "seleccionar_detalle",
    "toma_activa",
    "tomar_orden",
    "validar_compatibilidad_detalle",
    "validar_estacion_trabajo",
    # Ejecucion
    "ejecucion_activa",
    "ejecutar_detalle",
    "registrar_ejecucion_completada",
    "reservar_insumos_e_iniciar_ejecucion",
    # Inventario
    "cantidad_pendiente",
    "generar_movimientos_inventario",
    "hay_reservas_activas",
    "insumos_previstos_de",
    "inventario_aplicado",
    "reservas_activas",
    "stock_disponible",
    # Inventario global (todas las Ordenes)
    "aplicar_movimientos_inventario",
    "cantidad_reservada_global",
    "cargar_reservas_externas",
    "reservas_activas_globales",
    "reservas_externas_a",
    "stock_disponible_global",
    "stock_disponible_por_insumo",
    # Pagos
    "ROLES_PAGO",
    "registrar_pago",
    "tipo_de_pago_para",
    "registrar_saldo_pendiente",
    "validar_condicion_entrega",
    # Documentos
    "generar_comprobante_final",
    "generar_comprobante_recepcion",
]
