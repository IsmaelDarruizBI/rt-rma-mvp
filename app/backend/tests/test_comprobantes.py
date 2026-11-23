"""Bloque 4 de ajustes funcionales: comprobantes (DEC-AJ-09, BF-19).

Sin PostgreSQL (modo JSON y reglas del service). El recorrido con la base
(edicion auditada, versiones publicadas, ``texto_legal_id``) esta en
``tests/postgres/test_comprobantes_postgres.py``.

- Datos de la empresa: la edicion es de Administracion y audita cada campo
  cambiado; los comprobantes nuevos copian el nombre, la direccion, el
  telefono, el horario y el pie; los snapshots anteriores (sin esos
  campos) se siguen leyendo.
- Terminos y condiciones versionados: cada Comprobante de entrega y
  garantia guarda la version vigente y la conserva aunque despues rija
  otra; una version nueva numera sus apartados, no repite la vigente y la
  publica Administracion.
- P-04: la version inicial (la 2) no fija 180 dias: remite a la garantia
  indicada para cada trabajo en el comprobante.
- P-05: el comprobante dice quien retiro y los terminos no anulan la
  garantia si retira otra persona.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.domain.models import (
    TERMINOS_INICIALES,
    ContenidoTextoLegal,
    DatosEmpresa,
    DocumentoEmitido,
    EntidadConfiguracion,
    RolUsuario,
    TipoTextoLegal,
    Usuario,
)
from app.services.comprobantes import (
    datos_de_empresa_editados,
    nueva_version_texto_legal,
)
from app.services.exceptions import DomainError, PrecondicionInvalidaError
from app.storage.json.base import escribir_json_atomico
from tests.fixtures import api_salidas as f
from tests.fixtures import iteracion1 as it
from tests.fixtures.custodia import checkin_si_falta

FECHA = datetime(2026, 11, 23, 15, tzinfo=timezone.utc)
ADMIN = Usuario(id="ADMIN-001", nombre="Admin", rol=RolUsuario.ADMINISTRADOR)
RECEPCION = Usuario(id="RECEP-001", nombre="Recep", rol=RolUsuario.RECEPCION)
MIGRACION = (
    Path(__file__).resolve().parents[3]
    / "supabase/migrations/20261123000300_comprobantes_empresa_terminos.sql"
)
EMPRESA = {
    "nombre": "Rosario Tecno",
    "razon_social": "Rosario Tecno SRL",
    "cuit": "30-12345678-9",
    "direccion": "Cordoba 1234, Rosario",
    "telefono": "341-555-0100",
    "email": "rma@rosariotecno.test",
    "horario": "Lunes a viernes de 9 a 18",
    "pie_comprobante": "Gracias por elegirnos.",
}
TERCERO = {
    "retira_otra_persona": True,
    "retira_nombre": "Ana",
    "retira_apellido": "Lopez",
    "retira_telefono": "341-555-0199",
}


@pytest.fixture
def cliente(tmp_path):
    with f.cliente_http(tmp_path, "10") as test_client:
        yield test_client


def _lista_y_pagada(cliente) -> str:
    orden_id = f.definida(cliente, f.BATERIA)
    f.tomada(cliente, orden_id)
    f.ejecutar(cliente, orden_id)
    f.ok(f.aprobar(cliente, orden_id, "DET-001"))
    it.pagar(cliente, orden_id, "80000")
    checkin_si_falta(cliente, orden_id)
    return orden_id


def _entregar(cliente, orden_id, **cuerpo) -> dict:
    return f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/deliver",
            json={"usuario_id": f.RECEPCION, **cuerpo},
        )
    )


def _emitido(cliente, orden_id, tipo) -> dict:
    (documento,) = [
        d
        for d in f.ok(cliente.get(f"/api/orders/{orden_id}/documents"))[
            "emitidos"
        ]
        if d["tipo"] == tipo
    ]
    return documento


def _texto(terminos: dict) -> str:
    return " ".join(
        linea
        for apartado in terminos["contenido"]["apartados"]
        for linea in apartado["lineas"]
    )


def _terminos(version: int, primera: str) -> dict:
    texto = TERMINOS_INICIALES.model_copy(deep=True)
    texto.version = version
    texto.contenido.apartados[0].lineas = [primera]
    return texto.model_dump(mode="json")


# --- Datos de la empresa -------------------------------------------------


def test_la_edicion_audita_cada_campo_cambiado():
    anterior = DatosEmpresa(nombre="Rosario Tecno", condiciones_garantia="X")

    nueva, cambios = datos_de_empresa_editados(
        anterior, EMPRESA, usuario=ADMIN, fecha=FECHA
    )

    assert nueva.horario == "Lunes a viernes de 9 a 18"
    # Lo que no se edita en la pantalla se conserva.
    assert nueva.condiciones_garantia == "X"
    assert [(c.campo, c.valor_anterior, c.valor_nuevo) for c in cambios] == [
        (campo, None, valor)
        for campo, valor in EMPRESA.items()
        if campo != "nombre"
    ]
    assert {(c.entidad, c.clave, c.usuario_id) for c in cambios} == {
        (EntidadConfiguracion.EMPRESA, "EMPRESA", "ADMIN-001")
    }

    # Un campo vaciado queda sin informar; sin cambios no se registra nada.
    otra, (cambio,) = datos_de_empresa_editados(
        nueva, {**EMPRESA, "pie_comprobante": "  "}, usuario=ADMIN, fecha=FECHA
    )
    assert otra.pie_comprobante is None
    assert (cambio.campo, cambio.valor_nuevo) == ("pie_comprobante", None)
    with pytest.raises(PrecondicionInvalidaError, match="no hay cambios"):
        datos_de_empresa_editados(nueva, EMPRESA, usuario=ADMIN, fecha=FECHA)


def test_la_empresa_la_edita_solo_administracion_y_exige_el_nombre():
    anterior = DatosEmpresa(nombre="Rosario Tecno")
    with pytest.raises(DomainError):
        datos_de_empresa_editados(
            anterior, EMPRESA, usuario=RECEPCION, fecha=FECHA
        )
    with pytest.raises(PrecondicionInvalidaError, match="nombre comercial"):
        datos_de_empresa_editados(
            anterior, {**EMPRESA, "nombre": " "}, usuario=ADMIN, fecha=FECHA
        )
    with pytest.raises(PrecondicionInvalidaError, match="email"):
        datos_de_empresa_editados(
            anterior, {**EMPRESA, "email": "rma"}, usuario=ADMIN, fecha=FECHA
        )


def test_en_json_la_empresa_y_los_terminos_son_de_solo_lectura(cliente):
    empresa = f.ok(cliente.get("/api/admin/company"))
    assert empresa == {
        "editable": False,
        "empresa": DatosEmpresa(nombre="Rosario Tecno").model_dump(
            mode="json"
        ),
    }
    assert "PostgreSQL" in f.conflicto(
        cliente.put(
            "/api/admin/company",
            json={"usuario_id": f.ADMINISTRADOR, **EMPRESA},
        )
    )
    terminos = f.ok(cliente.get("/api/admin/terms"))
    assert terminos["editable"] is False
    assert terminos["vigente"]["version"] == 2
    assert [v["version"] for v in terminos["versiones"]] == [2]
    assert "PostgreSQL" in f.conflicto(
        cliente.post(
            "/api/admin/terms",
            json={
                "usuario_id": f.ADMINISTRADOR,
                "titulo": "TÉRMINOS",
                "contenido": terminos["vigente"]["contenido"],
            },
        )
    )


def test_los_comprobantes_nuevos_copian_los_datos_de_la_empresa(
    cliente, tmp_path
):
    escribir_json_atomico(tmp_path / "catalogs" / "empresa.json", EMPRESA)
    orden_id = f.crear(cliente)
    f.agregar(cliente, orden_id)
    ingreso = f.generar_ingreso(cliente, orden_id)
    documento = _emitido(cliente, orden_id, "COMPROBANTE_INGRESO")

    assert documento["contenido"]["empresa"] == {
        **EMPRESA,
        "condiciones_garantia": None,
    }
    pdf = cliente.get(
        f"/api/orders/{orden_id}/documents/{documento['id']}/pdf"
    ).content.decode("cp1252")
    assert "Horario: Lunes a viernes de 9 a 18" in pdf
    assert "Gracias por elegirnos." in pdf
    assert ingreso["id"] == orden_id

    # Cambiar la empresa no altera lo emitido.
    escribir_json_atomico(
        tmp_path / "catalogs" / "empresa.json", {"nombre": "Otra"}
    )
    assert (
        _emitido(cliente, orden_id, "COMPROBANTE_INGRESO")["contenido"][
            "empresa"
        ]["horario"]
        == "Lunes a viernes de 9 a 18"
    )


def test_un_snapshot_anterior_sin_los_campos_nuevos_se_sigue_leyendo(
    cliente,
):
    orden_id = _lista_y_pagada(cliente)
    _entregar(cliente, orden_id)
    emitido = _emitido(cliente, orden_id, "COMPROBANTE_ENTREGA")
    # Como lo guardo un comprobante anterior a DEC-AJ-09.
    for campo in ("horario", "pie_comprobante"):
        del emitido["contenido"]["empresa"][campo]
    del emitido["contenido"]["terminos"]

    contenido = DocumentoEmitido.model_validate(emitido).contenido

    assert contenido.empresa.horario is None
    assert contenido.empresa.pie_comprobante is None
    # Sin copia de los terminos: la pantalla imprime el texto anterior.
    assert contenido.terminos is None


# --- Terminos y condiciones versionados ----------------------------------


def test_p04_la_version_inicial_no_fija_180_dias():
    assert TERMINOS_INICIALES.version == 2
    texto = " ".join(
        linea
        for apartado in TERMINOS_INICIALES.contenido.apartados
        for linea in apartado.lineas
    )
    assert "180" not in texto
    assert "seis meses" not in texto
    primera = TERMINOS_INICIALES.contenido.apartados[0].lineas[0]
    assert primera.startswith(
        "La reparación cuenta con la garantía indicada para cada trabajo "
        "en este comprobante, con su plazo en días y su fecha de vencimiento"
    )
    # P-05: retirar otra persona no anula la garantia.
    assert "automáticamente anulada" not in texto
    assert "misma persona que dejó el equipo" not in texto
    assert [a.numero for a in TERMINOS_INICIALES.contenido.apartados] == list(
        range(1, 19)
    )


def test_la_migracion_carga_la_misma_version_inicial():
    sql = MIGRACION.read_text(encoding="utf-8")
    literal = re.search(
        r"'TERMINOS_CONDICIONES_ENTREGA', 2, '([^']*)',\s*'((?:[^']|'')*)'"
        r"::jsonb,\s*'([^']*)'",
        sql,
    )
    assert literal is not None
    titulo, contenido, vigente_desde = literal.groups()
    assert titulo == TERMINOS_INICIALES.titulo
    assert json.loads(contenido.replace("''", "'")) == (
        TERMINOS_INICIALES.contenido.model_dump(mode="json")
    )
    assert datetime.fromisoformat(vigente_desde) == (
        TERMINOS_INICIALES.vigente_desde
    )


def test_una_version_nueva_numera_sus_apartados_y_se_audita():
    contenido = TERMINOS_INICIALES.contenido.model_copy(deep=True)
    contenido.apartados = list(reversed(contenido.apartados))
    contenido.pie = ["FIRMA", " ", "FECHA "]

    nuevo, cambio = nueva_version_texto_legal(
        [TERMINOS_INICIALES],
        TERMINOS_INICIALES,
        tipo=TipoTextoLegal.TERMINOS_CONDICIONES_ENTREGA,
        titulo=" TÉRMINOS ",
        contenido=contenido,
        usuario=ADMIN,
        fecha=FECHA,
    )

    assert (nuevo.version, nuevo.titulo, nuevo.vigente_desde) == (
        3,
        "TÉRMINOS",
        FECHA,
    )
    assert nuevo.publicado_por == "ADMIN-001"
    assert [a.numero for a in nuevo.contenido.apartados] == list(range(1, 19))
    assert nuevo.contenido.pie == ["FIRMA", "FECHA"]
    assert (cambio.entidad, cambio.clave, cambio.campo) == (
        EntidadConfiguracion.TEXTO_LEGAL,
        "TERMINOS_CONDICIONES_ENTREGA",
        "version",
    )
    assert (cambio.valor_anterior, cambio.valor_nuevo) == ("2", "3")
    # La version vigente no cambio: es inmutable.
    assert TERMINOS_INICIALES.contenido.apartados[0].numero == 1


def test_una_version_igual_a_la_vigente_o_de_otro_rol_no_se_publica():
    argumentos = {
        "tipo": TipoTextoLegal.TERMINOS_CONDICIONES_ENTREGA,
        "titulo": TERMINOS_INICIALES.titulo,
        "contenido": TERMINOS_INICIALES.contenido,
        "fecha": FECHA,
    }
    with pytest.raises(PrecondicionInvalidaError, match="no hay cambios"):
        nueva_version_texto_legal(
            [TERMINOS_INICIALES],
            TERMINOS_INICIALES,
            usuario=ADMIN,
            **argumentos,
        )
    with pytest.raises(DomainError):
        nueva_version_texto_legal(
            [TERMINOS_INICIALES],
            TERMINOS_INICIALES,
            usuario=RECEPCION,
            **argumentos,
        )
    with pytest.raises(ValueError):
        ContenidoTextoLegal.model_validate({"apartados": []})


def test_el_comprobante_de_entrega_guarda_e_imprime_su_version(
    cliente, tmp_path
):
    primera = _lista_y_pagada(cliente)
    vista = f.ok(
        cliente.get(
            f"/api/orders/{primera}/documents/preview/COMPROBANTE_ENTREGA"
        )
    )
    assert vista["contenido"]["terminos"]["version"] == 2

    _entregar(cliente, primera, **TERCERO)
    anterior = _emitido(cliente, primera, "COMPROBANTE_ENTREGA")["contenido"]
    assert anterior["terminos"] == TERMINOS_INICIALES.model_dump(mode="json")
    assert "180" not in _texto(anterior["terminos"])

    # Rige otra version: la entrega siguiente la usa y la anterior conserva
    # la suya.
    escribir_json_atomico(
        tmp_path / "catalogs" / "textos_legales.json",
        [
            TERMINOS_INICIALES.model_dump(mode="json"),
            _terminos(3, "Texto de la version 3."),
        ],
    )
    segunda = _lista_y_pagada(cliente)
    _entregar(cliente, segunda)
    nueva = _emitido(cliente, segunda, "COMPROBANTE_ENTREGA")["contenido"]
    assert nueva["terminos"]["version"] == 3
    assert _texto(nueva["terminos"]).startswith("Texto de la version 3.")
    assert (
        _emitido(cliente, primera, "COMPROBANTE_ENTREGA")["contenido"]
        == anterior
    )


def test_p05_el_comprobante_dice_quien_retiro(cliente):
    orden_id = _lista_y_pagada(cliente)
    _entregar(cliente, orden_id, **TERCERO)

    contenido = _emitido(cliente, orden_id, "COMPROBANTE_ENTREGA")["contenido"]

    assert (
        contenido["recibido_por"],
        contenido["retira_otra_persona"],
        contenido["telefono_receptor"],
    ) == ("Ana Lopez", True, "341-555-0199")
    # La garantia de cada trabajo no cambia por quien retira.
    (trabajo,) = contenido["trabajos_realizados"]
    assert trabajo["garantia_dias"] == 90
    assert "anulada" not in _texto(contenido["terminos"])


def test_una_devolucion_sin_reparacion_no_lleva_terminos(cliente):
    from tests.fixtures.custodia import enviar_a_revision

    orden_id = f.crear(cliente)
    f.ok(enviar_a_revision(cliente, orden_id))
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/technical-review",
            json={"usuario_id": f.TECNICO, "resultado": "Sin falla."},
        )
    )
    f.ok(
        cliente.post(
            f"/api/orders/{orden_id}/review/without-repair",
            json={"usuario_id": f.RECEPCION, "motivo": "No corresponde."},
        )
    )
    _entregar(cliente, orden_id)
    contenido = _emitido(cliente, orden_id, "COMPROBANTE_ENTREGA")["contenido"]
    assert contenido["tipo_entrega"] == "DEVOLUCION_SIN_REPARACION"
    assert contenido["terminos"] is None
