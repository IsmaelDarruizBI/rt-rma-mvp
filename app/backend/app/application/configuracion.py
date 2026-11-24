"""Administracion de catalogos con auditoria (DC23, DC23AUD, BR-REP-040).

Tipos de Reparacion (alta, edicion de precio, puntaje, garantia y nombre,
desactivacion) y Tipos habilitados de cada Mesa de trabajo. Cada comando
guarda el cambio y su auditoria en la misma transaccion. Solo con
PostgreSQL: DC23 pide la administracion sobre la persistencia definitiva.

DEC-AJ-12: precio unico o por modelo de cada Tipo, sus precios por modelo
(``guardar_precios_modelo``, en bloque y todo o nada) y el alta y la
edicion de los modelos de equipo (``guardar_modelo_equipo``).
"""

from collections.abc import Collection, Sequence
from decimal import Decimal
from uuid import uuid4

from pydantic import ValidationError

from app.domain.models import (
    CambioConfiguracion,
    EntidadConfiguracion,
    ImportacionPrecios,
    ModeloEquipo,
    PoliticaGarantiaRma,
    PrecioTipoModelo,
    TipoReparacion,
)
from app.repositories.configuracion import ConfiguracionRepository
from app.services.autorizacion import validar_alguno_de
from app.services.configuracion import (
    ROLES_MODELOS,
    ROLES_PRECIOS,
    ROLES_TIPO_REPARACION,
    cambio_de_tipos_habilitados,
    cambios_de_modelo,
    cambios_de_precios_modelo,
    cambios_de_tipo,
    insumos_necesarios,
)
from app.services.exceptions import (
    CodigoDuplicadoError,
    EntidadNoEncontradaError,
    PrecondicionInvalidaError,
)

from .codigos import con_reintento_de_codigo
from .contexto import ApplicationContext


def _repositorio(contexto: ApplicationContext) -> ConfiguracionRepository:
    if contexto.configuracion is None:
        raise PrecondicionInvalidaError(
            "La administracion de catalogos funciona sobre la base "
            "PostgreSQL (DC23); en el modo JSON los catalogos son de solo "
            "lectura."
        )
    return contexto.configuracion


class _Conservar:
    """Un campo que el cliente no informo (CFG-06)."""

    def __repr__(self) -> str:
        return "CONSERVAR"


CONSERVAR = _Conservar()
GARANTIA_CON_CHECKIN_INICIAL = 90
GARANTIA_SIN_CHECKIN_INICIAL = 30


def guardar_tipo_reparacion(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    codigo: str | None = None,
    nombre: str,
    precio: Decimal,
    puntaje: int,
    garantia_dias: int | _Conservar = CONSERVAR,
    garantia_con_checkin: int | _Conservar = CONSERVAR,
    garantia_sin_checkin: int | _Conservar = CONSERVAR,
    politica_garantia_rma: PoliticaGarantiaRma | None | _Conservar = CONSERVAR,
    activo: bool = True,
    precio_por_modelo: bool | _Conservar = CONSERVAR,
    nuevo: bool,
) -> TipoReparacion:
    """Alta o edicion de un Tipo, con auditoria.

    CFG-01: en el alta el codigo es opcional. Sin codigo lo genera la base
    (``TR-NNN``); un codigo informado (clientes anteriores, scripts) se
    respeta si no existe otro igual sin distinguir mayusculas.

    CFG-06 (DF-1 y DF-2): la pantalla solo muestra los plazos con y sin
    check-in. Un campo de garantia que no viene (``CONSERVAR``) conserva
    el valor del Tipo en la edicion; en el alta, el plazo generico
    (``garantia_dias``, el que rige sin check-in registrado) toma el plazo
    con check-in, los plazos 90 y 30 dias y la politica RMA queda sin
    definir. Lo que manda un cliente anterior se respeta.

    DEC-AJ-12: ``precio_por_modelo`` (un precio) se conserva si no viene;
    en el alta, precio unico. Los precios por modelo no se pierden al
    volver al precio unico: dejan de usarse.
    """
    repositorio = _repositorio(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    # El permiso antes de reservar un codigo: un rechazo no consume numeros.
    validar_alguno_de(usuario, ROLES_TIPO_REPARACION)
    if nuevo:
        validar_alguno_de(usuario, ROLES_PRECIOS)  # D3: el alta fija precio
    codigo = (codigo or "").strip() or None
    if not nuevo and codigo is None:
        raise PrecondicionInvalidaError("Falta el codigo del Tipo a editar.")
    codigo_informado = codigo

    def intento():
        codigo = codigo_informado
        with contexto.transaccion():
            anterior = None
            if not nuevo:
                anterior = contexto.catalogos.obtener_tipo_reparacion(codigo)
            elif codigo is None:
                codigo = repositorio.reservar_codigo("TR")
            elif any(
                t.id.upper() == codigo.upper()
                for t in contexto.catalogos.listar_tipos_reparacion()
            ):
                raise CodigoDuplicadoError(
                    f"Ya existe un Tipo de Reparacion {codigo}."
                )

            def elegir(valor, campo, inicial):
                if valor is not CONSERVAR:
                    return valor
                return getattr(anterior, campo) if anterior else inicial

            con_checkin = elegir(
                garantia_con_checkin,
                "garantia_con_checkin",
                GARANTIA_CON_CHECKIN_INICIAL,
            )
            tipo = TipoReparacion(
                id=codigo,
                nombre=nombre.strip(),
                precio=precio,
                puntaje=puntaje,
                garantia_dias=elegir(
                    garantia_dias, "garantia_dias", con_checkin
                ),
                garantia_con_checkin=con_checkin,
                garantia_sin_checkin=elegir(
                    garantia_sin_checkin,
                    "garantia_sin_checkin",
                    GARANTIA_SIN_CHECKIN_INICIAL,
                ),
                politica_garantia_rma=elegir(
                    politica_garantia_rma, "politica_garantia_rma", None
                ),
                activo=activo,
                precio_por_modelo=elegir(
                    precio_por_modelo, "precio_por_modelo", False
                ),
                precios_modelo=anterior.precios_modelo if anterior else {},
            )
            cambios = cambios_de_tipo(
                anterior, tipo, usuario=usuario, fecha=fecha
            )
            repositorio.guardar_tipo_reparacion(
                tipo, nuevo=nuevo, cambios=cambios
            )
        return tipo

    return con_reintento_de_codigo(
        intento, generado=nuevo and codigo_informado is None
    )


def habilitar_tipos_en_mesa(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    estacion_id: str,
    tipo_ids: Collection[str],
) -> CambioConfiguracion:
    repositorio = _repositorio(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    with contexto.transaccion():
        contexto.catalogos.obtener_estacion(estacion_id)
        anteriores = [
            c.tipo_reparacion_id
            for c in contexto.catalogos.listar_tipo_reparacion_estaciones()
            if c.estacion_id == estacion_id
        ]
        cambio = cambio_de_tipos_habilitados(
            estacion_id,
            anteriores,
            tipo_ids,
            tipos_existentes=contexto.catalogos.listar_tipos_reparacion(),
            usuario=usuario,
            fecha=fecha,
        )
        repositorio.guardar_tipos_de_mesa(estacion_id, set(tipo_ids), cambio)
    return cambio


def historial_de_cambios(
    contexto: ApplicationContext,
    *,
    entidad: EntidadConfiguracion | None = None,
    clave: str | None = None,
) -> list[CambioConfiguracion]:
    """La auditoria de la configuracion (la ruta la limita a
    Administracion). Sin PostgreSQL no hay cambios registrados."""
    if contexto.configuracion is None:
        return []
    return contexto.configuracion.listar_cambios(entidad=entidad, clave=clave)


# --- Modelos de equipo (DEC-AJ-12, D-12.5) ----------------------------------


def listar_modelos_administrables(
    contexto: ApplicationContext,
) -> list[ModeloEquipo]:
    """Todos los modelos, activos o no, en el orden del catalogo."""
    if contexto.modelos_equipo is None:
        return []
    return contexto.modelos_equipo.listar_modelos()


def guardar_modelo_equipo(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    codigo: str | None = None,
    marca: str,
    modelo: str,
    variante: str | None = None,
    numeros_modelo: Sequence[str] = (),
    activo: bool = True,
    nuevo: bool,
) -> ModeloEquipo:
    """Alta o edicion de un modelo de equipo, con auditoria.

    En el alta el codigo lo genera la base (``MOD-NNNN``, siguiendo al
    mayor existente); uno informado se respeta si es valido y no existe.
    Un modelo no se borra: se desactiva y deja de ofrecerse en el ingreso.
    """
    repositorio = _repositorio(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    validar_alguno_de(usuario, ROLES_MODELOS)
    codigo = (codigo or "").strip().upper() or None
    if not nuevo and codigo is None:
        raise PrecondicionInvalidaError("Falta el codigo del modelo a editar.")
    codigo_informado = codigo

    def limpio(texto: str | None) -> str | None:
        return " ".join((texto or "").split()) or None

    def intento():
        codigo = codigo_informado
        with contexto.transaccion():
            existentes = listar_modelos_administrables(contexto)
            anterior = None
            if not nuevo:
                anterior = next(
                    (m for m in existentes if m.id == codigo), None
                )
                if anterior is None:
                    raise EntidadNoEncontradaError(
                        f"No existe el modelo de equipo {codigo}"
                    )
            elif codigo is None:
                codigo = repositorio.reservar_codigo("MOD")
            elif any(m.id == codigo for m in existentes):
                raise CodigoDuplicadoError(f"Ya existe el modelo {codigo}.")
            try:
                nuevo_modelo = ModeloEquipo(
                    id=codigo,
                    marca=limpio(marca) or "",
                    modelo=limpio(modelo) or "",
                    variante=limpio(variante),
                    numeros_modelo=tuple(
                        n for n in (limpio(x) for x in numeros_modelo) if n
                    ),
                    activo=activo,
                )
            except ValidationError as error:
                raise PrecondicionInvalidaError(
                    "El modelo necesita marca y modelo, y un codigo con "
                    "formato MOD-0001."
                ) from error
            cambios = cambios_de_modelo(
                anterior,
                nuevo_modelo,
                existentes=existentes,
                usuario=usuario,
                fecha=fecha,
            )
            repositorio.guardar_modelo_equipo(
                nuevo_modelo, nuevo=nuevo, cambios=cambios
            )
        return nuevo_modelo

    return con_reintento_de_codigo(
        intento, generado=nuevo and codigo_informado is None
    )


# --- Precios por modelo (DEC-AJ-12, D-12.1) ---------------------------------


def guardar_precios_modelo(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    precios: Sequence[PrecioTipoModelo],
    importacion: ImportacionPrecios | None = None,
) -> list[CambioConfiguracion]:
    """Fija o retira precios por modelo en bloque, con auditoria, en una
    transaccion: todo o nada. Devuelve los cambios registrados.

    La edicion individual de Configuracion y la importacion masiva
    (DEC-AJ-13) usan este mismo comando. Las Ordenes no cambian: cada
    Detalle guarda su copia del precio.

    Con ``importacion`` (DEC-AJ-13) se registra la importacion en la misma
    transaccion y cada cambio de la auditoria lleva su identificador; los
    precios nuevos y actualizados se cuentan sobre los cambios que se
    escriben.
    """
    repositorio = _repositorio(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = importacion.fecha if importacion else contexto.ahora()
    validar_alguno_de(usuario, ROLES_PRECIOS)
    with contexto.transaccion():
        tipos = {
            tipo.id: tipo
            for tipo in contexto.catalogos.listar_tipos_reparacion()
        }
        modelos = {
            modelo.id: modelo
            for modelo in listar_modelos_administrables(contexto)
        }
        efectivos, cambios = cambios_de_precios_modelo(
            precios,
            tipos=tipos,
            modelos=modelos,
            usuario=usuario,
            fecha=fecha,
        )
        if importacion is not None:
            nuevos = sum(1 for c in cambios if c.valor_anterior is None)
            repositorio.registrar_importacion_precios(
                importacion.model_copy(
                    update={
                        "nuevos": nuevos,
                        "actualizados": len(cambios) - nuevos,
                    }
                )
            )
            cambios = [
                c.model_copy(update={"importacion_id": importacion.id})
                for c in cambios
            ]
        repositorio.guardar_precios_modelo(efectivos, cambios)
    return cambios


# --- Insumos necesarios de un Tipo (DEC-AJ-14, D-14.4) ----------------------


def guardar_insumos_necesarios(
    contexto: ApplicationContext,
    *,
    usuario_id: str,
    tipo_reparacion_id: str,
    previstos: Sequence[tuple[str, Decimal]],
    requisitos: Sequence[tuple[str, Decimal]],
) -> list[CambioConfiguracion]:
    """«Insumos necesarios» de un Tipo: sus insumos previstos concretos y
    sus requisitos por categoria, en bloque y con auditoria
    (``TIPO_REPARACION_GESTIONAR``). Las Ordenes no cambian: lo ya
    reservado o consumido sigue igual, y un Detalle con la pieza elegida
    trabaja con su eleccion; los Detalles pendientes leen los requisitos
    vigentes. Devuelve los cambios registrados."""
    repositorio = _repositorio(contexto)
    usuario = contexto.catalogos.obtener_usuario(usuario_id)
    fecha = contexto.ahora()
    validar_alguno_de(usuario, ROLES_TIPO_REPARACION)
    with contexto.transaccion():
        tipo = contexto.catalogos.obtener_tipo_reparacion(tipo_reparacion_id)
        actuales = [
            p
            for p in contexto.catalogos.listar_tipo_reparacion_insumos()
            if p.tipo_reparacion_id == tipo.id
        ]
        efectivos, todos, cambios = insumos_necesarios(
            tipo,
            previstos_actuales=actuales,
            requisitos_actuales=(
                contexto.catalogos.listar_tipo_reparacion_requisitos()
            ),
            previstos=previstos,
            requisitos=requisitos,
            insumos={i.id: i for i in contexto.catalogos.listar_insumos()},
            categorias={
                c.id: c for c in contexto.operativa.listar_categorias_insumo()
            },
            usuario=usuario,
            fecha=fecha,
            nuevo_id=lambda: str(uuid4()),
        )
        repositorio.guardar_insumos_necesarios(
            tipo.id, efectivos, todos, cambios
        )
    return cambios
