"""Identificacion del Equipo para consultar antecedentes (BR-REP-022)."""

from app.domain.models import OrdenReparacion


def _normalizar(valor: str | None) -> str | None:
    texto = "".join((valor or "").split()).upper()
    return texto or None


def coincide_identificacion(
    orden: OrdenReparacion, imei: str | None, numero_serie: str | None
) -> bool:
    """El Equipo de la Orden tiene ese IMEI o ese numero de serie (sin
    espacios ni mayusculas). Un dato vacio nunca coincide."""
    imei, numero_serie = _normalizar(imei), _normalizar(numero_serie)
    return (imei is not None and _normalizar(orden.equipo.imei) == imei) or (
        numero_serie is not None
        and _normalizar(orden.equipo.numero_serie) == numero_serie
    )
