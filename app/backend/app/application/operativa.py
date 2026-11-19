"""Motivos, parametros y retiro demorado (DEC-MI-13, 14 y 15).

La administracion (alta y edicion de motivos, cambio de parametros) es de
Administracion y sobre PostgreSQL, con auditoria. La consulta de motivos y
el plazo vigente valen en los dos modos (en JSON, los valores iniciales).
"""

import re
from decimal import Decimal

from app.domain.models import Insumo, MedioPago, OrdenReparacion
from app.domain.models.lotes import ControlInsumo
from app.domain.models.operativa import (
    PARAMETRO_PLAZO_RETIRO,
    PARAMETROS_INICIALES,
    PREFIJO_MOTIVO,
    MotivoOperativo,
    TipoMotivo,
)
from app.services import permisos
from app.services.autorizacion import validar_alguno_de
from app.services.exceptions import (
    CodigoDuplicadoError,
    EntidadNoEncontradaError,
    PrecondicionInvalidaError,
)
from app.services.lotes import cambio_de_control
from app.services.operativa import (
    cambio_de_parametro,
    cambio_de_recargo,
    cambios_de_insumo,
    cambios_de_motivo,
    registrar_seguimiento_retiro,
    texto_de_motivo,
)

from .codigos import con_reintento_de_codigo
from .contexto import ApplicationContext
from .lotes import estado_de_lotes
from .modificacion import orden_para_modificar

# El formato de MotivoOperativo.codigo, validado antes de reservar nada.
CODIGO_MOTIVO = re.compile(r"[A-Z0-9][A-Z0-9_-]*")


def _editable(contexto: ApplicationContext):
    if not contexto.operativa.editable:
        raise PrecondicionInvalidaError(
            "La configuracion se administra sobre la base PostgreSQL (DC23); "
            "en el modo JSON es de solo lectura."
        )
    return contexto.operativa


def listar_motivos(
    contexto: ApplicationContext, tipo: TipoMotivo | None = None
) -> list[MotivoOperativo]:
    with contexto.lectura():
        return contexto.operativa.listar_motivos(tipo)


def resolver_motivo(
    contexto: ApplicationContext,
    tipo: TipoMotivo,
    codigo: str | None,
    descripcion: str | None,
) -> str:
    motivos = listar_motivos(contexto, tipo) if codigo else []
    return texto_de_motivo(motivos, tipo, codigo, descripcion)


def guardar_motivo(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    tipo: TipoMotivo,
    nombre: str,
    activo: bool = True,
    requiere_descripcion: bool = False,
    codigo: str | None = None,
    nuevo: bool,
) -> MotivoOperativo:
    """Alta o edicion de un motivo, con auditoria.

    CFG-01: en el alta el codigo es opcional; sin codigo lo genera la base
    (``CANC-NNN`` o ``INT-NNN`` segun el tipo). Uno informado se respeta,
    en mayusculas, si no existe.
    """
    repositorio = _editable(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    # El permiso antes de reservar un codigo: un rechazo no consume numeros.
    validar_alguno_de(usuario, permisos.MOTIVO_GESTIONAR)
    codigo = (codigo or "").strip().upper() or None
    if not nuevo and codigo is None:
        raise PrecondicionInvalidaError("Falta el codigo del motivo a editar.")
    if codigo is not None and not CODIGO_MOTIVO.fullmatch(codigo):
        raise PrecondicionInvalidaError(
            f"El codigo {codigo} no es valido: solo letras, numeros, "
            "guiones y guiones bajos."
        )
    if not nombre.strip():
        raise PrecondicionInvalidaError("El motivo necesita un nombre.")
    codigo_informado = codigo

    def intento():
        codigo = codigo_informado
        with contexto.transaccion():
            existentes = {m.codigo: m for m in repositorio.listar_motivos()}
            anterior = None
            if not nuevo:
                anterior = existentes.get(codigo)
                if anterior is None:
                    raise EntidadNoEncontradaError(
                        f"No existe el motivo {codigo}"
                    )
            elif codigo is None:
                codigo = repositorio.reservar_codigo(PREFIJO_MOTIVO[tipo])
            elif codigo in existentes:
                raise CodigoDuplicadoError(f"Ya existe el motivo {codigo}.")
            motivo = MotivoOperativo(
                codigo=codigo,
                tipo=tipo,
                nombre=nombre.strip(),
                activo=activo,
                requiere_descripcion=requiere_descripcion,
            )
            cambios = cambios_de_motivo(
                anterior, motivo, usuario=usuario, fecha=fecha
            )
            repositorio.guardar_motivo(motivo, nuevo=nuevo, cambios=cambios)
        return motivo

    return con_reintento_de_codigo(
        intento, generado=nuevo and codigo_informado is None
    )


def parametros(contexto: ApplicationContext) -> dict[str, str]:
    with contexto.lectura():
        return {**PARAMETROS_INICIALES, **contexto.operativa.parametros()}


def plazo_retiro_dias(contexto: ApplicationContext) -> int:
    valor = parametros(contexto).get(PARAMETRO_PLAZO_RETIRO, "30")
    return int(valor) if valor.isdigit() else 30


def guardar_parametro(
    contexto: ApplicationContext, *, usuario_id: str, clave: str, valor: str
) -> dict[str, str]:
    repositorio = _editable(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with contexto.transaccion():
        actuales = repositorio.parametros()
        if clave not in actuales:
            raise EntidadNoEncontradaError(f"No existe el parametro {clave}")
        cambio = cambio_de_parametro(
            clave, actuales[clave], valor, usuario=usuario, fecha=fecha
        )
        repositorio.guardar_parametro(clave, cambio.valor_nuevo, cambio)
    return parametros(contexto)


def guardar_recargo_medio_pago(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    medio_id: str,
    porcentaje: Decimal,
) -> MedioPago:
    """UX-08: Administracion configura el recargo de un medio de pago, con
    auditoria. Los pagos registrados no se recalculan."""
    repositorio = _editable(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with contexto.transaccion():
        medio = contexto.catalogos.obtener_medio_pago(medio_id)
        cambio = cambio_de_recargo(
            medio, porcentaje, usuario=usuario, fecha=fecha
        )
        repositorio.guardar_recargo_medio_pago(medio.id, porcentaje, cambio)
    return medio.model_copy(update={"recargo_porcentaje": porcentaje})


def registrar_seguimiento(
    contexto: ApplicationContext,
    *,
    orden_id: str,
    usuario_id: str,
    nota: str,
    canal: str | None = None,
) -> OrdenReparacion:
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with orden_para_modificar(contexto, orden_id) as orden:
        orden = registrar_seguimiento_retiro(
            orden, usuario=usuario, fecha=fecha, nota=nota, canal=canal
        )
        contexto.ordenes.guardar(orden)
    return orden


def guardar_insumo(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    clave: str | None = None,
    codigo: str | None = None,
    nombre: str,
    unidad: str | None,
    activo: bool,
    nuevo: bool,
    control: ControlInsumo | None = None,
    precio: Decimal | None = None,
) -> Insumo:
    """Alta o edicion de un insumo (DEC-MI-13), con auditoria. El stock de
    un insumo nuevo empieza en cero: entra con movimientos de inventario.

    CFG-01 (D4): en el alta el identificador y el codigo son opcionales.
    Sin identificador lo genera la base (``INS-NNN``); sin codigo se usa el
    identificador. Los informados (clientes anteriores, scripts) se
    respetan si no existen, sin distinguir mayusculas.
    """
    repositorio = _editable(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    validar_alguno_de(usuario, permisos.INSUMO_GESTIONAR)
    if nuevo and precio is not None:
        # D3, antes de reservar el codigo: un rechazo no consume numeros.
        validar_alguno_de(usuario, permisos.PRECIOS_GESTIONAR)
    clave = (clave or "").strip() or None
    codigo = (codigo or "").strip() or None
    if not nuevo and clave is None:
        raise PrecondicionInvalidaError("Falta el identificador del insumo.")
    clave_informado = clave
    codigo_informado = codigo

    def intento():
        clave = clave_informado
        codigo = codigo_informado
        with contexto.transaccion():
            existentes = {i.id: i for i in contexto.catalogos.listar_insumos()}
            anterior = None
            if not nuevo:
                anterior = existentes.get(clave)
                if anterior is None:
                    raise EntidadNoEncontradaError(
                        f"No existe el insumo {clave}"
                    )
                codigo = codigo or anterior.codigo
                if codigo != anterior.codigo:
                    # Como en la base (rma_backend no actualiza el codigo): el
                    # codigo identifica al insumo en lo registrado.
                    raise PrecondicionInvalidaError(
                        "El codigo de un insumo no cambia: da de alta otro."
                    )
            else:
                if clave is None:
                    clave = repositorio.reservar_codigo("INS")
                elif any(
                    i.id.upper() == clave.upper() for i in existentes.values()
                ):
                    raise CodigoDuplicadoError(f"Ya existe el insumo {clave}.")
                codigo = codigo or clave
            if any(
                i.codigo.upper() == codigo.upper() and i.id != clave
                for i in existentes.values()
            ):
                raise CodigoDuplicadoError(
                    f"Otro insumo ya usa el codigo {codigo}."
                )
            insumo = Insumo(
                id=clave,
                codigo=codigo,
                nombre=nombre.strip(),
                unidad=(unidad or "").strip() or None,
                stock_fisico=anterior.stock_fisico if anterior else 0,
                activo=activo,
                control=control
                or (anterior.control if anterior else ControlInsumo.SIN_LOTE),
                precio=precio,
            )
            if anterior is not None and insumo.control is not anterior.control:
                # DEC-MI-10: transicion controlada del stock existente.
                contexto.catalogos.bloquear_insumos([anterior.id])
                cambio_de_control(
                    anterior,
                    insumo.control,
                    estado_de_lotes(contexto, anterior),
                )
            cambios = cambios_de_insumo(
                anterior, insumo, usuario=usuario, fecha=fecha
            )
            repositorio.guardar_insumo(insumo, nuevo=nuevo, cambios=cambios)
        return insumo

    return con_reintento_de_codigo(
        intento, generado=nuevo and clave_informado is None
    )
