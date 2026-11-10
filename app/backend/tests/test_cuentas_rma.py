"""Procedimiento de Administracion para las cuentas de Supabase Auth.

``supabase/scripts/cuentas_rma.py`` con un transporte simulado: no se llama
a Supabase. La regla usuario -> identidad interna es la misma del frontend
(``app/frontend/src/auth/usuario.ts``).
"""

import importlib.util
from pathlib import Path

import pytest

RUTA = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "scripts"
    / "cuentas_rma.py"
)
_spec = importlib.util.spec_from_file_location("cuentas_rma", RUTA)
cuentas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cuentas)


class AdminSimulada:
    """La Admin API de Supabase Auth, en memoria."""

    def __init__(self, cuentas_existentes=()):
        self.pedidos = []
        self.usuarios = [
            {"id": f"id-{i}", "email": correo}
            for i, correo in enumerate(cuentas_existentes)
        ]

    def __call__(self, metodo, ruta, cuerpo):
        self.pedidos.append((metodo, ruta, cuerpo))
        if metodo == "GET":
            return {"users": self.usuarios}
        if metodo == "POST":
            nuevo = {
                "id": f"id-{len(self.usuarios)}",
                "email": cuerpo["email"],
            }
            self.usuarios.append(nuevo)
            return nuevo
        return {}


def test_misma_regla_que_el_frontend():
    assert cuentas.identidad("  JPerez ") == "jperez@usuarios.rma.invalid"
    assert (
        cuentas.identidad("ana_g", "cuentas.rma.invalid")
        == "ana_g@cuentas.rma.invalid"
    )
    for malo in (
        "",
        "ab",
        "a@b",
        "con espacio",
        "-empieza",
        "x" * 33,
        "ñandu",
    ):
        with pytest.raises(cuentas.ErrorCuenta):
            cuentas.identidad(malo)
    with pytest.raises(cuentas.ErrorCuenta):
        cuentas.identidad("jperez", "sin-punto")


def test_crear_cuenta_confirmada_sin_correo():
    api = AdminSimulada()
    cuentas.crear(api, "jperez@usuarios.rma.invalid", "una-clave-larga")
    ((metodo, ruta, cuerpo),) = api.pedidos
    assert (metodo, ruta) == ("POST", "/admin/users")
    assert cuerpo == {
        "email": "jperez@usuarios.rma.invalid",
        "password": "una-clave-larga",
        "email_confirm": True,
    }


def test_contrasena_minima():
    with pytest.raises(cuentas.ErrorCuenta, match="10"):
        cuentas.crear(AdminSimulada(), "jperez@usuarios.rma.invalid", "corta")


def test_restablecer_y_bloquear_buscan_la_cuenta():
    api = AdminSimulada(
        ["otra@usuarios.rma.invalid", "jperez@usuarios.rma.invalid"]
    )
    cuentas.restablecer(api, "jperez@usuarios.rma.invalid", "otra-clave-larga")
    cuentas.bloquear(api, "jperez@usuarios.rma.invalid", True)
    cuentas.bloquear(api, "jperez@usuarios.rma.invalid", False)
    cambios = [p for p in api.pedidos if p[0] == "PUT"]
    assert cambios == [
        ("PUT", "/admin/users/id-1", {"password": "otra-clave-larga"}),
        ("PUT", "/admin/users/id-1", {"ban_duration": cuentas.BLOQUEO}),
        ("PUT", "/admin/users/id-1", {"ban_duration": "none"}),
    ]
    with pytest.raises(cuentas.ErrorCuenta, match="No existe"):
        cuentas.restablecer(
            api, "nadie@usuarios.rma.invalid", "otra-clave-larga"
        )


def test_contrasena_generada_es_aleatoria_y_suficiente():
    a, b = cuentas.generar_contrasena(), cuentas.generar_contrasena()
    assert a != b and len(a) >= cuentas.LARGO_MINIMO


def test_sin_configuracion_no_hace_nada(monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    assert cuentas.main(["crear", "--usuario", "jperez"]) == 1
    assert "Faltan" in capsys.readouterr().err


def test_exige_https():
    with pytest.raises(cuentas.ErrorCuenta, match="https"):
        cuentas.transporte_http("http://proyecto.supabase.co", "clave")
