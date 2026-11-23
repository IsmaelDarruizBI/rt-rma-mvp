"""PDF de los comprobantes con trabajos y precios, desde su snapshot.

    COMPROBANTE_INGRESO       ingreso y autorizacion inicial (MVP v2):
                              recepcion del equipo + trabajos autorizados
    COMPROBANTE_AUTORIZACION  trabajos autorizados por el cliente

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
    AjusteEnDocumento,
    CanalComunicacion,
    ClaseAjuste,
    ContenidoComprobanteAutorizacion,
    ContenidoComprobanteIngreso,
    DescuentoEnDocumento,
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

TITULO_DOCUMENTO = {
    ContenidoComprobanteAutorizacion: "COMPROBANTE DE AUTORIZACIÓN",
    ContenidoComprobanteIngreso: "COMPROBANTE DE INGRESO",
}


def importe(valor: Decimal) -> str:
    """$ 85.000,00 (separadores de Argentina)."""
    texto = f"{valor:,.2f}".replace(",", "_").replace(".", ",")
    return "$ " + texto.replace("_", ".")


# DEC-AJ-10 (D-10.5): la cortesia se imprime como cortesia.
NOMBRE_CLASE = {
    ClaseAjuste.DESCUENTO: "Descuento",
    ClaseAjuste.CORTESIA: "Cortesía",
}


def texto_ajuste(ajuste: AjusteEnDocumento) -> str:
    """«Cortesía 10 %» o «Descuento $ 5000.00»."""
    return f"{NOMBRE_CLASE[ajuste.clase]} {ajuste.descripcion}"


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
            # DEC-AJ-09: ausente en los snapshots anteriores.
            f"Horario: {empresa.horario}" if empresa.horario else None,
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
        TITULO_DOCUMENTO[type(contenido)],
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
        ("Cliente", cliente.nombre_apellido if cliente else "—"),
        # UX-06: el DNI de la copia del documento; si no se cargo, se dice
        # (nunca se inventa).
        ("DNI", (cliente.dni or "sin DNI") if cliente else "—"),
        ("Teléfono", cliente.telefono if cliente else "—"),
    ]
    if cliente and cliente.email:
        izquierda.append(("Email", cliente.email))
    # UX-02: el identificador interno del equipo, con o sin IMEI. DEC-AJ-06:
    # sin IMEI se aclara que es provisorio y que no es un IMEI.
    derecha = [("Equipo", equipo.nombre), ("Identificador", equipo.id)]
    if not equipo.imei and getattr(contenido, "imei_no_disponible", False):
        derecha.append(("IMEI", "no disponible (identificador provisorio)"))
    if equipo.capacidad:
        derecha.append(("Capacidad", equipo.capacidad))
    if equipo.color:
        derecha.append(("Color", equipo.color))
    derecha.append(("Ingreso", fecha_hora(contenido.fecha_ingreso, zona)))
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
    if observaciones_unificadas(contenido):
        # DEC-UX-03: un solo texto para lo declarado y lo observado.
        texto = (
            getattr(contenido, "observaciones", None) or equipo.falla_reportada
        )
        hoja.parrafo(f"Observaciones del equipo: {texto}", tamano=9)
    else:
        hoja.parrafo(f"Falla declarada: {equipo.falla_reportada}", tamano=9)


def observaciones_unificadas(contenido) -> bool:
    """DEC-UX-03: el ingreso se registro con el texto unico «Observaciones
    del equipo» (marca explicita de la recepcion): se muestra una vez. En
    lo registrado antes, cada dato con su nombre."""
    return bool(getattr(contenido, "observaciones_unificadas", False))


def _dato(hoja: _Hoja, etiqueta: str, valor: str) -> None:
    """Una linea "Etiqueta: valor" que corta el valor si es largo."""
    sangria = ancho_texto(f"{etiqueta}: ", 9)
    lineas = cortar(valor, ANCHO_UTIL - sangria, 9.5)
    for indice, linea in enumerate(lineas):
        hoja.asegurar(13)
        hoja.bajar(13)
        if indice == 0:
            hoja.pdf.texto(MARGEN, hoja.y, f"{etiqueta}:", tamano=9, gris=0.35)
        hoja.pdf.texto(MARGEN + sangria, hoja.y, linea, tamano=9.5)


def _recepcion(
    hoja: _Hoja, contenido: ContenidoComprobanteIngreso, zona: tzinfo
) -> None:
    """Como se recibio el equipo. Solo lo visible: nunca notas internas."""
    hoja.titulo("Recepción del equipo")
    hoja.bajar(2)
    # DEC-AJ-05: lo que pidio el cliente, en texto libre.
    if contenido.trabajo_solicitado:
        _dato(hoja, "Trabajo solicitado", contenido.trabajo_solicitado)
    unificadas = observaciones_unificadas(contenido)
    # DEC-UX-03: con el texto unico no hay un estado fisico aparte (ya salio
    # una vez como «Observaciones del equipo»).
    if not unificadas or contenido.estado_fisico:
        _dato(hoja, "Estado físico", contenido.estado_fisico or "—")
    # Ya no se piden al ingresar: solo si la Orden los tiene registrados.
    if contenido.accesorios:
        _dato(hoja, "Accesorios", ", ".join(contenido.accesorios))
    # DEC-AJ-07: informativa; no es el check-in de entrega.
    if contenido.funcionalidades_verificadas is not None:
        respuesta = "Sí" if contenido.funcionalidades_verificadas else "No"
        if contenido.observaciones_verificacion:
            respuesta += f". {contenido.observaciones_verificacion}"
        _dato(hoja, "Funcionalidades verificadas al ingresar", respuesta)
    if contenido.checkin is not None:
        _dato(
            hoja,
            "Check-in",
            "Realizado" if contenido.checkin else "No realizado",
        )
    if contenido.observaciones and not unificadas:
        _dato(hoja, "Observaciones", contenido.observaciones)
    for nota in contenido.notas:
        _dato(hoja, "Observación", nota)
    if contenido.confirmada_en is not None:
        recibio = (
            f" por {contenido.confirmada_por.nombre}"
            if contenido.confirmada_por
            else ""
        )
        _dato(
            hoja,
            "Recibido",
            f"{fecha_hora(contenido.confirmada_en, zona)}{recibio}",
        )


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


def _totales(
    hoja: _Hoja,
    subtotal: Decimal | None,
    descuento: DescuentoEnDocumento | None,
    total: Decimal,
    contenido=None,
) -> None:
    """Total autorizado; con descuento, antes el subtotal y el descuento.

    DEC-AJ-10: en los emitidos desde entonces, los ajustes de los trabajos
    (ya en cada renglon) y el de la Orden van en lineas aparte, con su
    clase y sin el motivo (queda en el registro interno).
    """
    pdf = hoja.pdf
    filas: list[tuple[str, str, bool]] = []
    por_trabajo = bool(getattr(contenido, "ajustes_por_trabajo", False))
    if por_trabajo and descuento is not None and subtotal is not None:
        filas.append(("Subtotal", importe(subtotal), False))
        de_trabajos = sum(
            (t.ajuste.importe for t in contenido.trabajos if t.ajuste),
            Decimal("0"),
        )
        if de_trabajos > 0:
            filas.append(
                (
                    "Ajustes de los trabajos",
                    "- " + importe(de_trabajos),
                    False,
                )
            )
        if contenido.ajuste_orden is not None:
            filas.append(
                (
                    f"{texto_ajuste(contenido.ajuste_orden)} sobre la Orden",
                    "- " + importe(contenido.ajuste_orden.importe),
                    False,
                )
            )
        descuento = None
    elif descuento is not None and subtotal is not None:
        filas.append(("Subtotal", importe(subtotal), False))
        filas.append(
            (
                f"Descuento ({descuento.descripcion})",
                "- " + importe(descuento.importe),
                False,
            )
        )
    filas.append(("Total autorizado", importe(total), True))
    hoja.asegurar(8 + 16 * len(filas) + (13 if descuento else 0))
    for etiqueta, valor, negrita in filas:
        hoja.bajar(18 if negrita else 15)
        tamano = 10.5 if negrita else 9.5
        pdf.texto(
            COL_AUTORIZACION, hoja.y, etiqueta, tamano=tamano, negrita=negrita
        )
        pdf.texto(
            COL_PRECIO,
            hoja.y,
            valor,
            tamano=tamano,
            negrita=negrita,
            derecha=True,
        )
    if descuento is not None:
        hoja.parrafo(
            f"Motivo del descuento: {descuento.motivo}",
            tamano=8.5,
            gris=0.3,
            x=COL_AUTORIZACION,
            ancho=DERECHA - COL_AUTORIZACION,
        )


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
        # DEC-AJ-10 (D-10.5): precio original, ajuste y precio final.
        ajuste = getattr(trabajo, "ajuste", None)
        renglon_ajuste = (
            cortar(
                f"{texto_ajuste(ajuste)}: - {importe(ajuste.importe)} · "
                f"Precio final {importe(trabajo.precio_final)}",
                ANCHO_TRABAJO,
                8.5,
            )
            if ajuste is not None and trabajo.precio_final is not None
            else []
        )
        alto = (
            13 * max(len(nombre), len(autorizacion))
            + 12 * len(renglon_ajuste)
            + 6
        )
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
        base = y - 13 * max(len(nombre), len(autorizacion))
        for indice, linea in enumerate(renglon_ajuste):
            pdf.texto(
                COL_TRABAJO + 10,
                base - 12 * (indice + 1),
                linea,
                tamano=8.5,
                gris=0.3,
            )
        hoja.bajar(alto)
        pdf.linea(MARGEN, hoja.y + 3, DERECHA, hoja.y + 3, gris=0.85)
    hoja.encabezado_tabla = None
    if isinstance(contenido, ContenidoComprobanteIngreso):
        _totales(
            hoja,
            contenido.subtotal,
            contenido.descuento,
            contenido.total,
            contenido,
        )
    else:
        _totales(
            hoja,
            contenido.subtotal_autorizado,
            contenido.descuento,
            contenido.total_autorizado,
            contenido,
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


def _pie_de_empresa(hoja: _Hoja, contenido) -> None:
    """DEC-AJ-09: el pie libre que Administracion configuro, tal como se
    copio al emitir (ausente en los snapshots anteriores)."""
    pie = contenido.empresa.pie_comprobante
    if not pie:
        return
    hoja.bajar(10)
    for parrafo in pie.splitlines():
        if parrafo.strip():
            hoja.parrafo(parrafo.strip(), tamano=8.5, gris=0.3)


def _firma(hoja: _Hoja) -> None:
    """UX-06 y UX-07: espacio para la firma y la aclaracion del cliente. La
    firma es opcional (DEC-MI-06): el papel firmado o su foto se registran
    despues en la Orden y nunca bloquean la recepcion."""
    pdf = hoja.pdf
    alto = 78
    hoja.asegurar(alto + 16)
    hoja.bajar(16)
    pdf.rectangulo(
        MARGEN, hoja.y - alto, ANCHO_UTIL, alto, relleno=None, borde=0.6
    )
    pdf.texto(
        MARGEN + 10,
        hoja.y - 16,
        "Conformidad del cliente con la recepción del equipo",
        tamano=9.5,
        negrita=True,
    )
    base = hoja.y - alto + 22
    ancho = (ANCHO_UTIL - 40) / 3
    for indice, etiqueta in enumerate(("Firma", "Aclaración", "DNI")):
        x = MARGEN + 10 + indice * (ancho + 10)
        pdf.linea(x, base, x + ancho, base, gris=0.4)
        pdf.texto(x, base - 12, etiqueta, tamano=8.5, gris=0.35)
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
    """PDF del comprobante de autorizacion o del de ingreso.

    Comparten el armado; el de ingreso suma la recepcion del equipo.
    """
    contenido = documento.contenido
    nombre = TITULO_DOCUMENTO[type(contenido)].capitalize()
    pdf = Pdf(
        titulo=f"{nombre} {documento.id} — Orden {contenido.orden_id}",
        fecha=documento.fecha_emision,
        autor=contenido.empresa.nombre,
    )
    hoja = _Hoja(pdf)
    _encabezado(hoja, documento, zona_horaria)
    _cliente_y_equipo(hoja, contenido, zona_horaria)
    if isinstance(contenido, ContenidoComprobanteIngreso):
        _recepcion(hoja, contenido, zona_horaria)
    _trabajos(hoja, contenido, zona_horaria)
    _version(hoja, documento)
    _leyenda(hoja, contenido)
    if isinstance(contenido, ContenidoComprobanteIngreso):
        _firma(hoja)
    _pie_de_empresa(hoja, contenido)
    _pies(pdf, documento)
    return pdf.bytes()


def pdf_de_documento(
    documento: DocumentoEmitido, *, zona_horaria: tzinfo
) -> tuple[str, bytes]:
    """Nombre de archivo y PDF de un documento emitido.

    Se descargan como PDF el comprobante de ingreso y el de autorizacion;
    los demas se imprimen (o guardan como PDF) desde el navegador.
    """
    if not isinstance(documento.contenido, tuple(TITULO_DOCUMENTO)):
        raise PrecondicionInvalidaError(
            f"{documento.id} no se descarga como PDF: se imprime desde la "
            "pantalla de la Orden."
        )
    return (
        f"{documento.id}.pdf",
        pdf_comprobante_autorizacion(documento, zona_horaria=zona_horaria),
    )
