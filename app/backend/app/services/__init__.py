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
from .autorizacion_cliente import (
    EstadoAutorizacion,
    decision_vigente,
    detalles_pendientes_de_autorizacion,
    es_trabajable,
    estado_autorizacion,
    exigir_autorizacion_vigente,
    marcar_pendiente_autorizacion,
    pendiente_de_autorizacion,
    requiere_autorizacion_cliente,
    situacion_de_la_orden,
)
from .cancelaciones import (
    ROLES_CANCELACION,
    cancelar_detalle,
    cancelar_orden,
    registrar_devolucion_equipo,
    validar_cancelacion_detalle,
)
from .decision_cliente import (
    AnalisisDesistimiento,
    DecisionDetalle,
    ResultadoComercial,
    analizar_desistimiento,
    registrar_decision_cliente,
    registrar_desistimiento_cliente,
)
from .documentos import (
    generar_comprobante_final,
    generar_comprobante_recepcion,
)
from .ejecuciones import (
    ejecucion_activa,
    ejecutar_detalle,
    intentar_reserva_e_inicio,
    registrar_ejecucion_completada,
    registrar_ejecucion_interrumpida,
    registrar_ejecucion_requiere_redefinicion,
    registrar_reserva_fallida,
    reservar_insumos_e_iniciar_ejecucion,
)
from .exceptions import (
    ConfirmacionRequeridaError,
    DomainError,
    EntidadNoEncontradaError,
    OrdenCerradaError,
    PrecondicionInvalidaError,
    RecursoNoDisponibleError,
    TomaDeOtroTecnicoError,
)
from .identificadores import nuevo_id
from .inventario import (
    ImpactoStockInsumo,
    cantidad_pendiente,
    faltantes_del_detalle,
    generar_movimientos_inventario,
    hay_reservas_activas,
    impacto_en_stock_del_detalle,
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
    crear_orden_garantia_rma,
    crear_orden_rt_interno,
    definir_prioridad,
    devolucion_pendiente,
    devolver_equipo_rt,
    entregar_equipo,
    equipo_bajo_custodia,
    evaluar_situacion_orden,
    exigir_orden_abierta,
    habilitar_orden,
    informar_resultado_rt,
    ingresar_a_cola,
    marcar_orden_cancelada,
    marcar_orden_en_revision,
    marcar_reparacion_lista,
    notificar_cliente,
)
from .pagos import (
    ROLES_PAGO,
    condicion_entrega_cumplida,
    registrar_pago,
    registrar_saldo_pendiente,
    tipo_de_pago_para,
    validar_condicion_entrega,
)
from .recursos import (
    autorizar_override_recursos,
    continuar_por_override,
    exigir_espera_por_recursos,
    marcar_pendiente_recursos,
    override_listo_para_habilitar,
    registrar_espera_recursos,
    tiene_override_factibilidad,
    validar_override_recursos,
)
from .redefinicion import (
    marcar_pendiente_revision,
    redefinir_detalle,
    requiere_definicion,
    revisar_detalle_pendiente,
    revision_vigente,
)
from .reparaciones import (
    aprobar_control_tecnico,
    calcular_puntaje,
    control_tecnico_completo,
    definicion_finalizada,
    definir_reparacion_detail,
    definir_reparacion_detail_luego_revision,
    exigir_definicion_finalizable,
    hay_detalles_para_factibilidad,
    pendiente_de_retrabajo,
    rechazar_control_tecnico,
    validar_factibilidad_detalles,
)
from .resolucion import ResultadoEvaluacionOrden, resolver_situacion_orden
from .revisiones import (
    finalizada_sin_reparacion,
    lista_para_cierre,
    registrar_finalizacion_sin_reparacion,
    registrar_revision_tecnica,
)
from .tomas import (
    hay_ejecucion_activa,
    liberar_orden,
    seleccionar_detalle,
    toma_activa,
    tomar_orden,
    validar_compatibilidad_detalle,
    validar_estacion_trabajo,
    validar_titular_de_la_toma,
)
from .workflow import registrar_accion_funcional, registrar_paso

__all__ = [
    # Autorizacion funcional
    "actor_valido",
    "validar_actor",
    "validar_alguno_de",
    "validar_usuario_activo",
    # Errores de dominio
    "ConfirmacionRequeridaError",
    "DomainError",
    "EntidadNoEncontradaError",
    "OrdenCerradaError",
    "PrecondicionInvalidaError",
    "RecursoNoDisponibleError",
    "TomaDeOtroTecnicoError",
    # Trazabilidad e identificadores
    "nuevo_id",
    "registrar_accion_funcional",
    "registrar_paso",
    # Ciclo de vida de la Orden
    "crear_orden_cliente_externo",
    "crear_orden_garantia_rma",
    "crear_orden_rt_interno",
    "definir_prioridad",
    "devolucion_pendiente",
    "devolver_equipo_rt",
    "entregar_equipo",
    "equipo_bajo_custodia",
    "evaluar_situacion_orden",
    "exigir_orden_abierta",
    "habilitar_orden",
    "informar_resultado_rt",
    "ingresar_a_cola",
    "marcar_orden_cancelada",
    "marcar_orden_en_revision",
    "marcar_reparacion_lista",
    "notificar_cliente",
    # Cancelacion y devolucion (PROC-REP-300/305/306/270)
    "ROLES_CANCELACION",
    "cancelar_detalle",
    "cancelar_orden",
    "registrar_devolucion_equipo",
    "validar_cancelacion_detalle",
    # Autorizacion del cliente por Detalle (BR-REP-028, PROC-REP-046/047)
    "AnalisisDesistimiento",
    "analizar_desistimiento",
    "registrar_desistimiento_cliente",
    "DecisionDetalle",
    "EstadoAutorizacion",
    "ResultadoComercial",
    "decision_vigente",
    "detalles_pendientes_de_autorizacion",
    "es_trabajable",
    "estado_autorizacion",
    "exigir_autorizacion_vigente",
    "marcar_pendiente_autorizacion",
    "pendiente_de_autorizacion",
    "registrar_decision_cliente",
    "requiere_autorizacion_cliente",
    "situacion_de_la_orden",
    # Resolver puro de BR-REP-012
    "ResultadoEvaluacionOrden",
    "resolver_situacion_orden",
    # Espera de recursos (EXC-REP-001)
    "exigir_espera_por_recursos",
    "marcar_pendiente_recursos",
    "override_listo_para_habilitar",
    "autorizar_override_recursos",
    "continuar_por_override",
    "tiene_override_factibilidad",
    "validar_override_recursos",
    "registrar_espera_recursos",
    # Revision tecnica (PROC-REP-065)
    "registrar_revision_tecnica",
    "registrar_finalizacion_sin_reparacion",
    "finalizada_sin_reparacion",
    "lista_para_cierre",
    # Detalles de Reparacion
    "aprobar_control_tecnico",
    "calcular_puntaje",
    "control_tecnico_completo",
    "pendiente_de_retrabajo",
    "rechazar_control_tecnico",
    "definir_reparacion_detail",
    "definicion_finalizada",
    "exigir_definicion_finalizable",
    "hay_detalles_para_factibilidad",
    "definir_reparacion_detail_luego_revision",
    "validar_factibilidad_detalles",
    # Toma y seleccion
    "hay_ejecucion_activa",
    "liberar_orden",
    "seleccionar_detalle",
    "toma_activa",
    "tomar_orden",
    "validar_compatibilidad_detalle",
    "validar_estacion_trabajo",
    "validar_titular_de_la_toma",
    # Ejecucion
    "ejecucion_activa",
    "ejecutar_detalle",
    "registrar_ejecucion_completada",
    "registrar_ejecucion_interrumpida",
    "registrar_reserva_fallida",
    "registrar_ejecucion_requiere_redefinicion",
    # Revision posterior de un Detalle (EXC-REP-004)
    "marcar_pendiente_revision",
    "redefinir_detalle",
    "requiere_definicion",
    "revisar_detalle_pendiente",
    "revision_vigente",
    "intentar_reserva_e_inicio",
    "reservar_insumos_e_iniciar_ejecucion",
    # Inventario
    "ImpactoStockInsumo",
    "cantidad_pendiente",
    "faltantes_del_detalle",
    "generar_movimientos_inventario",
    "hay_reservas_activas",
    "impacto_en_stock_del_detalle",
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
    "condicion_entrega_cumplida",
    "registrar_pago",
    "tipo_de_pago_para",
    "registrar_saldo_pendiente",
    "validar_condicion_entrega",
    # Documentos
    "generar_comprobante_final",
    "generar_comprobante_recepcion",
]
