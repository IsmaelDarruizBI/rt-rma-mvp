"""``domain.politicas``: la politica de proceso y comercial por Origen.

BR-REP-016 fija la condicion comercial por Origen; este test fija los
otros cuatro requerimientos de proceso (comprobante, notificacion,
entrega a cliente, informar RT) que MVP v2 necesita para HP-REP-002 y
HP-REP-003, aunque en Slice 0 todavia no tengan flujo operativo.
"""

from app.domain.models import OrigenOrden
from app.domain.politicas import CondicionComercial, politica_de


def test_cliente_externo_es_cobrable_y_pasa_por_todo_el_cierre_normal():
    politica = politica_de(OrigenOrden.CLIENTE_EXTERNO)

    assert politica.condicion_comercial == CondicionComercial.COBRABLE
    assert politica.requiere_comprobante_recepcion is True
    assert politica.requiere_notificacion is True
    assert politica.requiere_entrega_cliente is True
    assert politica.requiere_informar_rt is False


def test_rt_interno_es_no_cobrable_al_cliente_y_se_devuelve_a_gestion_rt():
    politica = politica_de(OrigenOrden.RT_INTERNO)

    assert politica.condicion_comercial == (
        CondicionComercial.NO_COBRABLE_AL_CLIENTE
    )
    assert politica.requiere_comprobante_recepcion is False
    assert politica.requiere_notificacion is False
    assert politica.requiere_entrega_cliente is False
    assert politica.requiere_informar_rt is True


def test_rma_garantia_reparacion_es_no_cobrable_pero_se_entrega_igual():
    politica = politica_de(OrigenOrden.RMA_GARANTIA_REPARACION)

    assert politica.condicion_comercial == CondicionComercial.NO_COBRABLE
    assert politica.requiere_comprobante_recepcion is True
    assert politica.requiere_notificacion is True
    assert politica.requiere_entrega_cliente is True
    assert politica.requiere_informar_rt is False


def test_los_tres_origenes_del_enum_tienen_politica_declarada():
    for origen in OrigenOrden:
        # No debe lanzar KeyError para ningun valor real del enum.
        politica_de(origen)


def test_rt_garantia_venta_no_forma_parte_del_dominio():
    """Explicitamente fuera de scope de MVP v2 (docs/discovery/README.md)."""
    assert not hasattr(OrigenOrden, "RT_GARANTIA_VENTA")
