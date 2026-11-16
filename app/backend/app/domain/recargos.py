"""Recargo por medio de pago (DEC-UX-08, ABI-44 y ABI-45).

Reglas puras, sin persistencia:

- ``recargo_de``: el recargo de un cobro, al centavo (mitad hacia arriba).
- ``distribuir``: reparte un importe entre partes con peso, en centavos
  exactos (metodo del resto mayor): la suma de las partes es siempre el
  importe y, ante un empate en el resto, gana la parte que viene antes
  (el orden de los Detalles), asi el resultado es deterministico.
- ``recargo_a_devolver``: la parte del recargo de un pago que acompana a
  una devolucion de su importe.

El saldo de la Orden no cambia: se calcula siempre sobre los importes
(``monto``); el recargo se cobra y se devuelve junto con ellos.
"""

from collections.abc import Sequence
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

CENTAVO = Decimal("0.01")
CERO = Decimal("0")


def sin_ceros(valor: Decimal) -> Decimal:
    """El mismo importe sin ceros decimales de mas (200, 6.7), como lo
    devuelve PostgreSQL."""
    if valor == valor.to_integral_value():
        return valor.quantize(Decimal(1))
    return valor.normalize()


def recargo_de(monto: Decimal, porcentaje: Decimal) -> Decimal:
    """El recargo de un cobro, redondeado al centavo (mitad hacia arriba)."""
    if porcentaje <= 0 or monto <= 0:
        return CERO
    return sin_ceros(
        (monto * porcentaje / Decimal("100")).quantize(
            CENTAVO, rounding=ROUND_HALF_UP
        )
    )


def distribuir(
    importe: Decimal, pesos: Sequence[tuple[str, Decimal]]
) -> list[tuple[str, Decimal]]:
    """Reparte ``importe`` en proporcion a ``pesos`` (clave, peso).

    Solo cuentan los pesos positivos. Sin importe o sin pesos no hay
    reparto (lista vacia). Las partes en cero no se devuelven.
    """
    validos = [(clave, peso) for clave, peso in pesos if peso > 0]
    if importe <= 0 or not validos:
        return []
    centavos = int((importe / CENTAVO).to_integral_value())
    total = sum(peso for _, peso in validos)
    exactas = [centavos * peso / total for _, peso in validos]
    pisos = [int(x.to_integral_value(rounding=ROUND_DOWN)) for x in exactas]
    faltan = centavos - sum(pisos)
    # Resto mayor; ante un empate, el que viene antes.
    orden = sorted(
        range(len(validos)), key=lambda i: (-(exactas[i] - pisos[i]), i)
    )
    for i in orden[:faltan]:
        pisos[i] += 1
    return [
        (clave, sin_ceros(Decimal(partes) * CENTAVO))
        for (clave, _), partes in zip(validos, pisos, strict=True)
        if partes > 0
    ]


def recargo_a_devolver(
    *,
    monto_pago: Decimal,
    recargo_pago: Decimal,
    devuelto_antes: Decimal,
    recargo_devuelto_antes: Decimal,
    monto: Decimal,
) -> Decimal:
    """La parte del recargo de un pago que se devuelve con ``monto``.

    Proporcional al importe devuelto, al centavo (mitad hacia arriba).
    Si con esta devolucion se completa el importe del pago, se devuelve
    todo el recargo que queda: asi la suma nunca supera lo cobrado ni deja
    centavos sueltos.
    """
    queda = recargo_pago - recargo_devuelto_antes
    if queda <= 0 or recargo_pago <= 0:
        return CERO
    if devuelto_antes + monto >= monto_pago:
        return sin_ceros(queda)
    proporcional = (monto * recargo_pago / monto_pago).quantize(
        CENTAVO, rounding=ROUND_HALF_UP
    )
    return sin_ceros(min(proporcional, queda))
