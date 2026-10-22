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
    acciones_complementarias,
    acciones_de_autorizacion,
    acciones_de_cancelacion,
    acciones_de_custodia,
    acciones_disponibles,
    acciones_financieras,
    puede_ejecutar,
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
from .bandejas import (
    Bandeja,
    DestinoBandeja,
    ItemBandeja,
    TipoBandeja,
    TrabajoEnBandeja,
    VistaBandejas,
    bandejas_de_inicio,
    bandejas_de_taller,
)
from .cancelacion import cancelar_detalle, cancelar_orden, registrar_devolucion
from .catalogo_equipos import (
    EstadoCatalogoEquipos,
    catalogo_para_seleccion,
    equipo_desde_catalogo,
    estado_catalogo_equipos,
    sincronizar_catalogo_equipos,
)
from .cierre import (
    aprobar_control,
    devolver_rt,
    entregar,
    informar_rt,
    notificar,
    rechazar_control,
    registrar_checkin,
    registrar_pago_de_orden,
)
from .clientes import (
    BusquedaCliente,
    EstadoBusqueda,
    buscar_cliente_por_dni,
)
from .cola import cambiar_prioridad_de_orden, encolar_orden
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
from .custodia import (
    agregar_observacion_recepcion,
    confirmar_recepcion,
    registrar_no_recepcion,
    registrar_recepcion,
)
from .documentos import (
    DocumentosDeOrden,
    contexto_documentos,
    documento_de_orden,
    documentos_de_orden,
    emitir_comprobante_autorizacion,
    emitir_comprobante_recepcion,
    pdf_documento_de_orden,
    vista_previa_documento,
)
from .finanzas import (
    MovimientoFinanciero,
    SituacionFinanciera,
    anular_pago_de_orden,
    aplicar_descuento_de_orden,
    listar_medios_pago,
    movimientos_financieros,
    registrar_devolucion_de_dinero,
    situacion_financiera,
)
from .fotos import (
    LimpiezaFotos,
    agregar_foto,
    foto_de_orden,
    limpiar_fotos_huerfanas,
)
from .garantias import ajustar_garantia
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
from .ingreso_inicial import generar_comprobante_ingreso
from .inventario import (
    DetalleInsumo,
    ResultadoMovimientoStock,
    ResultadoRevalidacion,
    ResultadoRevalidacionMasiva,
    ResultadoRevalidacionOrden,
    consultar_inventario,
    detalle_de_insumo,
    movimientos_de_inventario,
    registrar_ajuste_stock,
    registrar_ingreso_stock,
    revalidar_ordenes_pendientes,
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
from .situacion import (
    AvisoOperativo,
    CodigoSituacion,
    EstadoEtapa,
    EtapaOperativa,
    SituacionOperativa,
    TareaOperativa,
    situacion_de_orden,
    situacion_operativa,
)
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
    # Catalogo de equipos de Ventas
    "EstadoCatalogoEquipos",
    "catalogo_para_seleccion",
    "equipo_desde_catalogo",
    "estado_catalogo_equipos",
    "sincronizar_catalogo_equipos",
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
    "acciones_de_custodia",
    "acciones_disponibles",
    "acciones_financieras",
    "DocumentosDeOrden",
    "contexto_documentos",
    "documento_de_orden",
    "documentos_de_orden",
    "pdf_documento_de_orden",
    "vista_previa_documento",
    "MovimientoFinanciero",
    "SituacionFinanciera",
    "listar_medios_pago",
    "movimientos_financieros",
    "situacion_financiera",
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
    "AvisoOperativo",
    "CodigoSituacion",
    "EstadoEtapa",
    "EtapaOperativa",
    "SituacionOperativa",
    "TareaOperativa",
    "situacion_de_orden",
    "situacion_operativa",
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
    "registrar_checkin",
    "entregar",
    "informar_rt",
    "devolver_rt",
    "cancelar_detalle",
    "cancelar_orden",
    "registrar_devolucion",
    "registrar_decision_cliente",
    "registrar_desistimiento",
    "anular_pago_de_orden",
    "registrar_devolucion_de_dinero",
    "registrar_recepcion",
    "confirmar_recepcion",
    "registrar_no_recepcion",
    # Inventario operativo
    "DetalleInsumo",
    "ResultadoMovimientoStock",
    "ResultadoRevalidacion",
    "ResultadoRevalidacionMasiva",
    "ResultadoRevalidacionOrden",
    "consultar_inventario",
    "detalle_de_insumo",
    "movimientos_de_inventario",
    "registrar_ajuste_stock",
    "registrar_ingreso_stock",
    "revalidar_ordenes_pendientes",
    "agregar_observacion_recepcion",
    "emitir_comprobante_autorizacion",
    "emitir_comprobante_recepcion",
    # Bandejas de trabajo (lectura)
    "Bandeja",
    "DestinoBandeja",
    "ItemBandeja",
    "TipoBandeja",
    "TrabajoEnBandeja",
    "VistaBandejas",
    "bandejas_de_inicio",
    "bandejas_de_taller",
    "puede_ejecutar",
    # MVP v2: iteracion 1 del UAT
    "acciones_complementarias",
    "ajustar_garantia",
    "BusquedaCliente",
    "EstadoBusqueda",
    "buscar_cliente_por_dni",
    "agregar_foto",
    "foto_de_orden",
    "LimpiezaFotos",
    "limpiar_fotos_huerfanas",
    "aplicar_descuento_de_orden",
    "cambiar_prioridad_de_orden",
    "generar_comprobante_ingreso",
]
