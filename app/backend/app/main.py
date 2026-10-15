"""Punto de entrada de la aplicacion FastAPI del MVP.

Se limita a construir la app, configurar CORS para el frontend Vite,
montar el contexto de aplicacion y registrar los routers.

El ``ApplicationContext`` se arma una sola vez, desde ``Settings``, y
queda en ``app.state``. Un test que quiera otro directorio de datos
solo tiene que llamar a ``create_app(Settings(data_dir=tmp_path))``.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import catalogos, health, inventario, ordenes, trabajo
from app.api.errores import registrar_manejadores_de_error
from app.application import construir_contexto
from app.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construye y configura la instancia de FastAPI."""
    settings = settings or get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.state.settings = settings
    application.state.contexto = construir_contexto(settings)

    registrar_manejadores_de_error(application)

    application.include_router(health.router)
    application.include_router(catalogos.router)
    application.include_router(ordenes.router)
    application.include_router(inventario.router)
    application.include_router(trabajo.router)

    return application


app = create_app()
