"""Identidad del Equipo (DEC-MI-11; BR-REP-022; cierra ABI-05).

- Se busca por IMEI; si no hay coincidencias, por numero de serie; si
  tampoco, el Equipo es una identidad nueva. Coincidencia exacta (sin
  espacios ni mayusculas): nunca por similitud de nombre, modelo o
  cliente.
- Ante coincidencias, Recepcion elige el Equipo o indica «Ninguno».
- Vincular a un Equipo existente exige que comparta el IMEI o el numero de
  serie con lo que se ingresa; si los dos tienen IMEI, debe ser el mismo.
- El historial del Equipo son todas las Ordenes con su identidad: ingresos,
  reparaciones, garantias, reingresos y custodia.
"""

from collections.abc import Iterable
from datetime import datetime

from pydantic import BaseModel

from app.domain.models import Equipo, OrdenReparacion


def normalizar(valor: str | None) -> str | None:
    texto = "".join((valor or "").split()).upper()
    return texto or None


class CandidatoEquipo(BaseModel):
    equipo_id: str
    imei: str | None
    numero_serie: str | None
    marca: str
    modelo: str
    variante: str | None
    ordenes: list[str]
    ultimo_ingreso: datetime


def candidatos(
    ordenes: Iterable[OrdenReparacion],
    *,
    imei: str | None,
    numero_serie: str | None,
) -> tuple[str | None, list[CandidatoEquipo]]:
    """(criterio, candidatos): por IMEI y, si no hay, por numero de serie."""
    ordenes = list(ordenes)
    imei, numero_serie = normalizar(imei), normalizar(numero_serie)
    for criterio, valor, campo in (
        ("IMEI", imei, "imei"),
        ("NUMERO_SERIE", numero_serie, "numero_serie"),
    ):
        if valor is None:
            continue
        coincidentes = [
            o for o in ordenes if normalizar(getattr(o.equipo, campo)) == valor
        ]
        if coincidentes:
            return criterio, _agrupar(coincidentes)
    return None, []


def _agrupar(ordenes: list[OrdenReparacion]) -> list[CandidatoEquipo]:
    por_equipo: dict[str, list[OrdenReparacion]] = {}
    for orden in ordenes:
        por_equipo.setdefault(orden.equipo.id, []).append(orden)
    resultado = []
    for equipo_id, propias in por_equipo.items():
        propias.sort(key=lambda o: o.created_at)
        ultima = propias[-1]
        resultado.append(
            CandidatoEquipo(
                equipo_id=equipo_id,
                imei=ultima.equipo.imei,
                numero_serie=ultima.equipo.numero_serie,
                marca=ultima.equipo.marca,
                modelo=ultima.equipo.modelo,
                variante=ultima.equipo.variante,
                ordenes=[o.id for o in propias],
                ultimo_ingreso=ultima.created_at,
            )
        )
    resultado.sort(key=lambda c: c.ultimo_ingreso, reverse=True)
    return resultado


def comparte_identidad(equipo: Equipo, existente: Equipo) -> bool:
    """El Equipo ingresado puede ser ``existente``: comparten IMEI o numero
    de serie, y si los dos tienen IMEI es el mismo."""
    imei, imei_existente = normalizar(equipo.imei), normalizar(existente.imei)
    if imei and imei_existente:
        return imei == imei_existente
    serie = normalizar(equipo.numero_serie)
    return serie is not None and serie == normalizar(existente.numero_serie)
