"""Catalogo tecnico de modelos de equipo (lectura).

    modelos_para_seleccion  los modelos que se ofrecen en el alta y la
                            correccion del equipo

Elegir un modelo y copiarlo al Equipo lo hace ``equipo_desde_catalogo``,
junto con la carga manual y los productos de Ventas de Ordenes
anteriores.
"""

from app.domain.models import ModeloEquipo

from .contexto import ApplicationContext


def modelos_para_seleccion(
    contexto: ApplicationContext,
) -> list[ModeloEquipo]:
    """Los modelos activos, en el orden del catalogo."""
    modelos = contexto.modelos_equipo
    if modelos is None:
        return []
    return [modelo for modelo in modelos.listar_modelos() if modelo.activo]
