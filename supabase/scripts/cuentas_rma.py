"""Cuentas de los empleados en Supabase Auth (usuario y contrasena).

Lo usa Administracion, con autorizacion, desde una maquina de confianza. Los
empleados no usan su correo: cada cuenta tiene como "email" la identidad
interna ``<usuario>@<dominio>`` (dominio reservado ``.invalid``: no existe
ni recibe correo; ver ``app/frontend/src/auth/usuario.ts``, misma regla).
RMA no guarda contrasenas ni hashes: solo Supabase Auth.

    crear        --usuario jperez [--generar]   cuenta confirmada
    restablecer  --usuario jperez [--generar]   contrasena nueva
    bloquear     --usuario jperez               no puede iniciar sesion
    desbloquear  --usuario jperez

Variables (nunca en el repositorio ni en el frontend):
    SUPABASE_URL          https://<proyecto>.supabase.co
    SUPABASE_SECRET_KEY   clave secreta (o service_role) del proyecto
    RMA_DOMINIO_USUARIOS  opcional, por defecto usuarios.rma.invalid

La contrasena se pide sin eco (dos veces) o, con ``--generar``, se genera y
se muestra UNA vez para entregarla en persona. Nunca va en los argumentos.
Despues de crear, el vinculo con el usuario de RMA se hace con
``supabase/scripts/vincular_usuarios_auth.sql`` (codigo + identidad).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import secrets
import string
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

DOMINIO_POR_DEFECTO = "usuarios.rma.invalid"
FORMATO_USUARIO = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
FORMATO_DOMINIO = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
LARGO_MINIMO = 10
BLOQUEO = "876000h"  # 100 anios: bloqueo indefinido de Supabase Auth


class ErrorCuenta(Exception):
    """Un error que se le muestra a Administracion (sin secretos)."""


def normalizar_usuario(texto: str) -> str:
    usuario = texto.strip().lower()
    if not FORMATO_USUARIO.fullmatch(usuario):
        raise ErrorCuenta(
            "Usuario invalido: 3 a 32 caracteres, minusculas, digitos, punto, "
            "guion o guion bajo, empezando con letra o digito."
        )
    return usuario


def identidad(usuario: str, dominio: str = DOMINIO_POR_DEFECTO) -> str:
    if not FORMATO_DOMINIO.fullmatch(dominio):
        raise ErrorCuenta("Dominio de usuarios invalido.")
    return f"{normalizar_usuario(usuario)}@{dominio}"


def validar_contrasena(contrasena: str) -> str:
    if len(contrasena) < LARGO_MINIMO:
        raise ErrorCuenta(
            f"La contrasena debe tener al menos {LARGO_MINIMO} caracteres."
        )
    return contrasena


def generar_contrasena(largo: int = 16) -> str:
    alfabeto = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(largo))


Transporte = Callable[[str, str, dict[str, Any] | None], Any]
"""(metodo, ruta, cuerpo) -> respuesta JSON de la Admin API."""


def transporte_http(url: str, clave: str) -> Transporte:
    if not url.startswith("https://"):
        raise ErrorCuenta("SUPABASE_URL debe usar https.")
    base = url.rstrip("/") + "/auth/v1"

    def enviar(metodo: str, ruta: str, cuerpo: dict[str, Any] | None):
        datos = None if cuerpo is None else json.dumps(cuerpo).encode()
        pedido = urllib.request.Request(
            base + ruta,
            data=datos,
            method=metodo,
            headers={
                "apikey": clave,
                "Authorization": f"Bearer {clave}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(pedido, timeout=30) as respuesta:
                texto = respuesta.read().decode() or "null"
                return json.loads(texto)
        except urllib.error.HTTPError as error:
            # Solo el codigo y el mensaje de Supabase: nunca la clave.
            try:
                detalle = json.loads(error.read().decode())
                mensaje = detalle.get("msg") or detalle.get("message") or ""
            except ValueError:
                mensaje = ""
            raise ErrorCuenta(
                f"Supabase Auth respondio {error.code}: {mensaje}".strip()
            ) from None

    return enviar


def _buscar(enviar: Transporte, correo: str) -> dict[str, Any]:
    pagina = 1
    while True:
        datos = enviar("GET", f"/admin/users?page={pagina}&per_page=200", None)
        usuarios = datos.get("users", []) if isinstance(datos, dict) else []
        for usuario in usuarios:
            if (usuario.get("email") or "").lower() == correo:
                return usuario
        if len(usuarios) < 200:
            raise ErrorCuenta("No existe una cuenta con ese usuario.")
        pagina += 1


def crear(enviar: Transporte, correo: str, contrasena: str) -> dict[str, Any]:
    """Cuenta confirmada: sin correo de confirmacion (no hay a quien)."""
    return enviar(
        "POST",
        "/admin/users",
        {
            "email": correo,
            "password": validar_contrasena(contrasena),
            "email_confirm": True,
        },
    )


def restablecer(enviar: Transporte, correo: str, contrasena: str) -> None:
    cuenta = _buscar(enviar, correo)
    enviar(
        "PUT",
        f"/admin/users/{urllib.parse.quote(cuenta['id'])}",
        {"password": validar_contrasena(contrasena)},
    )


def bloquear(enviar: Transporte, correo: str, bloqueada: bool) -> None:
    cuenta = _buscar(enviar, correo)
    enviar(
        "PUT",
        f"/admin/users/{urllib.parse.quote(cuenta['id'])}",
        {"ban_duration": BLOQUEO if bloqueada else "none"},
    )


def _contrasena(generar: bool) -> str:
    if generar:
        contrasena = generar_contrasena()
        print(f"Contrasena (se muestra una sola vez): {contrasena}")
        return contrasena
    primera = getpass.getpass("Contrasena: ")
    if getpass.getpass("Repetila: ") != primera:
        raise ErrorCuenta("Las contrasenas no coinciden.")
    return validar_contrasena(primera)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "accion", choices=["crear", "restablecer", "bloquear", "desbloquear"]
    )
    parser.add_argument("--usuario", required=True)
    parser.add_argument("--generar", action="store_true")
    args = parser.parse_args(argv)
    try:
        url = os.environ.get("SUPABASE_URL", "")
        clave = os.environ.get("SUPABASE_SECRET_KEY", "")
        if not url or not clave:
            raise ErrorCuenta("Faltan SUPABASE_URL o SUPABASE_SECRET_KEY.")
        correo = identidad(
            args.usuario,
            os.environ.get("RMA_DOMINIO_USUARIOS", DOMINIO_POR_DEFECTO),
        )
        enviar = transporte_http(url, clave)
        if args.accion == "crear":
            cuenta = crear(enviar, correo, _contrasena(args.generar))
            print(f"Cuenta creada: {correo} (id {cuenta.get('id')}).")
            print(
                "Vincularla con su usuario de RMA: "
                "supabase/scripts/vincular_usuarios_auth.sql "
                f"-v codigo=<CODIGO> -v email={correo}"
            )
        elif args.accion == "restablecer":
            restablecer(enviar, correo, _contrasena(args.generar))
            print(f"Contrasena restablecida para {correo}.")
        else:
            bloquear(enviar, correo, args.accion == "bloquear")
            estado = (
                "bloqueada" if args.accion == "bloquear" else "desbloqueada"
            )
            print(f"Cuenta {correo} {estado}.")
    except ErrorCuenta as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
