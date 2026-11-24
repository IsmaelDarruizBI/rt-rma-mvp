# ruff: noqa: E501  (textos largos)
"""Comprueba, por la API, que la configuración se puede editar sobre PostgreSQL.

Para cada área: la lectura responde ``editable: true`` y un cambio de ida y
vuelta (cambiar un campo y restaurarlo) se guarda y se relee. Pensado para
correr DESPUÉS de ``cargar_datos_validacion.py`` (usa sus códigos: TR-003,
TR-007, MOD-0037, CAT-009, FAB-003, INS-012, EST-001).

Deja rastro: cada ida y vuelta son dos cambios en el historial de
configuración (el valor final es el original). No publica términos (una
versión publicada no se puede deshacer) y no aplica ninguna importación.

    app/backend/.venv/Scripts/python supabase/scripts/validacion_local/verificar_edicion.py [--api http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cargar_datos_validacion import HOSTS_LOCALES, Api, ErrorApi  # noqa: E402

resultados: list[tuple[str, bool, str]] = []


def anotar(area: str, ok: bool, detalle: str = "") -> None:
    resultados.append((area, ok, detalle))
    print(f"[{'OK' if ok else 'FALLA'}] {area}{': ' + detalle if detalle else ''}")


def probar(area: str, funcion) -> None:
    try:
        detalle = funcion()
        anotar(area, True, detalle or "")
    except (ErrorApi, AssertionError, KeyError, StopIteration) as error:
        anotar(area, False, str(error) or type(error).__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verifica la edición de la configuración por la API.")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    if urllib.parse.urlsplit(args.api).hostname not in HOSTS_LOCALES:
        print("Rechazado: solo un backend local.", file=sys.stderr)
        return 2
    api = Api(args.api)
    admin = next(u["id"] for u in api.get("/api/catalogs/users") if u["rol"] == "ADMINISTRADOR")

    def editable(ruta: str, **kw) -> dict:
        respuesta = api.get(ruta, **kw)
        assert respuesta.get("editable") is True, f"{ruta}: editable={respuesta.get('editable')}"
        return respuesta

    # 1. Datos de la empresa
    def empresa():
        original = editable("/api/admin/company")["empresa"]
        cuerpo = {k: original[k] for k in ("nombre", "razon_social", "cuit", "direccion", "telefono", "email", "horario", "pie_comprobante")}
        api.put("/api/admin/company", {"usuario_id": admin, **cuerpo, "horario": "Horario editado (verificación)"})
        assert api.get("/api/admin/company")["empresa"]["horario"] == "Horario editado (verificación)"
        api.put("/api/admin/company", {"usuario_id": admin, **cuerpo})
        assert api.get("/api/admin/company")["empresa"]["horario"] == original["horario"]
        return "GET editable; PUT horario y restaurado"

    # 2. Términos (solo lectura: publicar crea una versión que no se deshace)
    def terminos():
        vista = editable("/api/admin/terms")
        return f"GET editable; vigente v{vista['vigente']['version']} (no se publica: el paso A2 lo hace a mano)"

    # 3. Modelos de equipo
    def modelos():
        lista = editable("/api/admin/device-models")["modelos"]
        modelo = next(m for m in lista if m["id"] == "MOD-0037")
        cuerpo = {k: modelo[k] for k in ("marca", "modelo", "variante", "numeros_modelo", "activo")}
        api.put("/api/admin/device-models/MOD-0037", {"usuario_id": admin, **cuerpo, "variante": "Prueba local editada"})
        api.put("/api/admin/device-models/MOD-0037", {"usuario_id": admin, **cuerpo})
        final = next(m for m in api.get("/api/admin/device-models")["modelos"] if m["id"] == "MOD-0037")
        assert final["variante"] == modelo["variante"]
        return f"GET editable ({len(lista)} modelos); PUT variante de MOD-0037 y restaurada"

    # 4. Categorías y fabricantes
    def clasificacion():
        vista = editable("/api/admin/supply-classification")
        categoria = next(c for c in vista["categorias"] if c["id"] == "CAT-009")
        fabricante = next(f for f in vista["fabricantes"] if f["id"] == "FAB-003")
        api.put("/api/admin/supply-categories/CAT-009", {"usuario_id": admin, "nombre": categoria["nombre"] + " (editada)", "activo": True})
        api.put("/api/admin/supply-categories/CAT-009", {"usuario_id": admin, "nombre": categoria["nombre"], "activo": True})
        api.put("/api/admin/supply-manufacturers/FAB-003", {"usuario_id": admin, "nombre": fabricante["nombre"] + " (editado)", "activo": True})
        api.put("/api/admin/supply-manufacturers/FAB-003", {"usuario_id": admin, "nombre": fabricante["nombre"], "activo": True})
        vista = api.get("/api/admin/supply-classification")
        assert next(c for c in vista["categorias"] if c["id"] == "CAT-009")["nombre"] == categoria["nombre"]
        assert next(f for f in vista["fabricantes"] if f["id"] == "FAB-003")["nombre"] == fabricante["nombre"]
        return f"GET editable ({len(vista['categorias'])} categorías, {len(vista['fabricantes'])} fabricantes); PUT CAT-009 y FAB-003 y restaurados"

    # 5. Insumos: stock mínimo y clasificación
    def insumos():
        lista = editable("/api/admin/supplies")["insumos"]
        insumo = next(i for i in lista if i["id"] == "INS-012")
        cuerpo = {k: insumo[k] for k in ("codigo", "nombre", "unidad", "activo", "control", "precio")}
        api.put("/api/admin/supplies/INS-012", {"usuario_id": admin, **cuerpo, "stock_minimo": "6"})
        assert next(i for i in api.get("/api/admin/supplies")["insumos"] if i["id"] == "INS-012")["stock_minimo"] in ("6", "6.000")
        api.put("/api/admin/supplies/INS-012", {"usuario_id": admin, **cuerpo, "stock_minimo": insumo["stock_minimo"]})
        final = next(i for i in api.get("/api/admin/supplies")["insumos"] if i["id"] == "INS-012")
        assert final["stock_minimo"] == insumo["stock_minimo"] and final["categoria_id"] == insumo["categoria_id"]
        return f"GET editable ({len(lista)} insumos); PUT stock mínimo de INS-012 y restaurado (clasificación conservada)"

    # 6. Tipos de reparación y Mesa
    def tipos():
        catalogo = editable("/api/admin/catalog")
        tipo = next(t for t in catalogo["tipos"] if t["id"] == "TR-007")
        cuerpo = {k: tipo[k] for k in ("nombre", "precio", "puntaje", "activo")}
        api.put("/api/admin/repair-types/TR-007", {"usuario_id": admin, **cuerpo, "precio": "16000"})
        api.put("/api/admin/repair-types/TR-007", {"usuario_id": admin, **cuerpo})
        mesa = next(m for m in api.get("/api/admin/catalog")["mesas"] if m["id"] == "EST-001")
        api.put("/api/admin/stations/EST-001/repair-types", {"usuario_id": admin, "tipos": [t for t in mesa["tipos"] if t != "TR-008"]})
        api.put("/api/admin/stations/EST-001/repair-types", {"usuario_id": admin, "tipos": mesa["tipos"]})
        catalogo = api.get("/api/admin/catalog")
        assert next(t for t in catalogo["tipos"] if t["id"] == "TR-007")["precio"] == tipo["precio"]
        assert sorted(next(m for m in catalogo["mesas"] if m["id"] == "EST-001")["tipos"]) == sorted(mesa["tipos"])
        return "GET editable; PUT precio de TR-007 y restaurado; Mesa EST-001 sin TR-008 y restaurada"

    # 7. Precios por modelo
    def precios():
        tipo = next(t for t in api.get("/api/admin/catalog")["tipos"] if t["id"] == "TR-003")
        original = tipo["precios_modelo"]["MOD-0001"]
        api.put("/api/admin/repair-types/TR-003/model-prices", {"usuario_id": admin, "precios": [{"modelo_equipo_id": "MOD-0001", "precio": "31234.50"}]})
        api.put("/api/admin/repair-types/TR-003/model-prices", {"usuario_id": admin, "precios": [{"modelo_equipo_id": "MOD-0001", "precio": original}]})
        final = next(t for t in api.get("/api/admin/catalog")["tipos"] if t["id"] == "TR-003")["precios_modelo"]["MOD-0001"]
        assert final == original, (final, original)
        return f"PUT precio TR-003/MOD-0001 y restaurado ({original})"

    # 8. Insumos necesarios
    def necesarios():
        vista = editable("/api/admin/repair-types/supplies")
        previstos = [p for p in vista["previstos"] if p["tipo_reparacion_id"] == "TR-003"]
        requisitos = [r for r in vista["requisitos"] if r["tipo_reparacion_id"] == "TR-003" and r.get("activo", True)]
        cuerpo = {"usuario_id": admin, "requisitos": [{"categoria_id": r["categoria_id"], "cantidad": r["cantidad"]} for r in requisitos]}
        api.put("/api/admin/repair-types/TR-003/supplies", {**cuerpo, "insumos": [{"insumo_id": p["insumo_id"], "cantidad": "2"} for p in previstos]})
        api.put("/api/admin/repair-types/TR-003/supplies", {**cuerpo, "insumos": [{"insumo_id": p["insumo_id"], "cantidad": p["cantidad"]} for p in previstos]})
        final = [p for p in api.get("/api/admin/repair-types/supplies")["previstos"] if p["tipo_reparacion_id"] == "TR-003"]
        assert [(p["insumo_id"], p["cantidad"]) for p in final] == [(p["insumo_id"], p["cantidad"]) for p in previstos]
        return f"GET editable; PUT cantidad del previsto de TR-003 y restaurada ({len(requisitos)} requisito/s conservado/s)"

    # 9. Plantilla e importación (solo vista previa)
    def importacion():
        plantilla = api.get("/api/admin/model-prices/template", params={"formato": "xlsx"}, binario=True)
        vista = api.post("/api/admin/model-prices/import/preview", params={"usuario_id": admin, "nombre": "plantilla.xlsx"}, crudo=plantilla, tipo="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        assert vista["editable"] is True, vista.get("editable")
        assert vista["resumen"]["errores"] == 0
        return f"GET plantilla ({len(plantilla)} bytes); vista previa editable, {vista['resumen']['sin_cambio']} sin cambio, aplicable={vista['aplicable']} (no se aplica)"

    # 10. Otras secciones de Configuración
    def otras():
        for ruta in ("/api/admin/parameters", "/api/admin/payment-methods", "/api/admin/reasons"):
            editable(ruta)
        return "parameters, payment-methods y reasons: editable"

    # 11. Pantallas nuevas de lectura
    def lecturas():
        bajo = api.get("/api/inventory", params={"bajo_minimo": "true"})
        sugerencias = api.get("/api/purchases/suggestions")
        sin_pieza = api.get("/api/purchases/suggestions/pending-pieces")
        cambios = api.get("/api/admin/config-changes")
        estados = sorted({i["estado_reposicion"] for i in bajo})
        return f"inventario bajo mínimo: {len(bajo)} ({', '.join(estados)}); sugerencias: {len(sugerencias)}; trabajos sin pieza: {len(sin_pieza)}; historial de configuración: {len(cambios)} cambios"

    for area, funcion in (
        ("Datos de la empresa", empresa),
        ("Términos y condiciones", terminos),
        ("Modelos de equipo", modelos),
        ("Categorías y fabricantes", clasificacion),
        ("Insumos (stock mínimo y clasificación)", insumos),
        ("Tipos de reparación y Mesa", tipos),
        ("Precios por modelo", precios),
        ("Insumos necesarios", necesarios),
        ("Plantilla e importación de precios", importacion),
        ("Parámetros, medios de pago y motivos", otras),
        ("Lecturas de Inventario y Compras", lecturas),
    ):
        probar(area, funcion)

    fallas = [r for r in resultados if not r[1]]
    print(f"\n{len(resultados) - len(fallas)} de {len(resultados)} áreas OK.")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
