"""Punto de entrada de la aplicacion FastAPI del MVP.

Se limita a construir la app, configurar CORS para el frontend Vite,
montar el contexto de aplicacion y registrar los routers.

El ``ApplicationContext`` se arma una sola vez, desde ``Settings``, y
queda en ``app.state``. Un test que quiera otro directorio de datos
solo tiene que llamar a ``create_app(Settings(data_dir=tmp_path))``.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api import (
    catalogo_equipos,
    catalogos,
    clientes,
    health,
    inventario,
    mantenimiento,
    ordenes,
    trabajo,
)
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
    # Respuestas comprimidas si el navegador las acepta: el catalogo de
    # equipos del alta pesa ~150 KB en JSON y ~7 KB comprimido. Las
    # imagenes (fotos) ya vienen comprimidas y Starlette no las toca.
    application.add_middleware(GZipMiddleware, minimum_size=1000)

    application.state.settings = settings
    application.state.contexto = construir_contexto(settings)

    registrar_manejadores_de_error(application)

    application.include_router(health.router)
    application.include_router(catalogos.router)
    application.include_router(catalogo_equipos.router)
    application.include_router(clientes.router)
    application.include_router(ordenes.router)
    application.include_router(inventario.router)
    application.include_router(trabajo.router)
    application.include_router(mantenimiento.router)

    return application


app = create_app()
