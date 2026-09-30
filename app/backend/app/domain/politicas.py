"""Politica de proceso y comercial por Origen de la Orden.

BR-REP-016 fija que la condicion comercial depende del Origen, no de
ajustes manuales: cada Origen trae consigo si corresponde comprobante de
recepcion, notificacion al cliente, entrega al cliente e informe a
Gestion RT, ademas de si la Orden es cobrable. Antes de MVP v2 esto
estaba disperso como condicionales ``if orden.origen == CLIENTE_EXTERNO``
en ``services.documentos`` y ``services.pagos``; centralizarlo aqui evita
que la misma decision se repita -y eventualmente diverja- en cada lugar
que la necesita.

Es deliberadamente una tabla de datos, no un mecanismo: un
``dict`` de ``PoliticaOrigen`` (``frozen=True``, sin comportamiento)
indexado por ``OrigenOrden``. No hay motor de reglas ni DSL: agregar un
Origen nuevo es agregar una entrada a ``_POLITICAS``.

Alcance de Slice 0: las tres politicas estan declaradas y testeadas,
pero solo la de ``CLIENTE_EXTERNO`` tiene un flujo operativo -es el unico
Origen que la API puede crear-. ``RT_INTERNO`` y ``RMA_GARANTIA_REPARACION``
quedan listas para los slices que conectan HP-REP-002 y HP-REP-003.
"""

from dataclasses import dataclass

from .models.enums import OrigenOrden


class CondicionComercial:
    """Constantes de la condicion comercial de BR-REP-016.

    No es un ``Enum`` de dominio persistido -ninguna entidad guarda este
    valor-: es una clasificacion derivada del Origen, consultada al
    vuelo por ``politica_de()``. Por eso vive como constantes de clase en
    vez de sumarse a ``domain.models.enums``, que reune los valores que
    SI se persisten en algun modelo.
    """

    COBRABLE = "COBRABLE"
    NO_COBRABLE_AL_CLIENTE = "NO_COBRABLE_AL_CLIENTE"
    NO_COBRABLE = "NO_COBRABLE"


@dataclass(frozen=True)
class PoliticaOrigen:
    """Que exige el proceso y el comercio para un Origen de Orden.

    ``condicion_comercial`` distingue si el cliente debe pagar
    (``COBRABLE``), si el equipo es interno y no se le cobra a ningun
    cliente (``NO_COBRABLE_AL_CLIENTE``) o si la Orden completa esta
    exenta de cobro (``NO_COBRABLE``, garantia). Es independiente del
    precio snapshot de cada Detalle: una Orden ``NO_COBRABLE`` sigue
    teniendo ``total`` -lo que hubiera costado-, solo que nadie debe
    pagarlo.
    """

    condicion_comercial: str
    requiere_comprobante_recepcion: bool
    requiere_notificacion: bool
    requiere_entrega_cliente: bool
    requiere_informar_rt: bool


_POLITICAS: dict[OrigenOrden, PoliticaOrigen] = {
    OrigenOrden.CLIENTE_EXTERNO: PoliticaOrigen(
        condicion_comercial=CondicionComercial.COBRABLE,
        requiere_comprobante_recepcion=True,
        requiere_notificacion=True,
        requiere_entrega_cliente=True,
        requiere_informar_rt=False,
    ),
    OrigenOrden.RT_INTERNO: PoliticaOrigen(
        condicion_comercial=CondicionComercial.NO_COBRABLE_AL_CLIENTE,
        requiere_comprobante_recepcion=False,
        requiere_notificacion=False,
        requiere_entrega_cliente=False,
        requiere_informar_rt=True,
    ),
    OrigenOrden.RMA_GARANTIA_REPARACION: PoliticaOrigen(
        condicion_comercial=CondicionComercial.NO_COBRABLE,
        requiere_comprobante_recepcion=True,
        requiere_notificacion=True,
        requiere_entrega_cliente=True,
        requiere_informar_rt=False,
    ),
}


def politica_de(origen: OrigenOrden) -> PoliticaOrigen:
    """La ``PoliticaOrigen`` declarada para ese Origen.

    Los tres valores de ``OrigenOrden`` tienen entrada en ``_POLITICAS``,
    asi que esto nunca deberia fallar con los origenes actuales del
    dominio; si en el futuro se agrega un Origen al enum sin agregarle
    politica, es un error de programacion y ``KeyError`` es lo correcto.
    """
    return _POLITICAS[origen]
