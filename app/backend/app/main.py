"""Punto de entrada de la aplicacion FastAPI del MVP.

Se limita a construir la app, configurar CORS para el frontend Vite,
montar el contexto de aplicacion y registrar los routers.

El ``ApplicationContext`` se arma una sola vez, desde ``Settings``, y
queda en ``app.state``. Un test que quiera otro directorio de datos
solo tiene que llamar a ``create_app(Settings(data_dir=tmp_path))``.
"""

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api import (
    catalogo_equipos,
    catalogos,
    clientes,
    health,
    inventario,
    mantenimiento,
    modelos_equipo,
    ordenes,
    seguridad,
    trabajo,
)
from app.api.errores import registrar_manejadores_de_error
from app.api.seguridad import (
    Autenticacion,
    exigir_identidad,
    registrar_manejadores_de_seguridad,
)
from app.application import construir_contexto
from app.core.autenticacion import (
    VerificadorDeTokens,
    exigir_modo_seguro,
    obtener_clave_jwks,
    parametros_de,
)
from app.core.config import Settings, get_settings


@asynccontextmanager
async def _ciclo_de_vida(application: FastAPI):
    """B4: al apagar, el pool de PostgreSQL se cierra despues de que
    terminan los pedidos en curso."""
    yield
    cerrar = getattr(application.state.contexto, "cerrar", None)
    if cerrar is not None:
        cerrar()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construye y configura la instancia de FastAPI."""
    settings = settings or get_settings()

    # La documentacion interactiva (/docs, /redoc, /openapi.json) solo en
    # desarrollo local: con autenticacion real (UAT y produccion) no se
    # publica el mapa de la API.
    documentacion = settings.auth_modo == "demo"
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=_ciclo_de_vida,
        docs_url="/docs" if documentacion else None,
        redoc_url="/redoc" if documentacion else None,
        openapi_url="/openapi.json" if documentacion else None,
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
    try:
        application.state.autenticacion = construir_autenticacion(settings)
    except Exception:
        cerrar = getattr(application.state.contexto, "cerrar", None)
        if cerrar is not None:
            cerrar()
        raise

    registrar_manejadores_de_error(application)
    registrar_manejadores_de_seguridad(application)

    # ``/health`` es publico; todo lo demas pasa por la sesion.
    application.include_router(health.router)
    protegido = [Depends(exigir_identidad)]
    for modulo in (
        seguridad,
        catalogos,
        catalogo_equipos,
        modelos_equipo,
        clientes,
        ordenes,
        inventario,
        trabajo,
        mantenimiento,
    ):
        application.include_router(modulo.router, dependencies=protegido)

    return application


def construir_autenticacion(
    settings: Settings, entorno: dict[str, str] | None = None
) -> Autenticacion:
    """``demo`` sin verificador; ``supabase`` con las claves del proyecto.

    Falla al arrancar si el modo no es seguro para el entorno (Cloud Run
    o base remota en ``demo``) o si falta configuracion.
    """
    exigir_modo_seguro(
        settings, dict(os.environ) if entorno is None else entorno
    )
    if settings.auth_modo == "demo":
        return Autenticacion(None)
    parametros = parametros_de(settings)
    return Autenticacion(
        VerificadorDeTokens(
            parametros, obtener_clave_jwks(parametros.url_claves)
        )
    )


app = create_app()
