"""Escritor de PDF minimo (``app.core.pdf``) y el PDF del comprobante."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.application.documentos_pdf import (
    importe,
    pdf_comprobante_autorizacion,
)
from app.core.pdf import Pdf, ancho_texto, cortar
from app.domain.models import (
    CanalComunicacion,
    Cliente,
    ContenidoComprobanteAutorizacion,
    DatosEmpresa,
    DocumentoEmitido,
    Equipo,
    OrigenOrden,
    TipoDocumento,
    TrabajoAutorizadoEnDocumento,
)

FECHA = datetime(2026, 10, 15, 14, 30, tzinfo=timezone.utc)
ARGENTINA = timezone(timedelta(hours=-3))


def _documento(cantidad: int) -> DocumentoEmitido:
    trabajos = [
        TrabajoAutorizadoEnDocumento(
            detalle_id=f"DET-{numero:03d}",
            tipo_reparacion_id="TR-001",
            nombre=f"Cambio de bateria (trabajo {numero})",
            precio=Decimal("1000"),
            version_definicion=1,
            autorizado_en=FECHA,
            canal=CanalComunicacion.WHATSAPP,
        )
        for numero in range(1, cantidad + 1)
    ]
    return DocumentoEmitido(
        id="OR-000001-AUT-01",
        tipo=TipoDocumento.COMPROBANTE_AUTORIZACION,
        orden_id="OR-000001",
        version=1,
        fecha_emision=FECHA,
        contenido=ContenidoComprobanteAutorizacion(
            empresa=DatosEmpresa(nombre="Rosario Tecno"),
            orden_id="OR-000001",
            origen=OrigenOrden.CLIENTE_EXTERNO,
            fecha_ingreso=FECHA,
            cliente=Cliente(
                id="CLI-1", nombre_apellido="Ana (prueba)", telefono="1"
            ),
            equipo=Equipo(
                id="EQ-1",
                marca="Apple",
                modelo="iPhone 14",
                falla_reportada="No carga.",
            ),
            trabajos=trabajos,
            total_autorizado=Decimal(1000 * cantidad),
            leyenda="No es un comprobante de pago.",
        ),
    )


def test_cortar_respeta_el_ancho_y_las_palabras():
    texto = "Cambio de bateria y revision general del conector de carga"

    lineas = cortar(texto, 120, 10)

    assert len(lineas) > 1
    assert " ".join(lineas) == texto
    assert all(ancho_texto(linea, 10) <= 120 for linea in lineas)
    # Una palabra mas larga que el ancho tambien se corta.
    assert all(
        ancho_texto(linea, 10) <= 40 for linea in cortar("x" * 40, 40, 10)
    )


def test_el_texto_se_escapa_y_va_en_winansi():
    pdf = Pdf(titulo="Prueba", fecha=FECHA)
    pdf.texto(10, 10, "Autorizó (sí) \\ «Cambio»")

    datos = pdf.bytes()

    assert "(Autorizó \\(sí\\) \\\\ «Cambio») Tj".encode("cp1252") in datos


def test_mismo_snapshot_mismo_pdf():
    documento = _documento(2)

    primero = pdf_comprobante_autorizacion(documento, zona_horaria=ARGENTINA)
    segundo = pdf_comprobante_autorizacion(documento, zona_horaria=ARGENTINA)

    assert primero == segundo
    assert b"/Count 1" in primero
    # La hora va en la zona del negocio.
    assert "15/10/2026 11:30".encode("cp1252") in primero


def test_muchos_trabajos_pasan_a_otra_pagina_con_su_pie():
    pdf = pdf_comprobante_autorizacion(_documento(60), zona_horaria=ARGENTINA)

    texto = pdf.decode("cp1252")
    paginas = texto.count("/Type /Page ")
    assert paginas > 1
    assert f"/Count {paginas}" in texto
    assert f"Página {paginas} de {paginas}" in texto
    # El encabezado de la tabla se repite en cada pagina.
    assert texto.count("(Autorización del cliente) Tj") == paginas
    assert "(60. Cambio de bateria \\(trabajo 60\\)) Tj" in texto
    assert "$ 60.000,00" in texto


def test_importe_con_separadores_de_argentina():
    assert importe(Decimal("85000")) == "$ 85.000,00"
    assert importe(Decimal("1234567.5")) == "$ 1.234.567,50"
    assert importe(Decimal("0")) == "$ 0,00"
