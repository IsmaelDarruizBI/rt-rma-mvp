"""Seleccion de persistencia y configuracion segura de PostgreSQL (E0).

Ninguna de estas pruebas abre conexiones: validan la configuracion, el
arranque y que la cadena de conexion nunca aparezca en mensajes, logs ni
``repr``.
"""

import base64
import hashlib
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import CA_POSTGRES_POR_DEFECTO, Settings
from app.main import create_app
from app.storage.postgres import (
    ConfiguracionPersistenciaError,
    configuracion_postgres,
)

PASSWORD = "Clave-De-Prueba-No-Debe-Verse"
HOST_REMOTO = "pooler.ejemplo.invalid"
URL_REMOTA = f"postgresql://rma_api:{PASSWORD}@{HOST_REMOTO}:6543/postgres"
# Huella SHA-256 (DER) de la Supabase Root 2021 CA.
HUELLA_CA_SUPABASE = (
    "807025AD50D4ED219D2C9C7D299C004F824EB00CF7F65AFEF607D07B72E6CAFA"
)
CA_DEL_REPOSITORIO = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "certs"
    / "supabase-ca.crt"
)


@pytest.fixture(autouse=True)
def _sin_variables_de_persistencia(monkeypatch):
    for variable in (
        "RMA_PERSISTENCIA",
        "RMA_DATABASE_URL",
        "RMA_DB_SSLROOTCERT",
    ):
        monkeypatch.delenv(variable, raising=False)


def _settings(**valores) -> Settings:
    return Settings(_env_file=None, **valores)


def _postgres(url: str, **valores) -> Settings:
    return _settings(persistencia="postgres", database_url=url, **valores)


# --- Seleccion de persistencia ---------------------------------------


def test_por_defecto_la_persistencia_es_json():
    settings = _settings()
    assert settings.persistencia == "json"
    assert settings.database_url is None


def test_la_app_arranca_con_json_sin_variables_postgres(tmp_path):
    cliente = TestClient(create_app(_settings(data_dir=tmp_path)))
    assert cliente.get("/health").status_code == 200


def test_las_variables_de_entorno_eligen_postgres(monkeypatch):
    monkeypatch.setenv("RMA_PERSISTENCIA", "postgres")
    monkeypatch.setenv("RMA_DATABASE_URL", URL_REMOTA)
    settings = _settings()
    assert settings.persistencia == "postgres"
    assert settings.database_url.get_secret_value() == URL_REMOTA


def test_una_persistencia_desconocida_se_rechaza():
    with pytest.raises(ValidationError):
        _settings(persistencia="sqlite")


def test_postgres_sin_url_detiene_el_arranque(tmp_path):
    with pytest.raises(ConfiguracionPersistenciaError, match="DATABASE_URL"):
        create_app(_settings(persistencia="postgres", data_dir=tmp_path))


def test_postgres_remoto_no_arranca_hasta_e8(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ConfiguracionPersistenciaError) as capturado:
        create_app(_postgres(URL_REMOTA, data_dir=tmp_path))
    assert "solo arranca contra un servidor local" in str(capturado.value)
    assert PASSWORD not in str(capturado.value)
    assert PASSWORD not in caplog.text


# --- Validacion de la URL y del TLS ----------------------------------


@pytest.mark.parametrize(
    ("url", "motivo"),
    [
        (f"mysql://u:{PASSWORD}@{HOST_REMOTO}/x", "postgresql://"),
        (f"postgresql://u:{PASSWORD}@/postgres", "postgresql://"),
        ("no-es-una-url", "postgresql://"),
        (f"postgresql://u:{PASSWORD}@{HOST_REMOTO}:puerto/x", "valida"),
        (f"{URL_REMOTA}?sslmode=require", "sslmode=require"),
        (f"{URL_REMOTA}?sslmode=disable", "sslmode=disable"),
        (f"{URL_REMOTA}?sslmode=prefer", "sslmode=prefer"),
        (f"{URL_REMOTA}?sslmode=verify-ca", "sslmode=verify-ca"),
        (f"{URL_REMOTA}?sslmode={PASSWORD}", "no reconocido"),
        (
            f"{URL_REMOTA}?sslmode=verify-full&sslmode=disable",
            "repite",
        ),
        (f"{URL_REMOTA}?sslrootcert=system", "RMA_DB_SSLROOTCERT"),
        ("   ", "RMA_DATABASE_URL"),
        # libpq reemplazaria el host de la URL: una URL "local" podria
        # conectar sin TLS a un servidor remoto.
        (
            f"postgresql://u:{PASSWORD}@localhost/db?host={HOST_REMOTO}",
            "host",
        ),
        (
            f"postgresql://u:{PASSWORD}@127.0.0.1/db?hostaddr=203.0.113.9",
            "hostaddr",
        ),
        (f"postgresql://u:{PASSWORD}@localhost/db?service=otro", "service"),
        (f"{URL_REMOTA}?host=otro.ejemplo.invalid", "host"),
        (
            f"postgresql://u:{PASSWORD}@localhost,{HOST_REMOTO}/db",
            "un solo servidor",
        ),
    ],
)
def test_una_url_invalida_o_insegura_se_rechaza(url, motivo):
    with pytest.raises(ConfiguracionPersistenciaError) as capturado:
        configuracion_postgres(_postgres(url))
    assert motivo in str(capturado.value)
    assert PASSWORD not in str(capturado.value)
    assert capturado.value.__cause__ is None


@pytest.mark.parametrize(
    "url", [URL_REMOTA, f"{URL_REMOTA}?sslmode=verify-full"]
)
def test_un_servidor_remoto_usa_verify_full_con_la_ca(url):
    configuracion = configuracion_postgres(_postgres(url))
    assert configuracion.sslmode == "verify-full"
    assert configuracion.sslrootcert == CA_POSTGRES_POR_DEFECTO.resolve()
    argumentos = configuracion.argumentos_conexion()
    assert argumentos["sslmode"] == "verify-full"
    assert argumentos["sslrootcert"] == str(CA_POSTGRES_POR_DEFECTO.resolve())
    # El pooler en modo transaccion no admite sentencias preparadas.
    assert "prepare_threshold" in argumentos
    assert argumentos["prepare_threshold"] is None


def test_una_ca_inexistente_se_rechaza(tmp_path):
    settings = _postgres(URL_REMOTA, db_sslrootcert=tmp_path / "no-existe.crt")
    with pytest.raises(ConfiguracionPersistenciaError, match="no se puede"):
        configuracion_postgres(settings)


def test_una_ca_que_no_es_un_certificado_se_rechaza(tmp_path):
    archivo = tmp_path / "ca.crt"
    archivo.write_text("no es un certificado", encoding="utf-8")
    settings = _postgres(URL_REMOTA, db_sslrootcert=archivo)
    with pytest.raises(ConfiguracionPersistenciaError, match="PEM"):
        configuracion_postgres(settings)


@pytest.mark.parametrize(
    ("url", "sslmode"),
    [
        (
            "postgresql://postgres@127.0.0.1:54329/rma?sslmode=disable",
            "disable",
        ),
        ("postgresql://postgres@localhost/rma", "prefer"),
        ("postgres://postgres@[::1]:5432/rma", "prefer"),
    ],
)
def test_un_servidor_local_puede_ir_sin_tls(url, sslmode):
    configuracion = configuracion_postgres(_postgres(url))
    assert configuracion.sslmode == sslmode
    assert configuracion.sslrootcert is None
    assert "sslrootcert" not in configuracion.argumentos_conexion()


# --- Secretos --------------------------------------------------------


def test_la_cadena_de_conexion_no_aparece_en_repr_ni_en_volcados():
    settings = _postgres(URL_REMOTA)
    configuracion = configuracion_postgres(settings)
    for texto in (
        repr(settings),
        str(settings),
        str(settings.model_dump()),
        settings.model_dump_json(),
        repr(configuracion),
    ):
        assert PASSWORD not in texto


def test_sin_secretos_oculta_la_url_y_la_contrasena():
    url = f"postgresql://u:{PASSWORD}%40x@{HOST_REMOTO}/postgres"
    configuracion = configuracion_postgres(_postgres(url))
    texto = configuracion.sin_secretos(
        f"fallo {url}; otra postgresql://a:b@c/d; password={PASSWORD}; "
        f"{PASSWORD}@x"
    )
    assert PASSWORD not in texto
    assert "postgresql://" not in texto
    assert "<oculto>" in texto


# --- Certificado raiz ------------------------------------------------


def _huella_sha256(pem: bytes) -> str:
    cuerpo = b"".join(
        linea
        for linea in pem.splitlines()
        if linea and not linea.startswith(b"-----")
    )
    return hashlib.sha256(base64.b64decode(cuerpo)).hexdigest().upper()


def test_la_ca_empaquetada_es_la_raiz_publica_de_supabase():
    pem = CA_POSTGRES_POR_DEFECTO.read_bytes()
    assert pem.count(b"-----BEGIN CERTIFICATE-----") == 1
    assert _huella_sha256(pem) == HUELLA_CA_SUPABASE


def test_la_ca_empaquetada_es_identica_a_la_del_repositorio():
    if not CA_DEL_REPOSITORIO.exists():
        pytest.skip("Fuera del repositorio: no esta supabase/certs.")
    assert CA_POSTGRES_POR_DEFECTO.read_bytes() == (
        CA_DEL_REPOSITORIO.read_bytes()
    )
