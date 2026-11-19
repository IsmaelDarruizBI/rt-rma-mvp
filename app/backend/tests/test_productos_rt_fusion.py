"""Reparacion RT (etapa 1, tareas 1.1 y 1.4): reglas de la copia de
Productos de Gestion RT, sin base. Diseño: docs/reparacion-rt-discovery.md,
secciones 2.4 a 2.7.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.integraciones.catalogo.ventas import tipos_producto_desde_tabla
from app.integraciones.gestion_rt import (
    COLUMNAS,
    ProductosRtOrigenInvalidoError,
)
from app.integraciones.gestion_rt.contrato import tabla_desde_filas
from app.services import permisos
from app.services.productos_rt import (
    ProductosRtRechazadoError,
    ReglasProductosRt,
    analizar_imei,
    es_variante_del_estado,
    fusionar_productos_rt,
    normalizar_busqueda,
    terminos_de_busqueda,
)
from tests.fixtures import catalogo_ventas
from tests.fixtures import productos_rt as ficticios
from tests.fixtures.productos_rt import imei_ficticio, producto

ZONA = timezone(timedelta(hours=-3))
T1 = datetime(2026, 11, 19, 12, tzinfo=UTC)
T2 = T1 + timedelta(hours=2)
T3 = T2 + timedelta(hours=2)
REGLAS = ReglasProductosRt()


def _fusionar(actuales, filas=None, *, fecha=T1, reglas=REGLAS, tipos=None):
    tabla = tabla_desde_filas(
        COLUMNAS,
        ficticios.productos_base() if filas is None else filas,
        zona=ZONA,
        error=ProductosRtOrigenInvalidoError,
    )
    tipos_filas = ficticios.tipos_base() if tipos is None else tipos
    return fusionar_productos_rt(
        actuales,
        tabla.filas,
        tipos_producto_desde_tabla(
            catalogo_ventas.ENCABEZADOS,
            tipos_filas,
            marcas={"IPHONE": "Apple"},
        ),
        fecha=fecha,
        reglas=reglas,
        leidos=tabla.leidos,
        descartados=tabla.descartados,
        faltantes=tabla.faltantes,
    )


def _por_id(fusion):
    return {p.producto_id: p for p in fusion.productos}


# --- IMEI y busqueda ---------------------------------------------------------


def test_imei_valido_con_y_sin_digito_verificador():
    imei = imei_ficticio(1)
    assert analizar_imei(imei) == (imei, True, True)
    assert analizar_imei(f" {imei[:5]} {imei[5:]} ") == (imei, True, True)
    otro = imei[:-1] + str((int(imei[-1]) + 1) % 10)
    assert analizar_imei(otro) == (otro, True, False)


@pytest.mark.parametrize(
    ("valor", "normalizado"),
    [
        ("12345", "12345"),
        ("3.59999E+14", "3.59999E+14"),
        ("35-999-90000000-1", "35-999-90000000-1"),
        ("ABCDEFGHIJKLMNO", "ABCDEFGHIJKLMNO"),
    ],
)
def test_imei_invalido_se_guarda_y_no_se_usa(valor, normalizado):
    assert analizar_imei(valor) == (normalizado, False, None)


@pytest.mark.parametrize("valor", [None, "", "   "])
def test_imei_ausente(valor):
    assert analizar_imei(valor) == (None, False, None)


def test_busqueda_sin_mayusculas_ni_tildes():
    assert normalizar_busqueda("  iPhone  12 PRO  Máx ") == "iphone 12 pro max"
    assert terminos_de_busqueda("Pro  máx") == ["pro", "max"]
    assert terminos_de_busqueda("   ") == []


def test_variantes_del_estado():
    assert es_variante_del_estado("reparacion", "Reparacion")
    assert es_variante_del_estado("Reparación", "Reparacion")
    assert not es_variante_del_estado("Reparacion", "Reparacion")
    assert not es_variante_del_estado("Stock", "Reparacion")


# --- Primera sincronizacion --------------------------------------------------


def test_primera_sincronizacion_de_los_datos_ficticios():
    fusion = _fusionar([])
    productos = _por_id(fusion)
    listables = [p for p in fusion.productos if p.listable]
    assert len(listables) == ficticios.EN_REPARACION
    por_sede = {}
    for p in listables:
        por_sede[p.sede] = por_sede.get(p.sede, 0) + 1
    assert por_sede == ficticios.EN_REPARACION_POR_SEDE
    # Ni variantes, ni otros estados, ni eliminados nuevos, ni repetidos.
    excluidos = ("900013", "900014", "900015", "900016", "900018", "900020")
    for ausente in excluidos:
        assert ausente not in productos
    assert set(productos) == {p.producto_id for p in listables}
    c = fusion.contadores
    assert c["leidos"] == ficticios.LEIDOS
    assert c["descartados"] == ficticios.DESCARTADOS
    assert c["duplicados"] == 1
    assert c["nuevos"] == ficticios.EN_REPARACION
    assert c["en_reparacion"] == ficticios.EN_REPARACION
    assert c["imei_repetidos"] == 2


def test_datos_de_un_producto_y_su_tipo():
    p = _por_id(_fusionar([]))["900002"]
    assert p.en_reparacion and p.en_reparacion_desde == T1
    assert p.primera_vez_visto_en == T1 and p.sincronizado_en == T1
    assert p.estado_gestion_rt == "Reparacion"
    assert p.imei == imei_ficticio(2) and p.imei_valido and p.imei_luhn_valido
    assert p.tipo_producto_encontrado and not p.tipo_producto_eliminado
    assert p.modelo == "iPhone 12 Pro Max"
    assert p.capacidad == "256 GB" and p.color == "Deep Purple"
    assert p.categoria == "IPHONE" and p.subcategoria == "IPHONE USADOS"
    assert p.bateria == "87" and p.defecto.startswith("Pantalla")
    assert p.creado_en_origen == datetime(2026, 11, 10, 15, tzinfo=UTC)
    assert "900002" in p.texto_busqueda
    assert imei_ficticio(2) in p.texto_busqueda
    assert "iphone 12 pro max" in p.texto_busqueda
    assert len(p.huella) == 64


def test_casos_especiales_de_la_primera_sincronizacion():
    productos = _por_id(_fusionar([]))
    assert productos["900004"].imei is None
    assert not productos["900004"].imei_valido
    assert productos["900005"].imei == "12345"
    assert not productos["900005"].imei_valido
    assert not productos["900006"].imei_valido  # notacion cientifica
    assert not productos["900007"].tipo_producto_encontrado
    assert productos["900007"].tipo_producto_id == ficticios.TP_INEXISTENTE
    assert productos["900007"].modelo is None
    assert productos["900008"].tipo_producto_eliminado
    assert productos["900008"].modelo == "iPhone 11"
    assert productos["900009"].imei_repetido
    assert productos["900010"].imei_repetido
    assert productos["900009"].subcategoria == "IPHONE NUEVOS"
    assert productos["900011"].en_reparacion  # « Reparacion » recortado
    assert productos["900012"].sede == "Rosario Norte"
    assert productos["900021"].creado_en_origen is None


def test_avisos_sin_imei_ni_valores_del_origen():
    fusion = _fusionar([])
    texto = " ".join(fusion.avisos)
    assert "900018" in texto  # repetido
    assert "900013" in texto and "900014" in texto  # variantes
    assert "Rosario Norte" in texto
    assert "900007" in texto  # TipoProducto inexistente
    assert "900021" in texto  # fecha
    assert "comparten su IMEI" in texto
    for numero in range(1, 23):
        assert imei_ficticio(numero) not in texto
    assert ficticios.VALOR_SENSIBLE not in texto


def test_repetir_la_misma_lectura_no_cambia_nada():
    primera = _fusionar([])
    segunda = _fusionar(list(primera.productos), fecha=T2)
    c = segunda.contadores
    assert c["nuevos"] == 0 and c["actualizados"] == 0
    assert c["sin_cambios"] == ficticios.EN_REPARACION

    def datos(fusion):
        return {
            p.producto_id: p.model_dump(exclude={"sincronizado_en"})
            for p in fusion.productos
        }

    assert datos(primera) == datos(segunda)
    assert all(p.sincronizado_en == T2 for p in segunda.productos)


# --- Cambios de estado (seccion 2.7) -----------------------------------------


def _con_cambios(cambios: dict[str, dict], quitar: tuple[str, ...] = ()):
    """Los datos base con algunas filas cambiadas o quitadas."""
    filas = []
    for fila in ficticios.productos_base():
        pid = fila[COLUMNAS.index("producto_id")]
        if pid in quitar:
            continue
        for columna, valor in cambios.get(pid, {}).items():
            fila[COLUMNAS.index(columna)] = valor
        filas.append(fila)
    return filas


def test_sale_de_reparacion_y_vuelve_con_un_periodo_nuevo():
    primera = _fusionar([])
    sale = _fusionar(
        list(primera.productos),
        _con_cambios({"900001": {"producto_status": "Stock"}}),
        fecha=T2,
    )
    p = _por_id(sale)["900001"]
    assert not p.en_reparacion and not p.listable
    assert p.estado_gestion_rt == "Stock"
    assert p.salio_de_reparacion_en == T2 and p.en_reparacion_desde == T1
    assert sale.contadores["salieron"] == 1
    assert sale.contadores["en_reparacion"] == ficticios.EN_REPARACION - 1

    vuelve = _fusionar(list(sale.productos), fecha=T3)
    p = _por_id(vuelve)["900001"]
    assert p.en_reparacion and p.listable
    assert p.en_reparacion_desde == T3 and p.salio_de_reparacion_en is None
    assert p.primera_vez_visto_en == T1
    assert vuelve.contadores["volvieron"] == 1


def test_un_producto_que_ya_estaba_se_sigue_aunque_cambie_de_estado():
    primera = _fusionar([])
    vendido = _fusionar(
        list(primera.productos),
        _con_cambios({"900003": {"producto_status": "Vendido"}}),
        fecha=T2,
    )
    assert _por_id(vendido)["900003"].estado_gestion_rt == "Vendido"


def test_eliminado_en_gestion_rt_no_se_lista_ni_se_borra():
    primera = _fusionar([])
    fusion = _fusionar(
        list(primera.productos),
        _con_cambios({"900003": {"producto_eliminado": "yes"}}),
        fecha=T2,
    )
    p = _por_id(fusion)["900003"]
    assert p.eliminado_en_origen and not p.listable
    assert fusion.contadores["eliminados"] == 1


def test_ausente_del_origen_queda_marcado_y_vuelve_si_reaparece():
    primera = _fusionar([])
    falta = _fusionar(
        list(primera.productos), _con_cambios({}, quitar=("900002",)), fecha=T2
    )
    p = _por_id(falta)["900002"]
    assert not p.presente_en_origen and not p.listable
    assert p.en_reparacion  # no se sabe que salio: no se lista igual
    assert falta.contadores["ausentes"] == 1
    reaparece = _fusionar(list(falta.productos), fecha=T3)
    p = _por_id(reaparece)["900002"]
    assert p.presente_en_origen and p.listable
    assert p.en_reparacion_desde == T1  # nunca salio de Reparacion


def test_una_lectura_truncada_se_rechaza():
    primera = _fusionar([])
    pocas = ficticios.productos_base()[:5]
    with pytest.raises(ProductosRtRechazadoError, match="incompleta"):
        _fusionar(list(primera.productos), pocas, fecha=T2)


def test_la_proteccion_no_rige_con_pocos_productos():
    reglas = ReglasProductosRt(minimo_proteccion=100)
    primera = _fusionar([], reglas=reglas)
    fusion = _fusionar(list(primera.productos), [], fecha=T2, reglas=reglas)
    assert fusion.contadores["ausentes"] == ficticios.EN_REPARACION
    assert fusion.contadores["en_reparacion"] == 0


def test_umbral_configurable():
    primera = _fusionar([])
    mitad = ficticios.productos_base()[:12]
    with pytest.raises(ProductosRtRechazadoError):
        _fusionar(
            list(primera.productos),
            mitad,
            fecha=T2,
            reglas=ReglasProductosRt(umbral_desaparicion=0.1),
        )
    _fusionar(list(primera.productos), mitad, fecha=T2)  # 2 de 14: se aplica


# --- Duplicados e identidad (seccion 2.4) ------------------------------------


def test_id_repetido_conserva_los_datos_anteriores():
    primera = _fusionar([])
    repetida = ficticios.productos_base()
    repetida.append(producto("900001", imei=imei_ficticio(99), sede="RMA"))
    fusion = _fusionar(list(primera.productos), repetida, fecha=T2)
    p = _por_id(fusion)["900001"]
    anterior = _por_id(primera)["900001"]
    assert p.conflicto_origen
    assert p.imei == anterior.imei and p.sede == "Alippi"
    assert "900001" in " ".join(fusion.avisos)
    resuelto = _fusionar(list(fusion.productos), fecha=T3)
    assert not _por_id(resuelto)["900001"].conflicto_origen


def test_cambio_de_imei_o_tipo_marca_la_identidad():
    primera = _fusionar([])
    cambio = _fusionar(
        list(primera.productos),
        _con_cambios(
            {
                "900001": {"producto_imei": imei_ficticio(55)},
                "900003": {"producto_tp": ficticios.TP_SE},
            }
        ),
        fecha=T2,
    )
    productos = _por_id(cambio)
    for pid in ("900001", "900003"):
        assert productos[pid].cambio_identidad
    assert productos["900001"].identidad_anterior["imei"] == imei_ficticio(1)
    assert productos["900003"].identidad_anterior["tipo_producto_id"] == (
        ficticios.TP_16
    )
    assert productos["900003"].modelo == "iPhone SE 2020"
    assert not productos["900002"].cambio_identidad
    assert "900001" in " ".join(cambio.avisos)


def test_completar_un_imei_que_faltaba_no_es_cambio_de_identidad():
    primera = _fusionar([])
    completo = _fusionar(
        list(primera.productos),
        _con_cambios({"900004": {"producto_imei": imei_ficticio(44)}}),
        fecha=T2,
    )
    p = _por_id(completo)["900004"]
    assert p.imei_valido and not p.cambio_identidad


def test_imei_repetido_se_desmarca_cuando_deja_de_repetirse():
    primera = _fusionar([])
    fusion = _fusionar(
        list(primera.productos),
        _con_cambios({"900010": {"producto_imei": imei_ficticio(10)}}),
        fecha=T2,
    )
    productos = _por_id(fusion)
    assert not productos["900009"].imei_repetido
    assert not productos["900010"].imei_repetido


def test_un_eliminado_no_cuenta_para_el_imei_repetido():
    primera = _fusionar([])
    fusion = _fusionar(
        list(primera.productos),
        _con_cambios({"900010": {"producto_eliminado": "TRUE"}}),
        fecha=T2,
    )
    assert not _por_id(fusion)["900009"].imei_repetido


def test_sin_tipos_el_producto_se_copia_igual():
    fusion = _fusionar([], tipos=[])
    p = _por_id(fusion)["900001"]
    assert not p.tipo_producto_encontrado and p.modelo is None
    assert p.listable


# --- Permisos (seccion 6.3) --------------------------------------------------


def test_permisos_predeterminados():
    consultar = permisos.PRODUCTOS_RT_CONSULTAR
    sincronizar = permisos.PRODUCTOS_RT_SINCRONIZAR
    assert set(consultar.predeterminados) == {
        permisos.RECEP,
        permisos.COORD,
        permisos.ADMIN,
    }
    assert consultar.consulta and consultar.configurable
    assert sincronizar.predeterminados == (permisos.ADMIN,)
    assert sincronizar.configurable
    assert permisos.TECH not in consultar
