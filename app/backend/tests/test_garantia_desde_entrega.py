"""BF-17: la garantía empieza en la entrega efectiva (BR-REP-041).

El caso normal (la Orden tiene su registro de entrega) lo cubre
``test_documentos_custodia_entrega.py::test_20_la_garantia_empieza_con_la_entrega``.
Acá: una Orden entregada antes de que existiera ese registro, que solo tiene
el paso PROC-REP-270 en el historial. El certificado de garantía y el
comprobante final tienen que usar la misma fecha que el reclamo RMA y
``{garantia_hasta}`` (``services.ordenes.fecha_de_entrega``), y no quedar
sin inicio ni vencimiento.
"""

from datetime import date, datetime, timezone

from app.domain.models.catalogos import DatosEmpresa
from app.services.documentos import (
    ContextoDocumentos,
    contenido_comprobante_entrega,
    contenido_garantia,
)
from app.services.ordenes import fecha_de_entrega
from tests import test_documentos_custodia_entrega as base
from tests.fixtures.api_salidas import BATERIA, ok
from tests.test_documentos_custodia_entrega import (
    ARGENTINA,
    RETIRA,
    _entregar,
    _lista_y_cobrada,
)

# Los fixtures del modulo de documentos (reloj controlado y datos en tmp).
reloj = base.reloj
cliente = base.cliente

ENTREGA = datetime(2026, 10, 20, 2, 30, tzinfo=timezone.utc)  # 19/10 local
VENCE = date(2027, 1, 17)  # 19/10 + 90 días (BATERIA)


def _orden_anterior_al_registro_de_entrega(cliente, reloj):
    orden_id = _lista_y_cobrada(cliente, BATERIA)
    reloj.ahora = ENTREGA
    ok(_entregar(cliente, orden_id, **RETIRA))
    orden = cliente.app.state.contexto.ordenes.obtener(orden_id)
    assert orden.entrega is not None
    # Como una Orden entregada antes de que se guardara ``entrega``.
    return orden.model_copy(update={"entrega": None})


def test_el_certificado_usa_la_entrega_del_historial(cliente, reloj):
    anterior = _orden_anterior_al_registro_de_entrega(cliente, reloj)
    assert fecha_de_entrega(anterior) == ENTREGA

    contenido = contenido_garantia(
        anterior,
        ContextoDocumentos(
            empresa=DatosEmpresa(nombre="RT"), zona_horaria=ARGENTINA
        ),
    )

    assert contenido.fecha_inicio == ENTREGA
    (cobertura,) = contenido.coberturas
    assert cobertura.vence == VENCE


def test_el_comprobante_final_usa_la_entrega_del_historial(cliente, reloj):
    anterior = _orden_anterior_al_registro_de_entrega(cliente, reloj)

    contenido = contenido_comprobante_entrega(
        anterior,
        ContextoDocumentos(
            empresa=DatosEmpresa(nombre="RT"), zona_horaria=ARGENTINA
        ),
    )

    (trabajo,) = contenido.trabajos_realizados
    assert trabajo.garantia_vence == VENCE
