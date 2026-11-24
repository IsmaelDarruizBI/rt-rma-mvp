# ruff: noqa: E501  (textos largos)
"""Carga DATOS FICTICIOS para la validación manual local, por la API.

Todo pasa por el backend que está corriendo (no escribe SQL): así se
aplican las mismas reglas, códigos automáticos, auditoría e historial que
cuando se carga a mano desde la pantalla.

**Se corre una sola vez, sobre una base recién creada** con
``crear_base_validacion.ps1`` y el backend apuntando a ``rma_validacion``.
Si la base ya tiene datos (Órdenes, categorías o insumos además de
INS-001), no escribe nada y termina con un mensaje. Para volver a empezar:
recrear la base, reiniciar el backend y correrlo de nuevo.

Qué carga (detalle y casos en ``docs/VALIDACION_LOCAL.md``):

- datos de la empresa (ficticios);
- dos modelos de equipo nuevos: «iPhone 18 · Prueba local» (Apple, sin
  precios) y un Samsung (otra marca, para el error de la importación);
- categorías, subcategorías y tres fabricantes ficticios;
- once insumos clasificados con su compatibilidad, stock por «ingreso»
  (con lote donde el control lo exige) y stock mínimo en varios;
- un proveedor ficticio, una solicitud por stock mínimo y una orden de
  compra confirmada sin recibir;
- seis Tipos de reparación nuevos (cuatro con precio por modelo y huecos a
  propósito, dos de precio único), habilitados en la Mesa EST-001, con sus
  insumos necesarios;
- cuatro Órdenes de clientes ficticios en el ingreso.

También descarga la plantilla de precios y deja, FUERA del repositorio,
planillas de ejemplo para probar la importación (no la aplica).

Uso, con el backend corriendo:

    app/backend/.venv/Scripts/python supabase/scripts/validacion_local/cargar_datos_validacion.py [--api http://127.0.0.1:8000] [--salida <carpeta>]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

HOSTS_LOCALES = {"127.0.0.1", "localhost", "::1"}

# --- Datos ficticios --------------------------------------------------------

EMPRESA = {
    "nombre": "Rosario Tecno (validación local)",
    "razon_social": "Empresa Ficticia de Prueba S.A.",
    "cuit": None,
    "direccion": "Calle Ficticia 1234, Rosario (dato de prueba)",
    "telefono": "341-555-0100",
    "email": "contacto@example.com",
    "horario": "Lunes a viernes de 9 a 18 (horario de prueba)",
    "pie_comprobante": "Comprobante de PRUEBA emitido en la validación local. Sin validez.",
}

MODELO_NUEVO = {"marca": "Apple", "modelo": "iPhone 18", "variante": "Prueba local"}
MODELO_OTRA_MARCA = {"marca": "Samsung", "modelo": "Galaxy A54", "variante": None}

# (clave interna, nombre, clave interna de la categoría padre o None)
CATEGORIAS = [
    ("baterias", "Baterías", None),
    ("modulos", "Módulos", None),
    ("oled", "OLED", "modulos"),
    ("incell", "Incell", "modulos"),
    ("flex", "Flex", None),
    ("carga", "Carga", "flex"),
    ("camaras", "Cámaras", None),
    ("trasera", "Trasera", "camaras"),
    ("adhesivos", "Adhesivos y consumibles", None),
]

FABRICANTES = [
    ("voltix", "Voltix Parts (ficticio)"),
    ("nordcell", "Nordcell Repuestos (ficticio)"),
    ("delta", "Pantallas Delta (ficticio)"),
]

# Cada insumo: clave interna, código, nombre, categoría, fabricante, variante,
# código del fabricante, modelos compatibles (vacío: universal), control,
# precio, stock mínimo, ingreso (cantidad, lote) y qué caso muestra.
INSUMOS = [
    dict(k="bat11", codigo="BAT-IP11-VLX", nombre="Batería iPhone 11", cat="baterias", fab="voltix", variante="Estándar", codfab="VLX-B11", modelos=["MOD-0003"], control="SIN_LOTE", precio="18000", minimo="3", ingreso=("1", None), caso="Bajo mínimo (1 de 3). Única batería para iPhone 11: se elige sola."),
    dict(k="bat12", codigo="BAT-IP12-VLX", nombre="Batería iPhone 12 / 12 Pro", cat="baterias", fab="voltix", variante="Estándar", codfab="VLX-B12", modelos=["MOD-0006", "MOD-0008"], control="SIN_LOTE", precio="21000", minimo="2", ingreso=("4", None), caso="Suficiente (4, mínimo 2). Única para iPhone 12: se elige sola."),
    dict(k="bat14a", codigo="BAT-IP14-VLX", nombre="Batería iPhone 14", cat="baterias", fab="voltix", variante="Estándar", codfab="VLX-B14", modelos=["MOD-0014"], control="SIN_LOTE", precio="26000", minimo="2", ingreso=("1", None), caso="Bajo mínimo (1 de 2). Una de las dos baterías de iPhone 14: hay que elegir."),
    dict(k="bat14b", codigo="BAT-IP14-NRC", nombre="Batería iPhone 14", cat="baterias", fab="nordcell", variante="Alta capacidad", codfab="NRC-14HC", modelos=["MOD-0014"], control="LOTE", precio="31000", minimo=None, ingreso=("3", "NRC-B14-2611"), caso="Sin mínimo, por lote. La otra batería de iPhone 14."),
    dict(k="mod13o", codigo="MOD-IP13-OLED-DLT", nombre="Módulo iPhone 13", cat="oled", fab="delta", variante="OLED", codfab="DLT-13-OLED", modelos=["MOD-0010"], control="SIN_LOTE", precio="95000", minimo="1", ingreso=("2", None), caso="Suficiente. Uno de los dos módulos de iPhone 13: hay que elegir."),
    dict(k="mod13i", codigo="MOD-IP13-INC-NRC", nombre="Módulo iPhone 13", cat="incell", fab="nordcell", variante="Incell", codfab="NRC-13-INC", modelos=["MOD-0010"], control="SIN_LOTE", precio="62000", minimo=None, ingreso=("3", None), caso="Sin mínimo. El otro módulo de iPhone 13 (calidad Incell)."),
    dict(k="mod14o", codigo="MOD-IP14-OLED-DLT", nombre="Módulo iPhone 14", cat="oled", fab="delta", variante="OLED", codfab="DLT-14-OLED", modelos=["MOD-0014"], control="SIN_LOTE", precio="120000", minimo=None, ingreso=("1", None), caso="Único módulo de iPhone 14: se elige solo."),
    dict(k="flex12", codigo="FLX-IP12-VLX", nombre="Flex de carga iPhone 12 / 12 Pro", cat="carga", fab="voltix", variante=None, codfab="VLX-F12", modelos=["MOD-0006", "MOD-0008"], control="SIN_LOTE", precio="9000", minimo="3", ingreso=("1", None), caso="Bajo mínimo con reposición solicitada (1 de 3 + 2 pedidas)."),
    dict(k="flex14", codigo="FLX-IP14-NRC", nombre="Flex de carga iPhone 14", cat="carga", fab="nordcell", variante=None, codfab="NRC-F14", modelos=["MOD-0014"], control="SIN_LOTE", precio="11000", minimo=None, ingreso=None, caso="Sin stock, con 2 en camino (orden de compra confirmada sin recibir)."),
    dict(k="cam13", codigo="CAM-IP13-T-DLT", nombre="Cámara trasera iPhone 13", cat="trasera", fab="delta", variante="Doble lente", codfab="DLT-C13T", modelos=["MOD-0010"], control="LOTE", precio="45000", minimo=None, ingreso=("2", "DLT-C13-2611"), caso="Por lote. Única cámara de iPhone 13: se elige sola."),
    dict(k="adh", codigo="ADH-UNIV", nombre="Adhesivo de pantalla y batería", cat="adhesivos", fab=None, variante="Universal", codfab=None, modelos=[], control="LOTE", precio="1500", minimo="5", ingreso=("20", "ADH-2611-A"), caso="Universal, por lote, suficiente. Previsto concreto de batería y módulo."),
]

# Tipos de reparación: clave, nombre, precio único, puntaje, garantía (días),
# precio por modelo, multiplicador del precio base, modelos sin precio a
# propósito, filtro de líneas con precio, requisitos (categoría, cantidad) y
# previstos concretos (insumo, cantidad).
TIPOS = [
    dict(k="bateria", nombre="Cambio de batería", precio="0", puntaje=10, garantia=90, por_modelo=True, factor="1", sin_precio={"MOD-0010"}, lineas=None, requisitos=[("baterias", "1")], previstos=[("adh", "1")]),
    dict(k="modulo", nombre="Cambio de módulo", precio="0", puntaje=15, garantia=90, por_modelo=True, factor="2.5", sin_precio={"MOD-0017"}, lineas=None, requisitos=[("modulos", "1")], previstos=[("adh", "1")]),
    dict(k="flex", nombre="Cambio de flex de carga", precio="0", puntaje=12, garantia=90, por_modelo=True, factor="0.7", sin_precio=set(), lineas=None, requisitos=[("flex", "1")], previstos=[]),
    dict(k="camara", nombre="Cambio de cámara trasera", precio="0", puntaje=12, garantia=90, por_modelo=True, factor="1.4", sin_precio=set(), lineas={"iPhone 11", "iPhone 12", "iPhone 13", "iPhone 14", "iPhone 15"}, requisitos=[("camaras", "1")], previstos=[]),
    dict(k="diagnostico", nombre="Diagnóstico", precio="15000", puntaje=5, garantia=0, por_modelo=False, factor=None, sin_precio=set(), lineas=None, requisitos=[], previstos=[]),
    dict(k="limpieza", nombre="Limpieza y mantenimiento", precio="20000", puntaje=5, garantia=30, por_modelo=False, factor=None, sin_precio=set(), lineas=None, requisitos=[], previstos=[]),
]

# Precio base de un cambio de batería por línea; la variante suma o resta.
BASE_POR_LINEA = {
    "iPhone 8": 30000, "iPhone X": 36000, "iPhone Xr": 36000, "iPhone Xs": 38000,
    "iPhone SE 2020": 28000, "iPhone SE 2022": 30000,
    "iPhone 11": 42000, "iPhone 12": 48000, "iPhone 13": 55000, "iPhone 14": 62000,
    "iPhone 15": 70000, "iPhone 16": 78000, "iPhone 16e": 70000,
    "iPhone 17": 86000, "iPhone 17e": 78000,
}
AJUSTE_VARIANTE = {None: 0, "Plus": 4000, "Pro": 6000, "Pro Max": 9000, "Mini": -2000, "Max": 5000, "Air": 5000}

PROVEEDOR = {
    "nombre": "Distribuidora Ficticia de Repuestos",
    "cuit": None,
    "telefono": "341-555-0150",
    "email": "ventas@example.com",
    "contacto": "Contacto de prueba",
}

# Órdenes de ejemplo (Cliente Externo, en el ingreso).
ORDENES = [
    dict(k="A", cliente={"nombre_apellido": "Lucía Ficticia Gómez", "telefono": "341-555-0101", "email": "lucia.prueba@example.com"}, equipo={"modelo_tecnico_id": "MOD-0006", "color": "Azul", "numero_serie": "SERIE-PRUEBA-0001", "falla_reportada": "La batería dura muy poco (caso de prueba)."}, recepcion={"estado_fisico": "Rayones leves en el marco", "funcionalidades_verificadas": True}, trabajo="bateria", caso="Precio por modelo (iPhone 12) y batería elegida automáticamente."),
    dict(k="B", cliente={"nombre_apellido": "Martín Prueba Rossi", "telefono": "341-555-0102"}, equipo={"modelo_tecnico_id": "MOD-0010", "color": "Negro", "numero_serie": "SERIE-PRUEBA-0002", "falla_reportada": "Se apaga con 30 % de batería (caso de prueba)."}, recepcion={"funcionalidades_verificadas": True}, trabajo="bateria", caso="iPhone 13 sin precio de batería: «Precio pendiente de definir»; ninguna batería compatible."),
    dict(k="C", cliente={"nombre_apellido": "Carla Ejemplo Díaz", "telefono": "341-555-0103"}, equipo={"marca": "Apple", "modelo": "iPhone (modelo sin identificar)", "falla_reportada": "No carga (caso de prueba)."}, recepcion={"trabajo_solicitado": "Revisar el conector de carga; si no tiene arreglo, presupuestar.", "imei_no_disponible": True, "funcionalidades_verificadas": False, "observaciones_verificacion": "No enciende: no se pudo verificar."}, trabajo=None, caso="Sin modelo técnico, «IMEI no disponible» y trabajo solicitado en texto libre, sin trabajos."),
    dict(k="D", cliente={"nombre_apellido": "Diego Demo Fernández", "telefono": "341-555-0104"}, equipo={"modelo_tecnico_id": "MOD-0014", "color": "Blanco", "numero_serie": "SERIE-PRUEBA-0004", "falla_reportada": "Pantalla rota (caso de prueba)."}, recepcion={"estado_fisico": "Vidrio astillado", "funcionalidades_verificadas": True}, trabajo="modulo", caso="iPhone 14, cambio de módulo: precio por modelo y único módulo compatible elegido solo."),
]


# --- Cliente HTTP ------------------------------------------------------------


class ErrorApi(Exception):
    pass


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def pedir(self, metodo: str, ruta: str, cuerpo=None, *, params=None, crudo: bytes | None = None, tipo: str | None = None, binario: bool = False):
        url = self.base + ruta
        if params:
            url += "?" + urllib.parse.urlencode(params)
        datos = None
        encabezados = {}
        if crudo is not None:
            datos = crudo
            encabezados["Content-Type"] = tipo or "application/octet-stream"
        elif cuerpo is not None:
            datos = json.dumps(cuerpo).encode("utf-8")
            encabezados["Content-Type"] = "application/json"
        pedido = urllib.request.Request(url, data=datos, method=metodo, headers=encabezados)
        try:
            with urllib.request.urlopen(pedido, timeout=60) as respuesta:
                contenido = respuesta.read()
        except urllib.error.HTTPError as error:
            detalle = error.read().decode("utf-8", "replace")
            raise ErrorApi(f"{metodo} {ruta} -> {error.code}: {detalle}") from None
        except urllib.error.URLError as error:
            raise ErrorApi(f"No se pudo conectar con {self.base}: {error.reason}. ¿Está corriendo el backend?") from None
        if binario:
            return contenido
        return json.loads(contenido) if contenido else None

    def get(self, ruta, **kw):
        return self.pedir("GET", ruta, **kw)

    def post(self, ruta, cuerpo=None, **kw):
        return self.pedir("POST", ruta, cuerpo, **kw)

    def put(self, ruta, cuerpo=None, **kw):
        return self.pedir("PUT", ruta, cuerpo, **kw)


# --- Pasos -------------------------------------------------------------------


def redondear(valor: Decimal, paso: int = 500) -> Decimal:
    return (valor / paso).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * paso


def usuarios_por_rol(api: Api) -> dict[str, str]:
    usuarios = api.get("/api/catalogs/users")
    por_rol = {}
    for usuario in usuarios:
        if usuario.get("activo", True):
            por_rol.setdefault(usuario["rol"], usuario["id"])
    faltan = {"ADMINISTRADOR", "RECEPCION", "COORDINADOR_RMA", "TECNICO"} - set(por_rol)
    if faltan:
        raise ErrorApi(f"Faltan usuarios de demostración con los roles {sorted(faltan)}.")
    return por_rol


def verificar_base_nueva(api: Api, admin: str) -> None:
    estado = api.get("/api/admin/supplies")
    if not estado.get("editable"):
        raise ErrorApi("La administración no es editable: el backend no está sobre PostgreSQL (RMA_PERSISTENCIA=postgres).")
    insumos = [i["id"] for i in estado["insumos"]]
    clasificacion = api.get("/api/admin/supply-classification")
    ordenes = api.get("/api/orders", params={"usuario_id": admin})
    hay_ordenes = bool(ordenes.get("items") if isinstance(ordenes, dict) else ordenes)
    if insumos != ["INS-001"] or clasificacion["categorias"] or clasificacion["fabricantes"] or hay_ordenes:
        raise ErrorApi(
            "La base no está recién creada (ya hay insumos, categorías, fabricantes u Órdenes). "
            "No se escribió nada. Para volver a empezar: crear_base_validacion.ps1, reiniciar el backend y correr este script."
        )


def cargar_empresa(api: Api, admin: str) -> None:
    api.put("/api/admin/company", {"usuario_id": admin, **EMPRESA})


def cargar_modelos(api: Api, admin: str) -> dict[str, str]:
    nuevo = api.post("/api/admin/device-models", {"usuario_id": admin, **MODELO_NUEVO, "numeros_modelo": []})
    otra = api.post("/api/admin/device-models", {"usuario_id": admin, **MODELO_OTRA_MARCA, "numeros_modelo": []})
    return {"nuevo": nuevo["id"], "otra_marca": otra["id"], "nombre_nuevo": nuevo.get("nombre"), "nombre_otra": otra.get("nombre")}


def cargar_clasificacion(api: Api, admin: str) -> tuple[dict, dict]:
    categorias: dict[str, dict] = {}
    for clave, nombre, padre in CATEGORIAS:
        creada = api.post("/api/admin/supply-categories", {"usuario_id": admin, "nombre": nombre, "padre_id": categorias[padre]["id"] if padre else None})
        categorias[clave] = creada
    fabricantes = {}
    for clave, nombre in FABRICANTES:
        fabricantes[clave] = api.post("/api/admin/supply-manufacturers", {"usuario_id": admin, "nombre": nombre})
    return categorias, fabricantes


def cargar_insumos(api: Api, admin: str, categorias: dict, fabricantes: dict) -> dict[str, dict]:
    insumos = {}
    for dato in INSUMOS:
        cuerpo = {
            "usuario_id": admin,
            "codigo": dato["codigo"],
            "nombre": dato["nombre"],
            "unidad": "unidad",
            "control": dato["control"],
            "precio": dato["precio"],
            "stock_minimo": dato["minimo"],
            "categoria_id": categorias[dato["cat"]]["id"],
            "fabricante_id": fabricantes[dato["fab"]]["id"] if dato["fab"] else None,
            "variante": dato["variante"],
            "codigo_fabricante": dato["codfab"],
            "modelos_compatibles": dato["modelos"],
        }
        creado = api.post("/api/admin/supplies", cuerpo)
        insumos[dato["k"]] = {**dato, "id": creado["id"]}
        if dato["ingreso"]:
            cantidad, lote = dato["ingreso"]
            api.post(
                f"/api/inventory/{creado['id']}/receipts",
                {"usuario_id": admin, "cantidad": cantidad, "motivo": "Stock inicial de la validación local (dato ficticio)", "referencia": "VALIDACION-LOCAL", "lote": lote},
            )
    return insumos


def cargar_compras(api: Api, admin: str, insumos: dict) -> dict:
    proveedor = api.post("/api/admin/suppliers", {"usuario_id": admin, **PROVEEDOR})
    solicitud = api.post(
        "/api/purchases/requests",
        {"usuario_id": admin, "insumo_id": insumos["flex12"]["id"], "cantidad": "2", "motivo": "Reponer hasta el stock mínimo (dato ficticio)", "origen": "STOCK_MINIMO"},
    )
    orden = api.post(
        "/api/purchases/orders",
        {"usuario_id": admin, "proveedor_id": proveedor["id"], "items": [{"insumo_id": insumos["flex14"]["id"], "cantidad": "2", "costo_unitario": "7000"}], "observaciones": "Orden de compra de prueba (dato ficticio)"},
    )
    orden = api.post(f"/api/purchases/orders/{orden['id']}/confirm", {"usuario_id": admin})
    return {"proveedor": proveedor["id"], "solicitud": solicitud["id"], "orden_compra": orden["id"], "estado_oc": orden.get("estado")}


def precio_modelo(modelo: dict, factor: Decimal) -> Decimal | None:
    base = BASE_POR_LINEA.get(modelo["modelo"])
    if base is None or modelo.get("variante") not in AJUSTE_VARIANTE:
        return None
    return redondear(Decimal(base + AJUSTE_VARIANTE[modelo.get("variante")]) * factor)


def cargar_tipos(api: Api, admin: str, insumos: dict, categorias: dict) -> dict[str, dict]:
    modelos = [m for m in api.get("/api/admin/device-models")["modelos"] if m["marca"].lower() == "apple" and m["activo"]]
    tipos = {}
    for dato in TIPOS:
        creado = api.post(
            "/api/admin/repair-types",
            {"usuario_id": admin, "nombre": dato["nombre"], "precio": dato["precio"], "puntaje": dato["puntaje"], "garantia_dias": dato["garantia"], "precio_por_modelo": dato["por_modelo"]},
        )
        info = {**dato, "id": creado["id"], "con_precio": 0, "sin_precio": []}
        if dato["por_modelo"]:
            precios = []
            for modelo in modelos:
                precio = precio_modelo(modelo, Decimal(dato["factor"]))
                if precio is None or modelo["id"] in dato["sin_precio"] or (dato["lineas"] and modelo["modelo"] not in dato["lineas"]):
                    info["sin_precio"].append(f"{modelo['id']} {modelo['nombre']}")
                    continue
                precios.append({"modelo_equipo_id": modelo["id"], "precio": str(precio)})
            api.put(f"/api/admin/repair-types/{creado['id']}/model-prices", {"usuario_id": admin, "precios": precios})
            info["con_precio"] = len(precios)
        if dato["requisitos"] or dato["previstos"]:
            api.put(
                f"/api/admin/repair-types/{creado['id']}/supplies",
                {
                    "usuario_id": admin,
                    "insumos": [{"insumo_id": insumos[k]["id"], "cantidad": c} for k, c in dato["previstos"]],
                    "requisitos": [{"categoria_id": categorias[k]["id"], "cantidad": c} for k, c in dato["requisitos"]],
                },
            )
        tipos[dato["k"]] = info
    # Mesa EST-001: los Tipos que ya tenía más los nuevos.
    catalogo = api.get("/api/admin/catalog")
    for mesa in catalogo["mesas"]:
        if mesa["id"] == "EST-001":
            habilitados = sorted(set(mesa["tipos"]) | {t["id"] for t in tipos.values()})
            api.put("/api/admin/stations/EST-001/repair-types", {"usuario_id": admin, "tipos": habilitados})
    return tipos


def cargar_ordenes(api: Api, recepcion: str, tipos: dict) -> list[dict]:
    creadas = []
    for dato in ORDENES:
        cuerpo = {"usuario_id": recepcion, "cliente": dato["cliente"], "equipo": dato["equipo"], "recepcion": dato["recepcion"]}
        if dato["trabajo"]:
            cuerpo["trabajo_inicial"] = tipos[dato["trabajo"]]["id"]
        orden = api.post("/api/orders", cuerpo)
        creadas.append({**dato, "id": orden["id"], "estado": orden.get("estado_workflow")})
    return creadas


# --- Planillas de ejemplo para la importación de precios ---------------------


def columna_de(encabezados: list, codigo_tipo: str) -> int:
    for indice, valor in enumerate(encabezados):
        if isinstance(valor, str) and valor.strip().startswith(codigo_tipo):
            return indice
    raise ErrorApi(f"La plantilla no tiene la columna {codigo_tipo}.")


def preparar_planillas(api: Api, admin: str, salida: Path, tipos: dict, modelos: dict) -> list[dict]:
    salida.mkdir(parents=True, exist_ok=True)
    import openpyxl

    xlsx = api.get("/api/admin/model-prices/template", params={"formato": "xlsx"}, binario=True)
    csv_bytes = api.get("/api/admin/model-prices/template", params={"formato": "csv"}, binario=True)
    (salida / "plantilla_original.xlsx").write_bytes(xlsx)
    (salida / "plantilla_original.csv").write_bytes(csv_bytes)

    bateria, modulo = tipos["bateria"]["id"], tipos["modulo"]["id"]

    # .xlsx válido: dos precios NUEVO para el modelo nuevo (batería y módulo
    # del iPhone 18) y uno que CAMBIA (batería iPhone 14). La batería del
    # iPhone 13 queda sin precio a propósito (pasos B2 a B4 y C9).
    libro = openpyxl.load_workbook(io.BytesIO(xlsx))
    hoja = libro["Precios"] if "Precios" in libro.sheetnames else libro.worksheets[0]
    filas = list(hoja.iter_rows())
    encabezado_fila = next(i for i, fila in enumerate(filas) if any(c.value not in (None, "") for c in fila))
    encabezados = [c.value for c in filas[encabezado_fila]]
    col_bat, col_mod = columna_de(encabezados, bateria), columna_de(encabezados, modulo)

    def fila_de(codigo_modelo: str):
        for fila in filas[encabezado_fila + 1:]:
            valor = fila[0].value
            if isinstance(valor, str) and valor.strip().startswith(codigo_modelo):
                return fila
        raise ErrorApi(f"La plantilla no tiene la fila {codigo_modelo}.")

    fila_de(modelos["nuevo"])[col_bat].value = 98000
    fila_de("MOD-0014")[col_bat].value = 66000
    fila_de(modelos["nuevo"])[col_mod].value = 230000
    valido = io.BytesIO()
    libro.save(valido)
    (salida / "precios_ejemplo_valido.xlsx").write_bytes(valido.getvalue())

    # CSV con errores a propósito: «80,000» (ambiguo), una columna «TR001»
    # (se ignora) y una fila de otra marca. Además, un cambio válido.
    texto = csv_bytes.decode("utf-8-sig")
    lector = list(csv.reader(io.StringIO(texto), delimiter=";"))
    encabezado_csv = next(i for i, fila in enumerate(lector) if any(c.strip() for c in fila))
    cabecera = lector[encabezado_csv]
    col_bat_csv = columna_de(cabecera, bateria)
    cabecera.append("TR001 · columna mal escrita")
    for fila in lector[encabezado_csv + 1:]:
        if not fila:
            continue
        fila.extend([""] * (len(cabecera) - 1 - len(fila)))
        fila.append("")
        if fila[0].startswith("MOD-0003"):
            fila[col_bat_csv] = "80,000"
        if fila[0].startswith("MOD-0006"):
            fila[col_bat_csv] = "50.500"
    otra = [""] * len(cabecera)
    otra[0] = f"{modelos['otra_marca']} · {modelos['nombre_otra']}"
    otra[col_bat_csv] = "40000"
    lector.append(otra)
    destino = io.StringIO()
    csv.writer(destino, delimiter=";", lineterminator="\r\n").writerows(lector)
    errores_bytes = ("﻿" + destino.getvalue()).encode("utf-8")
    (salida / "precios_ejemplo_con_errores.csv").write_bytes(errores_bytes)

    resultados = []
    for nombre, contenido, tipo in (
        ("plantilla_original.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("plantilla_original.csv", csv_bytes, "text/csv"),
        ("precios_ejemplo_valido.xlsx", valido.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("precios_ejemplo_con_errores.csv", errores_bytes, "text/csv"),
    ):
        vista = api.post("/api/admin/model-prices/import/preview", params={"usuario_id": admin, "nombre": nombre}, crudo=contenido, tipo=tipo)
        resultados.append({"archivo": nombre, "resumen": vista["resumen"], "aplicable": vista["aplicable"], "editable": vista.get("editable"), "columnas_ignoradas": len(vista["columnas_ignoradas"])})
    return resultados


# --- Principal ---------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Carga datos ficticios de validación por la API.")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="URL del backend local.")
    parser.add_argument(
        "--salida",
        default=str(Path(os.environ.get("USERPROFILE") or Path.home()) / "rma-validacion-data" / "planillas"),
        help="Carpeta (fuera del repositorio) para las planillas de ejemplo.",
    )
    args = parser.parse_args()

    host = urllib.parse.urlsplit(args.api).hostname
    if host not in HOSTS_LOCALES:
        print(f"Rechazado: solo un backend local (127.0.0.1 o localhost), no «{host}».", file=sys.stderr)
        return 2

    api = Api(args.api)
    try:
        roles = usuarios_por_rol(api)
        admin, recepcion = roles["ADMINISTRADOR"], roles["RECEPCION"]
        verificar_base_nueva(api, admin)

        print("Cargando datos ficticios en", args.api)
        cargar_empresa(api, admin)
        print("  empresa: lista")
        modelos = cargar_modelos(api, admin)
        print(f"  modelos: {modelos['nuevo']} {modelos['nombre_nuevo']} y {modelos['otra_marca']} {modelos['nombre_otra']}")
        categorias, fabricantes = cargar_clasificacion(api, admin)
        print(f"  categorías: {len(categorias)}; fabricantes: {len(fabricantes)}")
        insumos = cargar_insumos(api, admin, categorias, fabricantes)
        print(f"  insumos: {len(insumos)} con su stock")
        compras = cargar_compras(api, admin, insumos)
        print(f"  compras: proveedor {compras['proveedor']}, solicitud {compras['solicitud']}, orden de compra {compras['orden_compra']} ({compras['estado_oc']})")
        tipos = cargar_tipos(api, admin, insumos, categorias)
        print(f"  tipos de reparación: {', '.join(t['id'] for t in tipos.values())}, habilitados en EST-001")
        ordenes = cargar_ordenes(api, recepcion, tipos)
        print(f"  órdenes: {', '.join(o['id'] for o in ordenes)}")
        planillas = preparar_planillas(api, admin, Path(args.salida), tipos, modelos)
        print(f"  planillas de ejemplo en {args.salida}")
    except ErrorApi as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    # --- Resumen ---
    print("\n=== Resumen de lo cargado (todo ficticio) ===")
    print("\nCategorías:")
    for clave, nombre, padre in CATEGORIAS:
        padre_txt = f" (sub de {categorias[padre]['id']})" if padre else ""
        print(f"  {categorias[clave]['id']}  {nombre}{padre_txt}")
    print("\nFabricantes:")
    for clave, nombre in FABRICANTES:
        print(f"  {fabricantes[clave]['id']}  {nombre}")
    print("\nInsumos (situación en Inventario):")
    situacion = {s["id"]: s for s in api.get("/api/inventory")}
    for dato in insumos.values():
        s = situacion[dato["id"]]
        print(f"  {dato['id']}  {dato['codigo']:<18} {dato['nombre']} · {dato['variante'] or '-'}  disp {s['disponible']}  mín {s['stock_minimo'] or '-'}  en camino {s['en_camino']}  {s['estado_reposicion']}")
    print("\nTipos de reparación:")
    for dato in tipos.values():
        if dato["por_modelo"]:
            print(f"  {dato['id']}  {dato['nombre']} (precio por modelo: {dato['con_precio']} modelos con precio; sin precio: {len(dato['sin_precio'])})")
            for faltante in dato["sin_precio"][:6]:
                print(f"        sin precio: {faltante}")
            if len(dato["sin_precio"]) > 6:
                print(f"        ... y {len(dato['sin_precio']) - 6} más")
        else:
            print(f"  {dato['id']}  {dato['nombre']} (precio único ${dato['precio']})")
    print("\nCompras:", compras)
    print("\nÓrdenes (Cliente Externo, en el ingreso, creadas por Recepción):")
    for orden in ordenes:
        print(f"  {orden['id']}  {orden['cliente']['nombre_apellido']} · {orden['caso']}")
    print("\nVista previa de las planillas (no se aplicó ninguna):")
    for resultado in planillas:
        print(f"  {resultado['archivo']}: {resultado['resumen']} aplicable={resultado['aplicable']} columnas ignoradas={resultado['columnas_ignoradas']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
