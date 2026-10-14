"""Capa de aplicacion: orquesta los services para atender una intencion.

Es la capa fina entre la API y el dominio. Cada funcion de aqui hace
siempre lo mismo:

    cargar de los repositories -> resolver catalogos y usuarios ->
    invocar los services en el orden del proceso -> persistir

y nada mas. No decide reglas de negocio -eso vive en ``app.services``-
ni conoce HTTP -eso vive en ``app.api``-.

CRITERIO DE AGRUPACION
----------------------
Un comando de aplicacion = una intencion de usuario, no un nodo del
proceso. Un comando arranca en el nodo que ejecuta un actor humano y
encadena todos los nodos ACT-SYSTEM y las decisiones que le siguen,
hasta el siguiente nodo con actor humano, que es donde corta. Nunca
atraviesa una segunda accion humana, y no existe ningun ejecutor
generico de workflow: la secuencia de cada comando esta escrita a mano
porque es una decision funcional, no una configuracion.
"""

from .acciones import (
    AccionDisponible,
    acciones_de_autorizacion,
    acciones_de_cancelacion,
    acciones_disponibles,
)
from .autorizacion_cliente import (
    AutorizacionDetalle,
    AutorizacionesOrden,
    PendienteAutorizacion,
    SituacionAutorizacion,
    autorizaciones_de_orden,
    decision_registrable,
    pendientes_de_autorizacion,
    registrar_decision_cliente,
    registrar_desistimiento,
    situacion_autorizacion,
)
from .cancelacion import cancelar_detalle, cancelar_orden, registrar_devolucion
from .cierre import (
    aprobar_control,
    devolver_rt,
    entregar,
    informar_rt,
    notificar,
    rechazar_control,
    registrar_pago_de_orden,
)
from .cola import encolar_orden
from .concurrencia import (
    LOCK_INVENTARIO,
    seccion_critica_inventario,
    seccion_critica_ordenes,
)
from .consultas import (
    DetalleOrigen,
    InsumoPrevisto,
    detalles_origen_de,
    insumos_previstos_por_detalle,
    listar_estaciones,
    listar_ordenes,
    listar_tipos_reparacion,
    listar_usuarios,
    nombres_de_tipo_por_detalle,
    obtener_orden,
)
from .contexto import ApplicationContext, construir_contexto
from .identificadores import siguiente_detalle_id, siguiente_orden_id
from .ingreso import (
    crear_orden,
    crear_orden_rt,
    definir_reparacion,
    definir_reparacion_desde_revision,
    enviar_a_revision,
    finalizar_definicion,
    finalizar_sin_reparacion,
    iniciar_garantia_rma,
)
from .progreso import PasoProgreso, progreso
from .recursos import (
    ImpactoOverride,
    esperar_recursos,
    forzar_detalle_por_recursos,
    impacto_override,
    revalidar_recursos,
)
from .redefinicion import redefinir_detalle, revisar_detalle
from .revision import realizar_revision
from .taller import (
    completar_ejecucion,
    iniciar_detalle,
    interrumpir_ejecucion,
    liberar_orden,
    requerir_redefinicion_ejecucion,
    tomar_orden_en_estacion,
)

__all__ = [
    # Contexto e infraestructura
    "ApplicationContext",
    "construir_contexto",
    "LOCK_INVENTARIO",
    "seccion_critica_inventario",
    "seccion_critica_ordenes",
    "siguiente_detalle_id",
    "siguiente_orden_id",
    # Lecturas
    "DetalleOrigen",
    "detalles_origen_de",
    "ImpactoOverride",
    "impacto_override",
    "listar_estaciones",
    "InsumoPrevisto",
    "insumos_previstos_por_detalle",
    "listar_ordenes",
    "listar_tipos_reparacion",
    "listar_usuarios",
    "nombres_de_tipo_por_detalle",
    "obtener_orden",
    "AutorizacionDetalle",
    "AutorizacionesOrden",
    "PendienteAutorizacion",
    "autorizaciones_de_orden",
    "pendientes_de_autorizacion",
    # Situacion de la Orden: acciones (por estado real) y progreso
    # (visualizacion, por Origen)
    "AccionDisponible",
    "PasoProgreso",
    "SituacionAutorizacion",
    "acciones_de_autorizacion",
    "acciones_de_cancelacion",
    "acciones_disponibles",
    "decision_registrable",
    "progreso",
    "situacion_autorizacion",
    # Comandos
    "crear_orden",
    "crear_orden_rt",
    "definir_reparacion",
    "definir_reparacion_desde_revision",
    "finalizar_definicion",
    "finalizar_sin_reparacion",
    "iniciar_garantia_rma",
    "enviar_a_revision",
    "realizar_revision",
    "esperar_recursos",
    "forzar_detalle_por_recursos",
    "revalidar_recursos",
    "encolar_orden",
    "tomar_orden_en_estacion",
    "iniciar_detalle",
    "liberar_orden",
    "completar_ejecucion",
    "interrumpir_ejecucion",
    "requerir_redefinicion_ejecucion",
    "revisar_detalle",
    "redefinir_detalle",
    "aprobar_control",
    "rechazar_control",
    "notificar",
    "registrar_pago_de_orden",
    "entregar",
    "informar_rt",
    "devolver_rt",
    "cancelar_detalle",
    "cancelar_orden",
    "registrar_devolucion",
    "registrar_decision_cliente",
    "registrar_desistimiento",
]
