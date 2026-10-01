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

from .acciones import AccionDisponible, acciones_disponibles
from .cierre import (
    aprobar_control,
    devolver_rt,
    entregar,
    informar_rt,
    notificar,
    registrar_pago_de_orden,
)
from .cola import encolar_orden
from .concurrencia import LOCK_INVENTARIO, seccion_critica_inventario
from .consultas import (
    InsumoPrevisto,
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
    crear_garantia_rma,
    crear_garantia_rma_en_revision,
    crear_orden,
    crear_orden_rt,
    definir_reparacion,
    definir_reparacion_desde_revision,
    enviar_a_revision,
)
from .progreso import PasoProgreso, progreso
from .recursos import esperar_recursos, revalidar_recursos
from .revision import realizar_revision
from .taller import (
    completar_ejecucion,
    iniciar_detalle,
    interrumpir_ejecucion,
    liberar_orden,
    tomar_orden_en_estacion,
)

__all__ = [
    # Contexto e infraestructura
    "ApplicationContext",
    "construir_contexto",
    "LOCK_INVENTARIO",
    "seccion_critica_inventario",
    "siguiente_detalle_id",
    "siguiente_orden_id",
    # Lecturas
    "listar_estaciones",
    "InsumoPrevisto",
    "insumos_previstos_por_detalle",
    "listar_ordenes",
    "listar_tipos_reparacion",
    "listar_usuarios",
    "nombres_de_tipo_por_detalle",
    "obtener_orden",
    # Situacion de la Orden: acciones (por estado real) y progreso
    # (visualizacion, por Origen)
    "AccionDisponible",
    "PasoProgreso",
    "acciones_disponibles",
    "progreso",
    # Comandos
    "crear_orden",
    "crear_orden_rt",
    "crear_garantia_rma",
    "crear_garantia_rma_en_revision",
    "definir_reparacion",
    "definir_reparacion_desde_revision",
    "enviar_a_revision",
    "realizar_revision",
    "esperar_recursos",
    "revalidar_recursos",
    "encolar_orden",
    "tomar_orden_en_estacion",
    "iniciar_detalle",
    "liberar_orden",
    "completar_ejecucion",
    "interrumpir_ejecucion",
    "aprobar_control",
    "notificar",
    "registrar_pago_de_orden",
    "entregar",
    "informar_rt",
    "devolver_rt",
]
