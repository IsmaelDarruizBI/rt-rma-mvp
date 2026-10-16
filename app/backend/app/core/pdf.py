"""Escritor de PDF minimo, sin dependencias.

Lo justo para un comprobante de una o pocas paginas A4: texto en
Helvetica y Helvetica-Bold (las fuentes estandar que todo lector de PDF
trae, con codificacion WinAnsi: acentos, enie, comillas angulares), lineas
y rectangulos. No embebe fuentes ni imagenes y no comprime: el archivo es
chico y el texto se puede buscar.

Es deterministico: los mismos datos dan los mismos bytes (la fecha del
documento la pasa quien lo arma), asi que un snapshot reproduce siempre
el mismo PDF.

    Pdf            paginas, dibujo y ``bytes()``
    ancho_texto    ancho de un texto en puntos, para alinear y cortar
    cortar         corta un texto en lineas que entran en un ancho
"""

import unicodedata
from datetime import datetime

ANCHO_A4 = 595.28
ALTO_A4 = 841.89

# Anchos (1/1000 del tamano) de los caracteres 32..126, de los AFM de
# Helvetica y Helvetica-Bold.
_ANCHOS = {
    False: [
        278,
        278,
        355,
        556,
        556,
        889,
        667,
        191,
        333,
        333,
        389,
        584,
        278,
        333,
        278,
        278,
        556,
        556,
        556,
        556,
        556,
        556,
        556,
        556,
        556,
        556,
        278,
        278,
        584,
        584,
        584,
        556,
        1015,
        667,
        667,
        722,
        722,
        667,
        611,
        778,
        722,
        278,
        500,
        667,
        556,
        833,
        722,
        778,
        667,
        778,
        722,
        667,
        611,
        722,
        667,
        944,
        667,
        667,
        611,
        278,
        278,
        278,
        469,
        556,
        333,
        556,
        556,
        500,
        556,
        556,
        278,
        556,
        556,
        222,
        222,
        500,
        222,
        833,
        556,
        556,
        556,
        556,
        333,
        500,
        278,
        556,
        500,
        722,
        500,
        500,
        500,
        334,
        260,
        334,
        584,
    ],
    True: [
        278,
        333,
        474,
        556,
        556,
        889,
        722,
        238,
        333,
        333,
        389,
        584,
        278,
        333,
        278,
        278,
        556,
        556,
        556,
        556,
        556,
        556,
        556,
        556,
        556,
        556,
        333,
        333,
        584,
        584,
        584,
        611,
        975,
        722,
        722,
        722,
        722,
        667,
        611,
        778,
        722,
        278,
        556,
        722,
        611,
        833,
        722,
        778,
        667,
        778,
        722,
        667,
        611,
        722,
        667,
        944,
        667,
        667,
        611,
        333,
        278,
        333,
        584,
        556,
        333,
        556,
        611,
        556,
        611,
        556,
        333,
        611,
        611,
        278,
        278,
        556,
        278,
        889,
        611,
        611,
        611,
        611,
        389,
        556,
        333,
        611,
        556,
        778,
        556,
        556,
        500,
        389,
        280,
        389,
        584,
    ],
}
# Fuera de ASCII: los que no se derivan de su letra base.
_ANCHOS_EXTRA = {
    "«": 556,
    "»": 556,
    "·": 278,
    "—": 1000,
    "–": 556,
    "°": 400,
    "º": 365,
    "ª": 370,
    "¿": 611,
    "¡": 333,
    "€": 556,
    "…": 1000,
    "“": 333,
    "”": 333,
    "‘": 222,
    "’": 222,
    "•": 350,
}


def _ancho_caracter(caracter: str, negrita: bool) -> int:
    codigo = ord(caracter)
    if 32 <= codigo <= 126:
        return _ANCHOS[negrita][codigo - 32]
    if caracter in _ANCHOS_EXTRA:
        return _ANCHOS_EXTRA[caracter]
    base = unicodedata.normalize("NFD", caracter)[:1]
    if base and 32 <= ord(base) <= 126:
        return _ANCHOS[negrita][ord(base) - 32]
    return 556


def ancho_texto(texto: str, tamano: float, negrita: bool = False) -> float:
    """Ancho del texto en puntos con esa fuente y tamano."""
    return (
        sum(_ancho_caracter(caracter, negrita) for caracter in texto)
        * tamano
        / 1000
    )


def cortar(
    texto: str, ancho: float, tamano: float, negrita: bool = False
) -> list[str]:
    """Lineas que entran en ``ancho``, cortando entre palabras.

    Una palabra mas larga que el ancho se corta donde haga falta. Los
    saltos de linea del texto se respetan.
    """
    lineas: list[str] = []
    for parrafo in texto.splitlines() or [""]:
        actual = ""
        for palabra in parrafo.split():
            candidata = f"{actual} {palabra}" if actual else palabra
            if ancho_texto(candidata, tamano, negrita) <= ancho:
                actual = candidata
                continue
            if actual:
                lineas.append(actual)
            while ancho_texto(palabra, tamano, negrita) > ancho:
                corte = len(palabra) - 1
                while (
                    corte > 1
                    and ancho_texto(palabra[:corte], tamano, negrita) > ancho
                ):
                    corte -= 1
                lineas.append(palabra[:corte])
                palabra = palabra[corte:]
            actual = palabra
        lineas.append(actual)
    return lineas


def _cadena(texto: str) -> bytes:
    """Texto como cadena literal de PDF en WinAnsi (cp1252)."""
    datos = texto.encode("cp1252", errors="replace")
    return (
        b"("
        + datos.replace(b"\\", b"\\\\")
        .replace(b"(", b"\\(")
        .replace(b")", b"\\)")
        .replace(b"\r", b"")
        .replace(b"\n", b" ")
        + b")"
    )


def _numero(valor: float) -> bytes:
    return f"{valor:.2f}".rstrip("0").rstrip(".").encode("ascii") or b"0"


def _fecha_pdf(fecha: datetime) -> bytes:
    desfase = fecha.utcoffset()
    sufijo = "Z"
    if desfase is not None and desfase.total_seconds():
        minutos = int(desfase.total_seconds() // 60)
        signo = "+" if minutos >= 0 else "-"
        minutos = abs(minutos)
        sufijo = f"{signo}{minutos // 60:02d}'{minutos % 60:02d}'"
    return f"D:{fecha:%Y%m%d%H%M%S}{sufijo}".encode("ascii")


class Pdf:
    """Un documento A4 que se dibuja pagina por pagina.

    Coordenadas en puntos, con el origen ABAJO a la izquierda (como en
    PDF). ``pagina`` empieza una pagina nueva; todo lo que se dibuja va a
    la ultima.
    """

    def __init__(self, *, titulo: str, fecha: datetime, autor: str = ""):
        self.titulo = titulo
        self.fecha = fecha
        self.autor = autor
        self._paginas: list[list[bytes]] = []
        self.pagina()

    @property
    def cantidad_paginas(self) -> int:
        return len(self._paginas)

    def pagina(self) -> None:
        self._paginas.append([])

    def en_pagina(self, indice: int) -> "_Lienzo":
        """Dibuja en una pagina ya creada (por ejemplo, el pie)."""
        return _Lienzo(self._paginas[indice])

    def _actual(self) -> "_Lienzo":
        return _Lienzo(self._paginas[-1])

    def texto(self, *args, **kwargs) -> None:
        self._actual().texto(*args, **kwargs)

    def linea(self, *args, **kwargs) -> None:
        self._actual().linea(*args, **kwargs)

    def rectangulo(self, *args, **kwargs) -> None:
        self._actual().rectangulo(*args, **kwargs)

    def bytes(self) -> bytes:
        objetos: list[bytes] = []

        def agregar(contenido: bytes) -> int:
            objetos.append(contenido)
            return len(objetos)

        catalogo = agregar(b"")  # se completa al final
        paginas = agregar(b"")
        normal = agregar(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        )
        negrita = agregar(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>"
        )
        hijas = []
        for operaciones in self._paginas:
            flujo = b"\n".join(operaciones)
            contenido = agregar(
                b"<< /Length "
                + str(len(flujo)).encode("ascii")
                + b" >>\nstream\n"
                + flujo
                + b"\nendstream"
            )
            hijas.append(
                agregar(
                    b"<< /Type /Page /Parent "
                    + f"{paginas} 0 R".encode("ascii")
                    + b" /MediaBox [0 0 "
                    + _numero(ANCHO_A4)
                    + b" "
                    + _numero(ALTO_A4)
                    + b"] /Resources << /Font << /F1 "
                    + f"{normal} 0 R /F2 {negrita} 0 R".encode("ascii")
                    + b" >> >> /Contents "
                    + f"{contenido} 0 R".encode("ascii")
                    + b" >>"
                )
            )
        objetos[catalogo - 1] = (
            b"<< /Type /Catalog /Pages "
            + f"{paginas} 0 R".encode("ascii")
            + b" >>"
        )
        objetos[paginas - 1] = (
            b"<< /Type /Pages /Kids ["
            + b" ".join(f"{hija} 0 R".encode("ascii") for hija in hijas)
            + b"] /Count "
            + str(len(hijas)).encode("ascii")
            + b" >>"
        )
        info = agregar(
            b"<< /Title "
            + _cadena(self.titulo)
            + b" /Author "
            + _cadena(self.autor)
            + b" /Producer (Rosario Tecno RMA) /CreationDate ("
            + _fecha_pdf(self.fecha)
            + b") >>"
        )

        salida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        posiciones = []
        for numero, contenido in enumerate(objetos, start=1):
            posiciones.append(len(salida))
            salida += f"{numero} 0 obj\n".encode("ascii")
            salida += contenido + b"\nendobj\n"
        inicio_xref = len(salida)
        salida += f"xref\n0 {len(objetos) + 1}\n".encode("ascii")
        salida += b"0000000000 65535 f \n"
        for posicion in posiciones:
            salida += f"{posicion:010d} 00000 n \n".encode("ascii")
        salida += (
            f"trailer\n<< /Size {len(objetos) + 1} /Root {catalogo} 0 R "
            f"/Info {info} 0 R >>\nstartxref\n{inicio_xref}\n%%EOF\n"
        ).encode("ascii")
        return bytes(salida)


class _Lienzo:
    """Las operaciones de dibujo de una pagina."""

    def __init__(self, operaciones: list[bytes]):
        self._operaciones = operaciones

    def texto(
        self,
        x: float,
        y: float,
        texto: str,
        *,
        tamano: float = 10,
        negrita: bool = False,
        gris: float = 0,
        derecha: bool = False,
    ) -> None:
        """Una linea de texto; con ``derecha``, ``x`` es el borde derecho."""
        if derecha:
            x -= ancho_texto(texto, tamano, negrita)
        self._operaciones.append(
            b"BT /"
            + (b"F2 " if negrita else b"F1 ")
            + _numero(tamano)
            + b" Tf "
            + _numero(gris)
            + b" g "
            + _numero(x)
            + b" "
            + _numero(y)
            + b" Td "
            + _cadena(texto)
            + b" Tj ET"
        )

    def linea(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        grosor: float = 0.5,
        gris: float = 0.7,
    ) -> None:
        self._operaciones.append(
            _numero(grosor)
            + b" w "
            + _numero(gris)
            + b" G "
            + b" ".join(_numero(v) for v in (x1, y1))
            + b" m "
            + b" ".join(_numero(v) for v in (x2, y2))
            + b" l S"
        )

    def rectangulo(
        self,
        x: float,
        y: float,
        ancho: float,
        alto: float,
        *,
        relleno: float | None = None,
        borde: float | None = 0.7,
        grosor: float = 0.5,
    ) -> None:
        """Rectangulo con esquina inferior izquierda en (x, y)."""
        partes = [_numero(grosor) + b" w"]
        if relleno is not None:
            partes.append(_numero(relleno) + b" g")
        if borde is not None:
            partes.append(_numero(borde) + b" G")
        partes.append(
            b" ".join(_numero(v) for v in (x, y, ancho, alto)) + b" re"
        )
        if relleno is not None and borde is not None:
            partes.append(b"B")
        elif relleno is not None:
            partes.append(b"f")
        else:
            partes.append(b"S")
        self._operaciones.append(b" ".join(partes))
