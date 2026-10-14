"""Lectura y escritura de archivos JSON para el almacenamiento del MVP.

Unico lugar del backend que conoce ``Path``, ``open()`` y el modulo
``json``. Los services nunca llegan hasta aqui: hablan con los contratos
de ``app.repositories``.

CONCURRENCIA (E4)
-----------------
Todo acceso a un archivo -leer, o escribir el temporal y reemplazar el
destino- ocurre dentro de ``acceso_exclusivo``, un lock de PROCESO. En
Windows ``os.replace`` falla con ``PermissionError`` si otro hilo tiene el
destino abierto -una lectura simultanea, otro reemplazo-: con el lock eso
no ocurre dentro del backend. Si el que lo tiene abierto es otro programa
(antivirus, indexador, un editor), la operacion se reintenta unas pocas
veces antes de fallar.

El lock NO protege entre procesos ni entre instancias: el backend sigue
corriendo con un unico worker (ver ``app.application.concurrencia``). JSON
es el almacenamiento de las pruebas funcionales, no el de produccion.
"""

import json
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, TypeVar

from app.repositories.exceptions import PersistenciaError

ResultadoT = TypeVar("ResultadoT")

_LOCK_ARCHIVOS = threading.RLock()

# Colision transitoria con otro programa: hasta 5 intentos, con esperas de
# 20, 40, 80 y 160 ms (300 ms en total) antes de rendirse.
_INTENTOS = 5
_ESPERA_INICIAL = 0.02


@contextmanager
def acceso_exclusivo() -> Iterator[None]:
    """Serializa el acceso a los archivos dentro de este proceso.

    Es reentrante: un repository puede leer la version guardada y
    reemplazarla dentro de una misma seccion, sin que otro hilo se meta
    entre las dos cosas.
    """
    with _LOCK_ARCHIVOS:
        yield


def _con_reintentos(operacion: Callable[[], ResultadoT]) -> ResultadoT:
    """Reintenta un ``PermissionError`` transitorio (archivo ocupado)."""
    espera = _ESPERA_INICIAL
    for intento in range(1, _INTENTOS + 1):
        try:
            return operacion()
        except PermissionError:
            if intento == _INTENTOS:
                raise
            time.sleep(espera)
            espera *= 2
    raise AssertionError("inalcanzable")  # pragma: no cover


def asegurar_directorio(directorio: Path) -> Path:
    """Crea el directorio si falta y lo devuelve."""
    try:
        directorio.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PersistenciaError(
            f"No se pudo preparar el directorio {directorio}: {error}"
        ) from error
    return directorio


def leer_json(ruta: Path) -> Any:
    """Lee y parsea un archivo JSON.

    Traduce cualquier fallo -contenido invalido o error de E/S- a
    ``PersistenciaError``, para que el llamador no tenga que conocer las
    excepciones del modulo ``json`` ni del sistema de archivos.
    """
    try:
        with acceso_exclusivo():
            contenido = _con_reintentos(
                lambda: ruta.read_text(encoding="utf-8")
            )
    except OSError as error:
        raise PersistenciaError(
            f"No se pudo leer {ruta}: {error}"
        ) from error

    try:
        return json.loads(contenido)
    except json.JSONDecodeError as error:
        raise PersistenciaError(
            f"El archivo {ruta} no contiene JSON valido: {error}"
        ) from error


def escribir_json_atomico(ruta: Path, contenido: Any) -> None:
    """Escribe el JSON de forma atomica.

    Escribe en un temporal del mismo directorio -con nombre unico, asi que
    dos escrituras nunca comparten temporal-, lo cierra y recien entonces
    hace ``os.replace``, que es atomico dentro del mismo sistema de
    archivos. Asi una escritura interrumpida nunca deja el archivo
    destino a medias: o esta la version anterior, o la nueva.

    Si algo falla, el temporal se borra y no queda basura al lado del
    archivo bueno.
    """
    asegurar_directorio(ruta.parent)

    temporal: Path | None = None
    try:
        with acceso_exclusivo():
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=ruta.parent,
                prefix=f".{ruta.name}.",
                suffix=".tmp",
                delete=False,
            ) as archivo:
                temporal = Path(archivo.name)
                json.dump(contenido, archivo, ensure_ascii=False, indent=2)
                archivo.write("\n")
                archivo.flush()
                os.fsync(archivo.fileno())

            origen = temporal
            _con_reintentos(lambda: os.replace(origen, ruta))
            temporal = None
    except OSError as error:
        raise PersistenciaError(
            f"No se pudo escribir {ruta}: {error}"
        ) from error
    finally:
        if temporal is not None and temporal.exists():
            temporal.unlink(missing_ok=True)
