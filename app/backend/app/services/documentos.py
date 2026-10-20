"""Documentos de la Orden.

Nodos cubiertos: PROC-REP-050/060 (comprobante de recepcion) y
PROC-REP-280 (comprobante final y garantia de reparacion).
Features: FEAT-REP-001, FEAT-REP-007, FEAT-REP-008.

El comprobante de autorizacion no es un nodo del proceso: lo emite
Recepcion a pedido (``emitir_comprobante_autorizacion``, ACC-REP-060) con
los trabajos que el cliente autorizo. Convive con el de recepcion, que sigue
siendo la constancia de ingreso y custodia del equipo; una version nueva de
este a pedido queda como ACC-REP-002.

Dos niveles:

- las marcas del proceso (``generar_comprobante_recepcion`` y
  ``generar_comprobante_final``): que el nodo emitio el documento;
- el documento emitido (``registrar_documento``): un snapshot inmutable de
  los datos con que se entrego, armado por ``contenido_*``. No se genera
  ningun PDF: el snapshot reproduce la version imprimible.

Una version nueva de un documento ya emitido exige motivo y conserva la
anterior. Volver a emitir el mismo contenido (un reintento) devuelve el
documento existente: nunca se duplica.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal

from app.domain.models import (
    CoberturaGarantia,
    ContenidoComprobanteAutorizacion,
    ContenidoComprobanteEntrega,
    ContenidoComprobanteIngreso,
    ContenidoComprobanteRecepcion,
    ContenidoDocumento,
    ContenidoGarantia,
    DatosEmpresa,
    DescuentoEnDocumento,
    DevolucionDineroEnDocumento,
    Documento,
    DocumentoEmitido,
    EntregaEquipo,
    EstadoControl,
    EstadoCustodia,
    EstadoReparacionDetail,
    EstadoWorkflow,
    OrdenReparacion,
    PagoEnDocumento,
    RegistroAutorizacionCliente,
    ReparacionDetail,
    ResultadoAutorizacion,
    RolUsuario,
    TipoDocumento,
    TipoEntrega,
    TrabajoAutorizadoEnDocumento,
    TrabajoCanceladoEnDocumento,
    TrabajoEnDocumento,
    Usuario,
    UsuarioEnDocumento,
    importe_de_descuento,
)
from app.domain.politicas import CondicionComercial, politica_de

from .autorizacion import validar_alguno_de
from .autorizacion_cliente import (
    decision_vigente,
    requiere_autorizacion_cliente,
)
from .custodia import ROLES_RECEPCION_EQUIPO, estado_custodia, tipo_de_entrega
from .descuentos import descripcion_de_descuento
from .exceptions import EntidadNoEncontradaError, PrecondicionInvalidaError
from .pagos import condicion_entrega_cumplida
from .reparaciones import nombre_del_trabajo
from .revisiones import finalizada_sin_reparacion, lista_para_cierre
from .workflow import registrar_accion_funcional, registrar_paso

# Emision a pedido de un documento: accion funcional sin nodo propio, con
# la System Action de CADA documento. ACC-REP-026 es la entrega del equipo
# (traceability/hp-rep-001.yaml) y nunca se usa para emitir documentos.
ACCION_EMITIR_COMPROBANTE_RECEPCION = "ACC-REP-002"
ACCION_EMITIR_COMPROBANTE_AUTORIZACION = "ACC-REP-060"

SIGLA_DOCUMENTO = {
    TipoDocumento.COMPROBANTE_RECEPCION: "REC",
    TipoDocumento.COMPROBANTE_ENTREGA: "ENT",
    TipoDocumento.GARANTIA: "GAR",
    TipoDocumento.COMPROBANTE_AUTORIZACION: "AUT",
    TipoDocumento.COMPROBANTE_INGRESO: "ING",
}

# Documentos que listan trabajos autorizados: el de ingreso (al ingresar)
# y el de autorizacion (autorizaciones posteriores).
_CON_TRABAJOS_AUTORIZADOS = (
    TipoDocumento.COMPROBANTE_INGRESO,
    TipoDocumento.COMPROBANTE_AUTORIZACION,
)

# Lo emite quien registra la decision del cliente (PROC-REP-046).
ROLES_COMPROBANTE_AUTORIZACION = (RolUsuario.RECEPCION,)

LEYENDA_RECEPCION = (
    "Este comprobante acredita la recepcion del equipo en las condiciones "
    "indicadas. No implica autorizacion de reparaciones ni aceptacion de "
    "presupuesto: cada trabajo requiere la autorizacion del cliente."
)
LEYENDA_RECEPCION_GARANTIA = (
    "Este comprobante acredita la recepcion del equipo en las condiciones "
    "indicadas para su revision en garantia. No implica que el reclamo este "
    "aceptado ni compromete ningun cobro."
)
LEYENDA_INGRESO = (
    "Constancia de recepción del equipo en las condiciones indicadas y de "
    "la autorización de los trabajos detallados con su precio. No es un "
    "comprobante de pago ni una factura, y no requiere firma."
)
LEYENDA_AUTORIZACION = (
    "Este comprobante detalla los trabajos que el cliente autorizó y su "
    "precio. No es un comprobante de pago ni una factura, y no requiere "
    "firma. Los trabajos pendientes, rechazados o cancelados no figuran."
)


def generar_comprobante_recepcion(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-050 -> PROC-REP-060 si corresponde (FEAT-REP-001).

    La rama la fija ``PoliticaOrigen.requiere_comprobante_recepcion``
    (BR-REP-016), no un origen hardcodeado: CLIENTE_EXTERNO y
    RMA_GARANTIA_REPARACION lo exigen, RT_INTERNO no (HP-REP-002 no
    acredita que un cliente dejo el equipo, no hay cliente). Cuando la
    politica dice "No", PROC-REP-050 igual queda registrado -la decision
    se tomo- pero PROC-REP-060 no se ejecuta.

    PROC-REP-060 es ACT-SYSTEM: no lo ejecuta una persona, asi que no
    recibe Usuario y el historial queda sin actor humano.
    """
    if orden.documentos.comprobante_recepcion.generado:
        raise PrecondicionInvalidaError(
            "El comprobante de recepcion ya fue generado."
        )

    requiere = politica_de(orden.origen).requiere_comprobante_recepcion

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-050",
        accion="REQUIERE_COMPROBANTE_RECEPCION",
        fecha=fecha,
        observacion="Si" if requiere else "No",
    )
    if not requiere:
        return nueva_orden

    nueva_orden = registrar_paso(
        nueva_orden,
        process_id="PROC-REP-060",
        accion="GENERAR_COMPROBANTE_RECEPCION",
        fecha=fecha,
    )
    nueva_orden.documentos.comprobante_recepcion = Documento(
        generado=True,
        fecha_generacion=fecha,
    )
    return nueva_orden


def generar_comprobante_final(
    orden: OrdenReparacion,
    *,
    fecha: datetime,
) -> OrdenReparacion:
    """PROC-REP-280: comprobante final y garantia de reparacion.

    Se genera DESPUES de que PROC-REP-265 confirma la condicion de
    entrega, para que el saldo informado sea el definitivo.

    La garantia de reparacion se emite unicamente si hubo reparacion: una
    Orden SIN_REPARACION (PROC-REP-069, BR-REP-010) recibe el comprobante
    final con Subtotal 0 y sin garantia.
    """
    if not lista_para_cierre(orden):
        raise PrecondicionInvalidaError(
            f"El comprobante final se emite sobre una Orden con resultado "
            f"(REPARACION_LISTA o SIN_REPARACION); esta en "
            f"{orden.estado_workflow.value}."
        )
    if orden.current_process != "PROC-REP-265":
        raise PrecondicionInvalidaError(
            "Falta validar la condicion de entrega (PROC-REP-265) "
            "antes de emitir el comprobante final; la Orden esta en "
            f"{orden.current_process}."
        )
    if not condicion_entrega_cumplida(orden):
        raise PrecondicionInvalidaError(
            f"No se emite el comprobante final con saldo pendiente: "
            f"{orden.saldo}."
        )

    sin_reparacion = finalizada_sin_reparacion(orden)
    observacion = f"Total {orden.total} / Saldo {orden.saldo}"
    if sin_reparacion:
        observacion += " / SIN_REPARACION: sin garantia de reparacion"

    nueva_orden = registrar_paso(
        orden,
        process_id="PROC-REP-280",
        accion="GENERAR_COMPROBANTE_FINAL",
        fecha=fecha,
        observacion=observacion,
    )
    nueva_orden.documentos.comprobante_final = Documento(
        generado=True,
        fecha_generacion=fecha,
    )
    if not sin_reparacion:
        nueva_orden.documentos.garantia_reparacion = Documento(
            generado=True,
            fecha_generacion=fecha,
        )
    return nueva_orden


# --- Contenido de los documentos ---------------------------------------------


@dataclass(frozen=True)
class ContextoDocumentos:
    """Datos de catalogo que un documento copia al emitirse.

    Los arma la capa de aplicacion. Se copian al snapshot (nombres de
    usuario, de Tipo de Reparacion y de medio de pago, datos de la
    empresa) para que un cambio de catalogo posterior no altere lo que se
    le entrego al cliente. ``zona_horaria`` fija el dia calendario de un
    vencimiento.
    """

    empresa: DatosEmpresa
    usuarios: Mapping[str, str] = field(default_factory=dict)
    tipos: Mapping[str, str] = field(default_factory=dict)
    medios: Mapping[str, str] = field(default_factory=dict)
    detalles_reclamados: Sequence[TrabajoEnDocumento] = ()
    zona_horaria: tzinfo = timezone.utc


def _usuario(
    contexto: ContextoDocumentos,
    usuario_id: str | None,
) -> UsuarioEnDocumento | None:
    if usuario_id is None:
        return None
    return UsuarioEnDocumento(
        id=usuario_id, nombre=contexto.usuarios.get(usuario_id, usuario_id)
    )


def _datos_comunes(
    orden: OrdenReparacion,
    contexto: ContextoDocumentos,
) -> dict:
    return {
        "empresa": contexto.empresa.model_copy(deep=True),
        "orden_id": orden.id,
        "origen": orden.origen,
        "fecha_ingreso": orden.created_at,
        "cliente": (
            orden.cliente.model_copy(deep=True) if orden.cliente else None
        ),
        "referencia_rt": orden.referencia_rt,
        "equipo": orden.equipo.model_copy(deep=True),
        "orden_origen_id": orden.orden_origen_id,
        "detalles_reclamados": [
            trabajo.model_copy(deep=True)
            for trabajo in contexto.detalles_reclamados
        ],
    }


def _es_cobrable(orden: OrdenReparacion) -> bool:
    return (
        politica_de(orden.origen).condicion_comercial
        == CondicionComercial.COBRABLE
    )


def _realizados(orden: OrdenReparacion):
    """Detalles realizados y aprobados en control (nunca los cancelados)."""
    return [
        detalle
        for detalle in orden.reparaciones_detail
        if detalle.estado is EstadoReparacionDetail.COMPLETO
        and detalle.control_estado is EstadoControl.APROBADO
    ]


def contenido_comprobante_recepcion(
    orden: OrdenReparacion,
    contexto: ContextoDocumentos,
) -> ContenidoComprobanteRecepcion:
    """Comprobante de recepcion con los datos vigentes del ingreso.

    No lista Detalles ni precios: acredita la recepcion, no una
    reparacion autorizada. Informa el estado de la custodia tal como esta
    (puede emitirse con la recepcion fisica todavia sin confirmar).
    """
    recepcion = orden.recepcion
    confirmacion = recepcion.confirmacion if recepcion else None
    return ContenidoComprobanteRecepcion(
        **_datos_comunes(orden, contexto),
        estado_fisico=recepcion.datos.estado_fisico if recepcion else None,
        accesorios=list(recepcion.datos.accesorios) if recepcion else [],
        observaciones=recepcion.datos.observaciones if recepcion else None,
        notas=_notas_visibles(recepcion),
        registrado_por=(
            _usuario(contexto, recepcion.registrado_por) if recepcion else None
        ),
        registrado_en=recepcion.registrado_en if recepcion else None,
        recepcion_fisica=estado_custodia(orden),
        confirmada_por=(
            _usuario(contexto, confirmacion.usuario_id)
            if confirmacion
            else None
        ),
        confirmada_en=confirmacion.fecha if confirmacion else None,
        leyenda=(
            LEYENDA_RECEPCION_GARANTIA
            if orden.orden_origen_id
            else LEYENDA_RECEPCION
        ),
    )


def _notas_visibles(recepcion) -> list[str]:
    """Las notas posteriores que ve el cliente: nunca las internas."""
    if recepcion is None:
        return []
    return [nota.texto for nota in recepcion.notas if not nota.interna]


def _descuento_en_documento(
    orden: OrdenReparacion, subtotal: Decimal
) -> DescuentoEnDocumento | None:
    """El descuento vigente sobre ``subtotal``, si descuenta algo."""
    vigente = orden.descuento_vigente
    importe = importe_de_descuento(subtotal, vigente)
    if vigente is None or importe == 0:
        return None
    return DescuentoEnDocumento(
        descripcion=descripcion_de_descuento(vigente),
        motivo=vigente.motivo,
        importe=importe,
    )


def _salida_registrada(orden: OrdenReparacion) -> EntregaEquipo | None:
    return orden.entrega or orden.devolucion


def _resultado(orden: OrdenReparacion, tipo_entrega: TipoEntrega) -> str:
    if orden.estado_workflow is EstadoWorkflow.CANCELADA:
        resultado = "Orden cancelada: el equipo se devuelve sin reparar"
    elif finalizada_sin_reparacion(orden):
        paso = next(
            paso
            for paso in orden.historial
            if paso.process_id == "PROC-REP-069"
        )
        resultado = f"Finalizada sin reparacion ({paso.observacion})"
    elif tipo_entrega is TipoEntrega.REPARACION_TERMINADA:
        resultado = "Reparacion terminada y aprobada en control"
    else:
        resultado = "Devolucion sin reparacion"
    if orden.orden_origen_id and not _es_cobrable(orden):
        resultado += (
            f". Garantia de la Orden {orden.orden_origen_id}: sin cargo"
        )
    return resultado


def contenido_comprobante_entrega(
    orden: OrdenReparacion,
    contexto: ContextoDocumentos,
) -> ContenidoComprobanteEntrega:
    """Comprobante final: lo realizado, lo cancelado, el cobro y la entrega.

    Los Detalles cancelados figuran aparte, como no realizados y no
    cobrados. Una Orden no cobrable no muestra importes. Si la salida del
    equipo todavia no se registro (vista previa), sus datos quedan vacios.
    """
    salida = _salida_registrada(orden)
    tipo_entrega = salida.tipo if salida else tipo_de_entrega(orden)
    cobrable = _es_cobrable(orden)
    resumen = orden.resumen_pago

    def trabajo(detalle) -> dict:
        return {
            "detalle_id": detalle.id,
            "tipo_reparacion_id": detalle.tipo_reparacion_id,
            "nombre": nombre_del_trabajo(detalle, contexto.tipos),
            "precio": detalle.precio if cobrable else None,
            "detalle_origen_id": detalle.detalle_origen_id,
        }

    return ContenidoComprobanteEntrega(
        **_datos_comunes(orden, contexto),
        estado_final=orden.estado_workflow,
        tipo_entrega=tipo_entrega,
        resultado=_resultado(orden, tipo_entrega),
        fecha_entrega=salida.fecha if salida else None,
        entregado_por=(
            _usuario(contexto, salida.entregado_por) if salida else None
        ),
        recibido_por=salida.recibido_por if salida else None,
        identificacion_receptor=(
            salida.identificacion_receptor if salida else None
        ),
        observaciones_entrega=salida.observaciones if salida else None,
        trabajos_realizados=[
            TrabajoEnDocumento(**trabajo(detalle))
            for detalle in _realizados(orden)
        ],
        trabajos_cancelados=[
            TrabajoCanceladoEnDocumento(
                **trabajo(detalle),
                motivo=(
                    detalle.cancelacion.motivo if detalle.cancelacion else None
                ),
                origen_cancelacion=(
                    detalle.cancelacion.origen if detalle.cancelacion else None
                ),
            )
            for detalle in orden.reparaciones_detail
            if detalle.estado is EstadoReparacionDetail.CANCELADO
        ],
        cobrable=cobrable,
        subtotal=(
            orden.subtotal if cobrable and orden.descuento_vigente else None
        ),
        descuento=(
            _descuento_en_documento(orden, orden.subtotal)
            if cobrable
            else None
        ),
        total=orden.total if cobrable else None,
        pagado=resumen.pagado if cobrable else None,
        devuelto=resumen.devuelto if cobrable else None,
        saldo=orden.saldo if cobrable else None,
        pagos=[
            PagoEnDocumento(
                id=pago.id,
                fecha=pago.fecha,
                tipo_pago=pago.tipo_pago,
                medio=contexto.medios.get(pago.metodo, pago.metodo),
                monto=pago.monto,
                referencia=pago.referencia,
            )
            for pago in resumen.pagos
            if cobrable and pago.vigente
        ],
        devoluciones_dinero=[
            DevolucionDineroEnDocumento(
                id=devolucion.id,
                pago_id=devolucion.pago_id,
                fecha=devolucion.fecha,
                medio=contexto.medios.get(devolucion.medio, devolucion.medio),
                monto=devolucion.monto,
                motivo=devolucion.motivo,
            )
            for devolucion in resumen.devoluciones
            if cobrable
        ],
    )


def vencimiento_garantia(
    fecha_inicio: datetime | None,
    garantia_dias: int,
    zona_horaria: tzinfo,
):
    """Ultimo dia de garantia: el dia (local) de la entrega + el plazo.

    ``None`` sin entrega todavia o con un plazo de 0 dias (sin garantia).
    """
    if fecha_inicio is None or garantia_dias <= 0:
        return None
    dia_entrega = fecha_inicio.astimezone(zona_horaria).date()
    return dia_entrega + timedelta(days=garantia_dias)


def contenido_garantia(
    orden: OrdenReparacion,
    contexto: ContextoDocumentos,
) -> ContenidoGarantia:
    """Garantia de los trabajos realizados, cada uno con su plazo.

    El plazo es el snapshot de cada Detalle (``garantia_dias``): no hay una
    duracion general. Empieza con la entrega efectiva; los cancelados y no
    realizados no tienen garantia.
    """
    fecha_inicio = orden.entrega.fecha if orden.entrega else None
    return ContenidoGarantia(
        **_datos_comunes(orden, contexto),
        fecha_inicio=fecha_inicio,
        coberturas=[
            CoberturaGarantia(
                detalle_id=detalle.id,
                tipo_reparacion_id=detalle.tipo_reparacion_id,
                nombre=nombre_del_trabajo(detalle, contexto.tipos),
                garantia_dias=detalle.garantia_dias,
                vence=vencimiento_garantia(
                    fecha_inicio, detalle.garantia_dias, contexto.zona_horaria
                ),
                detalle_origen_id=detalle.detalle_origen_id,
                observaciones=detalle.observaciones,
            )
            for detalle in _realizados(orden)
        ],
        condiciones=contexto.empresa.condiciones_garantia,
        observaciones_entrega=(
            orden.entrega.observaciones if orden.entrega else None
        ),
    )


# --- Comprobante de autorizacion ---------------------------------------------


def _autorizados(
    orden: OrdenReparacion,
) -> list[tuple[ReparacionDetail, RegistroAutorizacionCliente]]:
    """Detalles con una decision AUTORIZADO vigente y sin cancelar.

    Vigente es la decision sobre la definicion actual del Detalle: si se
    redefinio, la autorizacion anterior ya no cuenta (BR-REP-029). Un
    Detalle desistido o cancelado despues de autorizarse no figura.
    """
    if not requiere_autorizacion_cliente(orden):
        return []
    autorizados = []
    for detalle in orden.reparaciones_detail:
        if detalle.estado is EstadoReparacionDetail.CANCELADO:
            continue
        vigente = decision_vigente(detalle)
        if (
            vigente is not None
            and vigente.resultado is ResultadoAutorizacion.AUTORIZADO
        ):
            autorizados.append((detalle, vigente))
    return autorizados


def _trabajos_autorizados(
    orden: OrdenReparacion, contexto: ContextoDocumentos
) -> list[TrabajoAutorizadoEnDocumento]:
    return [
        TrabajoAutorizadoEnDocumento(
            detalle_id=detalle.id,
            tipo_reparacion_id=detalle.tipo_reparacion_id,
            nombre=nombre_del_trabajo(detalle, contexto.tipos),
            precio=detalle.precio,
            detalle_origen_id=detalle.detalle_origen_id,
            version_definicion=decision.version_definicion,
            autorizado_en=decision.fecha,
            canal=decision.canal,
            registrado_por=_usuario(contexto, decision.usuario_id),
        )
        for detalle, decision in _autorizados(orden)
    ]


def contenido_comprobante_autorizacion(
    orden: OrdenReparacion,
    contexto: ContextoDocumentos,
) -> ContenidoComprobanteAutorizacion:
    """Los trabajos autorizados, cada uno con su precio y su decision.

    Con descuento vigente: el subtotal de lo autorizado, el descuento
    sobre ese subtotal y el total resultante.
    """
    trabajos = _trabajos_autorizados(orden, contexto)
    subtotal = sum((trabajo.precio for trabajo in trabajos), Decimal("0"))
    descuento = _descuento_en_documento(orden, subtotal)
    return ContenidoComprobanteAutorizacion(
        **_datos_comunes(orden, contexto),
        trabajos=trabajos,
        subtotal_autorizado=subtotal if descuento else None,
        descuento=descuento,
        total_autorizado=subtotal - (descuento.importe if descuento else 0),
        leyenda=LEYENDA_AUTORIZACION,
    )


def contenido_comprobante_ingreso(
    orden: OrdenReparacion,
    contexto: ContextoDocumentos,
) -> ContenidoComprobanteIngreso:
    """Ingreso y autorizacion en un solo documento (MVP v2).

    La recepcion (estado fisico, accesorios, observaciones del equipo,
    notas visibles, check-in y la confirmacion fisica) y los trabajos
    autorizados con su precio, el descuento y el total. Las notas internas
    nunca figuran.
    """
    recepcion = orden.recepcion
    datos = recepcion.datos if recepcion else None
    confirmacion = recepcion.confirmacion if recepcion else None
    trabajos = _trabajos_autorizados(orden, contexto)
    subtotal = sum((trabajo.precio for trabajo in trabajos), Decimal("0"))
    descuento = _descuento_en_documento(orden, subtotal)
    return ContenidoComprobanteIngreso(
        **_datos_comunes(orden, contexto),
        estado_fisico=datos.estado_fisico if datos else None,
        accesorios=list(datos.accesorios) if datos else [],
        observaciones=datos.observaciones if datos else None,
        notas=_notas_visibles(recepcion),
        checkin=datos.checkin if datos else None,
        registrado_por=(
            _usuario(contexto, recepcion.registrado_por) if recepcion else None
        ),
        recepcion_fisica=estado_custodia(orden),
        confirmada_por=(
            _usuario(contexto, confirmacion.usuario_id)
            if confirmacion
            else None
        ),
        confirmada_en=confirmacion.fecha if confirmacion else None,
        trabajos=trabajos,
        subtotal=subtotal,
        descuento=descuento,
        total=subtotal - (descuento.importe if descuento else 0),
        leyenda=LEYENDA_INGRESO,
    )


def _firma(trabajos) -> tuple:
    """Que se autorizo: Detalle, definicion autorizada y precio."""
    return tuple(
        (trabajo.detalle_id, trabajo.version_definicion, trabajo.precio)
        for trabajo in trabajos
    )


def _firma_de(contenido) -> tuple:
    """Lo autorizado y el descuento de un documento con trabajos."""
    descuento = contenido.descuento
    return (
        _firma(contenido.trabajos),
        (descuento.descripcion, descuento.importe) if descuento else None,
    )


def _firma_vigente(orden: OrdenReparacion) -> tuple:
    autorizados = _autorizados(orden)
    subtotal = sum((detalle.precio for detalle, _ in autorizados), Decimal(0))
    descuento = _descuento_en_documento(orden, subtotal)
    return (
        tuple(
            (detalle.id, decision.version_definicion, detalle.precio)
            for detalle, decision in autorizados
        ),
        (descuento.descripcion, descuento.importe) if descuento else None,
    )


def autorizados_en_el_ingreso(
    orden: OrdenReparacion,
) -> frozenset[tuple[str, int]]:
    """(Detalle, version de definicion) que autorizo el comprobante de
    ingreso. Una redefinicion posterior abre otra version: esa ya no es la
    autorizacion inicial."""
    ingreso = ultimo_documento(orden, TipoDocumento.COMPROBANTE_INGRESO)
    if ingreso is None:
        return frozenset()
    return frozenset(
        (trabajo.detalle_id, trabajo.version_definicion)
        for trabajo in ingreso.contenido.trabajos
    )


def ultimo_con_trabajos_autorizados(
    orden: OrdenReparacion,
) -> DocumentoEmitido | None:
    """El ultimo documento emitido que lista lo autorizado (ingreso o
    autorizacion): contra el se decide si hace falta una version nueva."""
    for documento in reversed(orden.documentos.emitidos):
        if documento.tipo in _CON_TRABAJOS_AUTORIZADOS:
            return documento
    return None


def comprobante_autorizacion_emitible(orden: OrdenReparacion) -> bool:
    """Hay trabajos autorizados que el ultimo comprobante no refleja.

    Sin comprobante todavia, alcanza con un trabajo autorizado. Con uno ya
    emitido, solo si cambio lo autorizado (otro trabajo autorizado, uno
    cancelado o redefinido): asi un segundo clic no lo duplica.
    """
    if (
        orden.esta_cerrada
        or orden.estado_workflow is EstadoWorkflow.CANCELADA
        or not requiere_autorizacion_cliente(orden)
    ):
        return False
    vigente = _firma_vigente(orden)
    if not vigente[0]:
        return False
    ultimo = ultimo_con_trabajos_autorizados(orden)
    return ultimo is None or _firma_de(ultimo.contenido) != vigente


def _lista(nombres: Sequence[str]) -> str:
    citados = [f"«{nombre}»" for nombre in nombres]
    if len(citados) < 2:
        return "".join(citados)
    return ", ".join(citados[:-1]) + " y " + citados[-1]


def _motivo_autorizacion(anterior, actual) -> str:
    """Motivo de una version nueva: que cambio en lo autorizado."""
    previos = {trabajo.detalle_id: trabajo for trabajo in anterior.trabajos}
    vigentes = {trabajo.detalle_id: trabajo for trabajo in actual.trabajos}
    agregados = [t.nombre for d, t in vigentes.items() if d not in previos]
    cambiados = [
        t.nombre
        for d, t in vigentes.items()
        if d in previos and _firma([t]) != _firma([previos[d]])
    ]
    quitados = [t.nombre for d, t in previos.items() if d not in vigentes]
    partes = []
    if agregados:
        partes.append(f"se autorizó {_lista(agregados)}")
    if cambiados:
        partes.append(f"cambió lo autorizado de {_lista(cambiados)}")
    if quitados:
        partes.append(
            f"{_lista(quitados)} ya no figura (cancelado o redefinido)"
        )
    if _firma_de(anterior)[1] != _firma_de(actual)[1]:
        partes.append("cambió el descuento")
    return "Cambiaron los trabajos autorizados: " + "; ".join(partes) + "."


def emitir_comprobante_autorizacion(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    contenido: ContenidoComprobanteAutorizacion,
    fecha: datetime,
) -> tuple[OrdenReparacion, DocumentoEmitido, bool]:
    """Recepcion emite el comprobante de los trabajos autorizados.

    Solo a pedido (nunca lo emite el proceso) y solo con algun trabajo
    autorizado. Si lo autorizado no cambio desde la ultima version, la
    devuelve sin crear otra (un doble clic no duplica). Si cambio, emite la
    version siguiente con el motivo calculado: las anteriores se conservan
    tal como se entregaron. Deja la accion en el historial (ACC-REP-060).
    """
    validar_alguno_de(usuario, ROLES_COMPROBANTE_AUTORIZACION)
    if not requiere_autorizacion_cliente(orden):
        raise PrecondicionInvalidaError(
            f"Una Orden {orden.origen.value} no registra la autorizacion "
            "del cliente: no emite comprobante de autorizacion."
        )
    if orden.estado_workflow is EstadoWorkflow.CANCELADA:
        raise PrecondicionInvalidaError(
            "La Orden esta cancelada: no emite comprobante de autorizacion."
        )
    if not contenido.trabajos:
        raise PrecondicionInvalidaError(
            "No hay trabajos autorizados por el cliente: el comprobante de "
            "autorizacion solo lista trabajos autorizados."
        )
    ultimo = ultimo_con_trabajos_autorizados(orden)
    if ultimo is not None and _firma_de(ultimo.contenido) == _firma_de(
        contenido
    ):
        return orden, ultimo, False

    nueva_orden, documento, creado = registrar_documento(
        orden,
        contenido=contenido,
        fecha=fecha,
        usuario_id=usuario.id,
        motivo=(
            _motivo_autorizacion(ultimo.contenido, contenido)
            if ultimo is not None
            else None
        ),
    )
    if creado:
        observacion = (
            f"{documento.id} (version {documento.version}): "
            f"{_lista([t.nombre for t in contenido.trabajos])}, total "
            f"{contenido.total_autorizado}"
        )
        if documento.motivo:
            observacion += f". {documento.motivo}"
        nueva_orden = registrar_accion_funcional(
            nueva_orden,
            accion_id=ACCION_EMITIR_COMPROBANTE_AUTORIZACION,
            accion="EMITIR_DOCUMENTO",
            fecha=fecha,
            usuario_id=usuario.id,
            observacion=observacion,
        )
    return nueva_orden, documento, creado


def emitir_comprobante_ingreso(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    contenido: ContenidoComprobanteIngreso,
    fecha: datetime,
) -> tuple[OrdenReparacion, DocumentoEmitido, bool]:
    """Emite el comprobante de ingreso y autorizacion (una sola vez).

    Lo emite el ingreso inicial de CLIENTE_EXTERNO (Recepcion), ya con la
    recepcion confirmada y los trabajos autorizados. Si ya existe, lo
    devuelve sin crear otro: un reintento no lo duplica. Las
    autorizaciones posteriores usan el comprobante de autorizacion. Deja
    ACC-REP-060 en el historial (emitir el comprobante de autorizacion; la
    recepcion ya quedo en PROC-REP-060).
    """
    validar_alguno_de(usuario, ROLES_COMPROBANTE_AUTORIZACION)
    existente = ultimo_documento(orden, TipoDocumento.COMPROBANTE_INGRESO)
    if existente is not None:
        return orden, existente, False
    if not contenido.trabajos:
        raise PrecondicionInvalidaError(
            "El comprobante de ingreso necesita al menos un trabajo "
            "autorizado."
        )
    nueva_orden, documento, creado = registrar_documento(
        orden, contenido=contenido, fecha=fecha, usuario_id=usuario.id
    )
    if creado:
        nueva_orden = registrar_accion_funcional(
            nueva_orden,
            accion_id=ACCION_EMITIR_COMPROBANTE_AUTORIZACION,
            accion="EMITIR_DOCUMENTO",
            fecha=fecha,
            usuario_id=usuario.id,
            observacion=(
                f"{documento.id} (ingreso y autorizacion): "
                f"{_lista([t.nombre for t in contenido.trabajos])}, total "
                f"{contenido.total}"
            ),
        )
    return nueva_orden, documento, creado


# --- Documentos emitidos -----------------------------------------------------


def documentos_de_tipo(
    orden: OrdenReparacion,
    tipo: TipoDocumento,
) -> list[DocumentoEmitido]:
    """Versiones emitidas de un tipo, de la primera a la ultima."""
    return [
        documento
        for documento in orden.documentos.emitidos
        if documento.tipo is tipo
    ]


def ultimo_documento(
    orden: OrdenReparacion,
    tipo: TipoDocumento,
) -> DocumentoEmitido | None:
    """La version vigente (la ultima emitida) de un tipo, si la hay."""
    versiones = documentos_de_tipo(orden, tipo)
    return versiones[-1] if versiones else None


def documento_emitido(
    orden: OrdenReparacion,
    documento_id: str,
) -> DocumentoEmitido:
    """Un documento emitido de la Orden, o ``EntidadNoEncontradaError``."""
    for documento in orden.documentos.emitidos:
        if documento.id == documento_id:
            return documento
    raise EntidadNoEncontradaError(
        f"La Orden {orden.id} no tiene el documento {documento_id}."
    )


def registrar_documento(
    orden: OrdenReparacion,
    *,
    contenido: ContenidoDocumento,
    fecha: datetime,
    usuario_id: str | None,
    motivo: str | None = None,
) -> tuple[OrdenReparacion, DocumentoEmitido, bool]:
    """Agrega un documento emitido; devuelve tambien si se creo.

    Mismo contenido que la ultima version: no se crea nada (un reintento
    no duplica). Contenido distinto con una version ya emitida: exige
    ``motivo`` y crea la version siguiente, que referencia a la anterior.
    Ninguna version se modifica ni se borra.
    """
    tipo = contenido.tipo
    ultimo = ultimo_documento(orden, tipo)
    if ultimo is not None and ultimo.contenido == contenido:
        return orden, ultimo, False
    motivo = (motivo or "").strip() or None
    if ultimo is not None and motivo is None:
        raise PrecondicionInvalidaError(
            f"Ya se emitio {ultimo.id} (version {ultimo.version}): una "
            "version nueva exige indicar el motivo."
        )

    version = len(documentos_de_tipo(orden, tipo)) + 1
    documento = DocumentoEmitido(
        id=f"{orden.id}-{SIGLA_DOCUMENTO[tipo]}-{version:02d}",
        tipo=tipo,
        orden_id=orden.id,
        version=version,
        fecha_emision=fecha,
        usuario_id=usuario_id,
        motivo=motivo,
        reemplaza_a=ultimo.id if ultimo else None,
        contenido=contenido.model_copy(deep=True),
    )
    nueva_orden = orden.model_copy(deep=True)
    nueva_orden.documentos.emitidos.append(documento)
    nueva_orden.updated_at = fecha
    return nueva_orden, documento, True


def emitir_comprobante_recepcion(
    orden: OrdenReparacion,
    *,
    usuario: Usuario,
    contenido: ContenidoComprobanteRecepcion,
    fecha: datetime,
    motivo: str | None = None,
) -> tuple[OrdenReparacion, DocumentoEmitido]:
    """Emision a pedido del comprobante de recepcion (Recepcion).

    La primera emision la hace el proceso en PROC-REP-060; antes de ese
    nodo solo hay vista previa. Despues se puede emitir una version nueva
    (por ejemplo, tras corregir los datos del ingreso o confirmar la
    recepcion), con motivo. Un reintento devuelve la version vigente.
    """
    validar_alguno_de(usuario, ROLES_RECEPCION_EQUIPO)
    if not politica_de(orden.origen).requiere_comprobante_recepcion:
        raise PrecondicionInvalidaError(
            f"Una Orden {orden.origen.value} no emite comprobante de "
            "recepcion (BR-REP-016)."
        )
    if not orden.documentos.comprobante_recepcion.generado:
        raise PrecondicionInvalidaError(
            "El comprobante de recepcion se emite al finalizar la definicion "
            "o al enviar la Orden a revision (PROC-REP-060); mientras tanto "
            "solo hay vista previa."
        )

    nueva_orden, documento, creado = registrar_documento(
        orden,
        contenido=contenido,
        fecha=fecha,
        usuario_id=usuario.id,
        motivo=motivo,
    )
    if creado:
        observacion = f"{documento.id} (version {documento.version})"
        if documento.motivo:
            observacion += f": {documento.motivo}"
        nueva_orden = registrar_accion_funcional(
            nueva_orden,
            accion_id=ACCION_EMITIR_COMPROBANTE_RECEPCION,
            accion="EMITIR_DOCUMENTO",
            fecha=fecha,
            usuario_id=usuario.id,
            observacion=observacion,
        )
    return nueva_orden, documento


def documentos_previsualizables(
    orden: OrdenReparacion,
) -> list[TipoDocumento]:
    """Documentos que tiene sentido previsualizar ahora.

    El comprobante de recepcion, si el Origen lo emite. El comprobante
    final y la garantia, cuando la Orden ya tiene resultado (o fue
    cancelada con el equipo todavia en el local) y todavia no se
    emitieron. RT_INTERNO no emite documentos al cliente.
    """
    politica = politica_de(orden.origen)
    tipos: list[TipoDocumento] = []
    # Con el comprobante de ingreso, el de recepcion ya esta incluido.
    if politica.requiere_comprobante_recepcion and not ultimo_documento(
        orden, TipoDocumento.COMPROBANTE_INGRESO
    ):
        tipos.append(TipoDocumento.COMPROBANTE_RECEPCION)
    if not politica.requiere_entrega_cliente or orden.esta_cerrada:
        return tipos
    cancelada_en_custodia = (
        orden.estado_workflow is EstadoWorkflow.CANCELADA
        and estado_custodia(orden) is EstadoCustodia.EN_CUSTODIA
    )
    entrega_emitida = ultimo_documento(
        orden, TipoDocumento.COMPROBANTE_ENTREGA
    )
    if (
        lista_para_cierre(orden) or cancelada_en_custodia
    ) and entrega_emitida is None:
        tipos.append(TipoDocumento.COMPROBANTE_ENTREGA)
    if (
        lista_para_cierre(orden)
        and not finalizada_sin_reparacion(orden)
        and ultimo_documento(orden, TipoDocumento.GARANTIA) is None
    ):
        tipos.append(TipoDocumento.GARANTIA)
    return tipos


def contenido_de(
    orden: OrdenReparacion,
    tipo: TipoDocumento,
    contexto: ContextoDocumentos,
) -> ContenidoDocumento:
    """Contenido de un documento con los datos vigentes de la Orden."""
    if tipo is TipoDocumento.COMPROBANTE_RECEPCION:
        return contenido_comprobante_recepcion(orden, contexto)
    if tipo is TipoDocumento.COMPROBANTE_ENTREGA:
        return contenido_comprobante_entrega(orden, contexto)
    if tipo is TipoDocumento.COMPROBANTE_AUTORIZACION:
        return contenido_comprobante_autorizacion(orden, contexto)
    if tipo is TipoDocumento.COMPROBANTE_INGRESO:
        return contenido_comprobante_ingreso(orden, contexto)
    return contenido_garantia(orden, contexto)
