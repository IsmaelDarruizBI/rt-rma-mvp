"""Administracion de catalogos con auditoria (DC23, DC23AUD, BR-REP-040).

Reglas puras: quien administra, que se valida y que cambios se auditan. La
persistencia (el catalogo y su auditoria en la misma transaccion) es del
repository.

- Permisos configurables (CFG-03): ``TIPO_REPARACION_GESTIONAR`` para el
  Tipo y ``PRECIOS_GESTIONAR`` para su precio (D3: un alta fija el precio,
  asi que exige los dos); ``MESA_TIPOS_GESTIONAR`` para las Mesas.
- Un Tipo de Reparacion no se borra: se desactiva. Su codigo no cambia y
  ``TR-OTROS`` esta reservado.
- Cada campo que cambia deja un ``CambioConfiguracion`` con el valor
  anterior y el nuevo; un pedido sin cambios se rechaza.
- Lo ya registrado no cambia: los Detalles guardan su copia (BR-REP-015).
"""

from collections.abc import Collection, Iterable
from datetime import datetime
from decimal import Decimal
from enum import Enum

from app.domain.models import (
    TIPO_REPARACION_OTROS,
    CambioConfiguracion,
    EntidadConfiguracion,
    TipoReparacion,
    Usuario,
)

from . import permisos
from .autorizacion import validar_alguno_de
from .exceptions import PrecondicionInvalidaError

ROLES_ADMINISTRACION_CONFIGURACION = permisos.CONFIGURACION_ADMINISTRAR
ROLES_TIPO_REPARACION = permisos.TIPO_REPARACION_GESTIONAR
ROLES_PRECIOS = permisos.PRECIOS_GESTIONAR
ROLES_MESA_TIPOS = permisos.MESA_TIPOS_GESTIONAR
CAMPOS_TIPO = (
    "nombre",
    "precio",
    "puntaje",
    "garantia_dias",
    "garantia_con_checkin",
    "garantia_sin_checkin",
    "politica_garantia_rma",
    "activo",
)
CAMPO_TIPOS_HABILITADOS = "tipos_habilitados"


def texto(valor: object) -> str | None:
    """El valor como lo guarda la auditoria."""
    if valor is None:
        return None
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, Decimal):
        return f"{valor:.2f}"
    if isinstance(valor, Enum):
        return valor.value
    return str(valor)


def _validar_tipo(tipo: TipoReparacion) -> None:
    if tipo.id.upper() == TIPO_REPARACION_OTROS:
        raise PrecondicionInvalidaError(
            f"{TIPO_REPARACION_OTROS} esta reservado para la reparacion no "
            "tipificada: no se administra como un Tipo del catalogo."
        )
    if not tipo.nombre.strip():
        raise PrecondicionInvalidaError(
            "El Tipo de Reparacion necesita nombre."
        )
    if (
        tipo.precio < 0
        or tipo.puntaje < 0
        or tipo.garantia_dias < 0
        or tipo.garantia_con_checkin < 0
        or tipo.garantia_sin_checkin < 0
    ):
        raise PrecondicionInvalidaError(
            "Precio, puntaje y garantia no pueden ser negativos."
        )


def cambios_de_tipo(
    anterior: TipoReparacion | None,
    nuevo: TipoReparacion,
    *,
    usuario: Usuario,
    fecha: datetime,
) -> list[CambioConfiguracion]:
    """Los cambios auditables de un alta (``anterior`` None) o una edicion."""
    validar_alguno_de(usuario, ROLES_TIPO_REPARACION)
    if nuevo.precio != nuevo.precio.quantize(Decimal("0.01")):
        # QA B, M1: la base guarda dos decimales; uno mas cambiaria el
        # precio por redondeo sin pasar por PRECIOS_GESTIONAR.
        raise PrecondicionInvalidaError(
            "El precio admite hasta dos decimales."
        )
    if anterior is None or texto(anterior.precio) != texto(nuevo.precio):
        # D3: fijar o cambiar el precio es aparte.
        validar_alguno_de(usuario, ROLES_PRECIOS)
    _validar_tipo(nuevo)
    if anterior is not None and anterior.id != nuevo.id:
        raise PrecondicionInvalidaError("El codigo de un Tipo no cambia.")
    cambios = [
        CambioConfiguracion(
            entidad=EntidadConfiguracion.TIPO_REPARACION,
            clave=nuevo.id,
            campo=campo,
            valor_anterior=(
                texto(getattr(anterior, campo)) if anterior else None
            ),
            valor_nuevo=texto(getattr(nuevo, campo)),
            usuario_id=usuario.id,
            fecha=fecha,
        )
        for campo in CAMPOS_TIPO
        if (anterior is None and texto(getattr(nuevo, campo)) is not None)
        or (
            anterior is not None
            and texto(getattr(anterior, campo)) != texto(getattr(nuevo, campo))
        )
    ]
    if not cambios:
        raise PrecondicionInvalidaError(
            f"El Tipo {nuevo.id} ya tiene esos valores: no hay cambios."
        )
    return cambios


def cambio_de_tipos_habilitados(
    estacion_id: str,
    anteriores: Collection[str],
    nuevos: Collection[str],
    *,
    tipos_existentes: Iterable[TipoReparacion],
    usuario: Usuario,
    fecha: datetime,
) -> CambioConfiguracion:
    """Los Tipos que una Mesa de trabajo puede trabajar (BR-REP-011)."""
    validar_alguno_de(usuario, ROLES_MESA_TIPOS)
    conocidos = {tipo.id for tipo in tipos_existentes}
    desconocidos = sorted(set(nuevos) - conocidos)
    if desconocidos:
        raise PrecondicionInvalidaError(
            f"No existen los Tipos de Reparacion {', '.join(desconocidos)}."
        )
    antes = ", ".join(sorted(set(anteriores))) or None
    despues = ", ".join(sorted(set(nuevos))) or None
    if antes == despues:
        raise PrecondicionInvalidaError(
            f"La Mesa {estacion_id} ya tiene esos Tipos: no hay cambios."
        )
    return CambioConfiguracion(
        entidad=EntidadConfiguracion.MESA_TRABAJO,
        clave=estacion_id,
        campo=CAMPO_TIPOS_HABILITADOS,
        valor_anterior=antes,
        valor_nuevo=despues,
        usuario_id=usuario.id,
        fecha=fecha,
    )
