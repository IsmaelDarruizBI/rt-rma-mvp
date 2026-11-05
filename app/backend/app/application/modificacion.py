"""Punto de entrada unico para modificar una Orden existente.

Todo comando que cambia una Orden ya persistida la obtiene asi:

    with orden_para_modificar(contexto, orden_id) as orden:
        orden = algun_service(orden, ...)
        contexto.ordenes.guardar(orden)
    return orden

Concentra en un solo lugar dos garantias que antes dependian de cada
comando:

- E1: una Orden cerrada -entregada o devuelta a Gestion RT- no se
  modifica (``exigir_orden_abierta``). Se evalua ANTES de cualquier otra
  precondicion, asi que el rechazo es siempre el mismo: 409
  ORDEN_CERRADA, sin efectos.
- E4: la carga, las validaciones, los services y el guardado ocurren
  dentro de una sola transaccion (``contexto.transaccion()``; con JSON,
  la seccion critica de ``app.application.concurrencia``): dos pedidos
  sobre la misma Orden se atienden uno despues del otro, y el segundo ve
  lo que guardo el primero (y lo vuelve a validar) en vez de pisarlo.
  Una solicitud obsoleta -por ejemplo, desde una pantalla que todavia no
  se enteraba de la entrega- se valida contra la Orden ya entregada y se
  rechaza.

Las lecturas (``consultas``) y el inicio de una garantia RMA -que solo
lee la Orden origen- no pasan por aqui.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from app.domain.models import OrdenReparacion
from app.services import exigir_orden_abierta

from .contexto import ApplicationContext


@contextmanager
def orden_para_modificar(
    contexto: ApplicationContext,
    orden_id: str,
) -> Iterator[OrdenReparacion]:
    """Carga la Orden, garantiza que admite cambios y serializa el comando.

    La transaccion se mantiene hasta que termina el bloque ``with`` del
    caller, es decir, hasta despues de guardar. Si el caller ya abrio
    una, esta se une a ella.
    """
    with contexto.transaccion():
        orden = contexto.ordenes.obtener_para_modificar(orden_id)
        exigir_orden_abierta(orden)
        yield orden
