"""PDF del comprobante de autorizacion, armado desde su snapshot.

Se genera cada vez que se descarga, a partir del documento emitido (que
nunca cambia): no se guarda ningun binario y la misma version da siempre
el mismo PDF. Solo usa lo que el snapshot copio al emitirse; un cambio
posterior de la Orden o de los catalogos no lo altera.

    pdf_de_documento   (nombre de archivo, bytes) de un documento emitido
"""

from datetime import datetime, tzinfo
from decimal import Decimal

from app.core.pdf import ALTO_A4, ANCHO_A4, Pdf, ancho_texto, cortar
from app.domain.models import (
    CanalComunicacion,
    ContenidoComprobanteAutorizacion,
    DocumentoEmitido,
)
from app.services import PrecondicionInvalidaError

MARGEN = 48
DERECHA = ANCHO_A4 - MARGEN
ANCHO_UTIL = DERECHA - MARGEN
PIE = 56

NOMBRE_CANAL = {
    CanalComunicacion.PRESENCIAL: "Presencial",
    CanalComunicacion.TELEFONO: "Teléfono",
    CanalComunicacion.WHATSAPP: "WhatsApp",
    CanalComunicacion.EMAIL: "Email",
    CanalComunicacion.OTRO: "Otro",
}

# Columnas de la tabla de trabajos.
COL_TRABAJO = MARGEN + 6
ANCHO_TRABAJO = 250
COL_AUTORIZACION = COL_TRABAJO + ANCHO_TRABAJO + 12
ANCHO_AUTORIZACION = 150
COL_PRECIO = DERECHA - 6


def importe(valor: Decimal) -> str:
    """$ 85.000,00 (separadores de Argentina)."""
    texto = f"{valor:,.2f}".replace(",", "_").replace(".", ",")
    return "$ " + texto.replace("_", ".")


def fecha_hora(fecha: datetime, zona: tzinfo) -> str:
    return fecha.astimezone(zona).strftime("%d/%m/%Y %H:%M")


class _Hoja:
    """El PDF con un cursor vertical que salta de pagina solo."""

    def __init__(self, pdf: Pdf, encabezado_tabla=None):
        self.pdf = pdf
        self.y = ALTO_A4 - MARGEN
        self.encabezado_tabla = encabezado_tabla

    def asegurar(self, alto: float) -> None:
        if self.y - alto >= PIE:
            return
        self.pdf.pagina()
        self.y = ALTO_A4 - MARGEN
        if self.encabezado_tabla is not None:
            self.encabezado_tabla(self)

    def bajar(self, alto: float) -> None:
        self.y -= alto

    def parrafo(
        self,
        texto: str,
        *,
        tamano: float = 9.5,
        negrita: bool = False,
        gris: float = 0,
        x: float = MARGEN,
        ancho: float = ANCHO_UTIL,
        interlinea: float = 1.35,
    ) -> None:
        for linea in cortar(texto, ancho, tamano, negrita):
            self.asegurar(tamano * interlinea)
            self.bajar(tamano * interlinea)
            self.pdf.texto(
                x, self.y, linea, tamano=tamano, negrita=negrita, gris=gris
            )

    def titulo(self, texto: str) -> None:
        self.asegurar(34)
        self.bajar(22)
        self.pdf.texto(
            MARGEN, self.y, texto.upper(), tamano=8.5, negrita=True, gris=0.35
        )
        self.bajar(5)
        self.pdf.linea(MARGEN, self.y, DERECHA, self.y)


def _encabezado(hoja: _Hoja, documento: DocumentoEmitido, zona: tzinfo):
    contenido = documento.contenido
    empresa = contenido.empresa
    pdf = hoja.pdf
    arriba = hoja.y
    pdf.texto(MARGEN, arriba - 16, empresa.nombre, tamano=16, negrita=True)
    datos = [
        dato
        for dato in (
            empresa.razon_social,
            f"CUIT {empresa.cuit}" if empresa.cuit else None,
            empresa.direccion,
            " · ".join(d for d in (empresa.telefono, empresa.email) if d),
        )
        if dato
    ]
    y = arriba - 30
    for dato in datos:
        pdf.texto(MARGEN, y, dato, tamano=8.5, gris=0.35)
        y -= 11
    pdf.texto(
        DERECHA,
        arriba - 14,
        "COMPROBANTE DE AUTORIZACIÓN",
        tamano=12,
        negrita=True,
        derecha=True,
    )
    pdf.texto(
        DERECHA,
        arriba - 29,
        f"Orden {contenido.orden_id}",
        tamano=10.5,
        negrita=True,
        derecha=True,
    )
    pdf.texto(
        DERECHA,
        arriba - 42,
        f"{documento.id} · versión {documento.version}",
        tamano=8.5,
        gris=0.35,
        derecha=True,
    )
    pdf.texto(
        DERECHA,
        arriba - 53,
        f"Emitido el {fecha_hora(documento.fecha_emision, zona)}",
        tamano=8.5,
        gris=0.35,
        derecha=True,
    )
    hoja.y = min(y + 11, arriba - 53) - 12
    pdf.linea(MARGEN, hoja.y, DERECHA, hoja.y, grosor=1, gris=0.2)


def _cliente_y_equipo(hoja: _Hoja, contenido, zona: tzinfo) -> None:
    hoja.titulo("Cliente y equipo")
    pdf = hoja.pdf
    medio = MARGEN + ANCHO_UTIL / 2 + 6
    cliente = contenido.cliente
    equipo = contenido.equipo
    izquierda = [
        ("Cliente", cliente.nombre if cliente else "—"),
        ("Teléfono", cliente.telefono if cliente else "—"),
    ]
    if cliente and cliente.email:
        izquierda.append(("Email", cliente.email))
    derecha = [
        ("Equipo", f"{equipo.marca} {equipo.modelo}"),
        ("Ingreso", fecha_hora(contenido.fecha_ingreso, zona)),
    ]
    if equipo.imei:
        derecha.append(("IMEI", equipo.imei))
    if equipo.numero_serie:
        derecha.append(("N.º de serie", equipo.numero_serie))
    hoja.asegurar(13 * max(len(izquierda), len(derecha)) + 8)
    y = hoja.y - 4
    for columna, filas in ((MARGEN, izquierda), (medio, derecha)):
        for fila, (etiqueta, valor) in enumerate(filas, start=1):
            pdf.texto(
                columna, y - 13 * fila, f"{etiqueta}:", tamano=9, gris=0.35
            )
            pdf.texto(
                columna + ancho_texto(f"{etiqueta}: ", 9),
                y - 13 * fila,
                valor,
                tamano=9.5,
            )
    hoja.y = y - 13 * max(len(izquierda), len(derecha)) - 4
    hoja.parrafo(f"Falla declarada: {equipo.falla_reportada}", tamano=9)


def _encabezado_tabla(hoja: _Hoja) -> None:
    pdf = hoja.pdf
    hoja.bajar(18)
    pdf.rectangulo(
        MARGEN, hoja.y - 5, ANCHO_UTIL, 18, relleno=0.93, borde=None
    )
    pdf.texto(COL_TRABAJO, hoja.y, "Trabajo", tamano=8.5, negrita=True)
    pdf.texto(
        COL_AUTORIZACION,
        hoja.y,
        "Autorización del cliente",
        tamano=8.5,
        negrita=True,
    )
    pdf.texto(
        COL_PRECIO, hoja.y, "Precio", tamano=8.5, negrita=True, derecha=True
    )
    hoja.bajar(6)


def _trabajos(hoja: _Hoja, contenido, zona: tzinfo) -> None:
    hoja.titulo("Trabajos autorizados por el cliente")
    _encabezado_tabla(hoja)
    hoja.encabezado_tabla = _encabezado_tabla
    pdf = hoja.pdf
    for numero, trabajo in enumerate(contenido.trabajos, start=1):
        nombre = cortar(f"{numero}. {trabajo.nombre}", ANCHO_TRABAJO, 9.5)
        autorizacion = cortar(
            f"{fecha_hora(trabajo.autorizado_en, zona)} · "
            f"{NOMBRE_CANAL.get(trabajo.canal, trabajo.canal.value)}",
            ANCHO_AUTORIZACION,
            9,
        )
        alto = 13 * max(len(nombre), len(autorizacion)) + 6
        hoja.asegurar(alto)
        y = hoja.y
        for indice, linea in enumerate(nombre):
            pdf.texto(COL_TRABAJO, y - 13 * (indice + 1), linea, tamano=9.5)
        for indice, linea in enumerate(autorizacion):
            pdf.texto(
                COL_AUTORIZACION,
                y - 13 * (indice + 1),
                linea,
                tamano=9,
                gris=0.25,
            )
        pdf.texto(
            COL_PRECIO,
            y - 13,
            importe(trabajo.precio),
            tamano=9.5,
            derecha=True,
        )
        hoja.bajar(alto)
        pdf.linea(MARGEN, hoja.y + 3, DERECHA, hoja.y + 3, gris=0.85)
    hoja.encabezado_tabla = None
    hoja.asegurar(26)
    hoja.bajar(18)
    pdf.texto(
        COL_AUTORIZACION, hoja.y, "Total autorizado", tamano=10.5, negrita=True
    )
    pdf.texto(
        COL_PRECIO,
        hoja.y,
        importe(contenido.total_autorizado),
        tamano=10.5,
        negrita=True,
        derecha=True,
    )


def _version(hoja: _Hoja, documento: DocumentoEmitido) -> None:
    if documento.version == 1 or not documento.reemplaza_a:
        return
    hoja.bajar(10)
    texto = (
        f"Esta versión reemplaza a {documento.reemplaza_a}, que se conserva "
        "sin cambios."
    )
    if documento.motivo:
        texto += f" {documento.motivo}"
    hoja.parrafo(texto, tamano=8.5, gris=0.3)


def _leyenda(hoja: _Hoja, contenido) -> None:
    pdf = hoja.pdf
    lineas = cortar(contenido.leyenda, ANCHO_UTIL - 20, 9)
    alto = 16 + 13 + 12.5 * len(lineas) + 6
    hoja.asegurar(alto + 16)
    hoja.bajar(16)
    pdf.rectangulo(
        MARGEN, hoja.y - alto, ANCHO_UTIL, alto, relleno=0.96, borde=0.75
    )
    y = hoja.y - 18
    pdf.texto(
        MARGEN + 10,
        y,
        "No es un comprobante de pago.",
        tamano=10,
        negrita=True,
    )
    for linea in lineas:
        y -= 12.5
        pdf.texto(MARGEN + 10, y, linea, tamano=9, gris=0.2)
    hoja.bajar(alto)


def _pies(pdf: Pdf, documento: DocumentoEmitido) -> None:
    contenido = documento.contenido
    total = pdf.cantidad_paginas
    for indice in range(total):
        lienzo = pdf.en_pagina(indice)
        lienzo.linea(MARGEN, PIE - 14, DERECHA, PIE - 14, gris=0.8)
        lienzo.texto(
            MARGEN,
            PIE - 26,
            f"{contenido.empresa.nombre} · Orden {contenido.orden_id} · "
            f"{documento.id}",
            tamano=7.5,
            gris=0.4,
        )
        lienzo.texto(
            DERECHA,
            PIE - 26,
            f"Página {indice + 1} de {total}",
            tamano=7.5,
            gris=0.4,
            derecha=True,
        )


def pdf_comprobante_autorizacion(
    documento: DocumentoEmitido, *, zona_horaria: tzinfo
) -> bytes:
    contenido = documento.contenido
    pdf = Pdf(
        titulo=(
            f"Comprobante de autorización {documento.id} — Orden "
            f"{contenido.orden_id}"
        ),
        fecha=documento.fecha_emision,
        autor=contenido.empresa.nombre,
    )
    hoja = _Hoja(pdf)
    _encabezado(hoja, documento, zona_horaria)
    _cliente_y_equipo(hoja, contenido, zona_horaria)
    _trabajos(hoja, contenido, zona_horaria)
    _version(hoja, documento)
    _leyenda(hoja, contenido)
    _pies(pdf, documento)
    return pdf.bytes()


def pdf_de_documento(
    documento: DocumentoEmitido, *, zona_horaria: tzinfo
) -> tuple[str, bytes]:
    """Nombre de archivo y PDF de un documento emitido.

    Hoy solo el comprobante de autorizacion se descarga como PDF; los
    demas se imprimen (o guardan como PDF) desde el navegador.
    """
    if not isinstance(documento.contenido, ContenidoComprobanteAutorizacion):
        raise PrecondicionInvalidaError(
            f"{documento.id} no se descarga como PDF: se imprime desde la "
            "pantalla de la Orden."
        )
    return (
        f"{documento.id}.pdf",
        pdf_comprobante_autorizacion(documento, zona_horaria=zona_horaria),
    )
