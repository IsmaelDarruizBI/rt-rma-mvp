# ruff: noqa: E501  (tabla)
"""Configuracion v2, CFG-02: matriz de permisos de TODAS las rutas.

Cada ruta de la API esta clasificada aca. Una ruta nueva (o quitada) sin
clasificar hace fallar la prueba: es el control permanente de la auditoria
de permisos (docs/configuracion-discovery.md, seccion 8).

Clasificacion:

* ``API(...)``: ``exigir_rol`` corta en la API (403 con sesion real) con
  ALGUNO de esos permisos; el caso de uso vuelve a validar.
* ``SERVICIO(...)``: un comando que valida su permiso en el caso de uso
  (depende del estado de la Orden o exige varios permisos); con sesion
  real responde 409 si el rol no lo tiene.
* ``EN_LA_RUTA``: el permiso depende de un parametro (la auditoria de una
  entidad la ve quien la administra; la completa, Administracion).
* ``SESION``: lectura de catalogos para los selectores o la sesion: basta
  con estar autenticado.
* ``SISTEMA``: eventos de sistema sin usuario (analisis aparte, brecha 11).
* ``PUBLICA``: sin sesion (``/health``).

La prueba con sesion real de cada ruta ``API`` esta en
``tests/postgres/test_permisos_operativos_postgres.py``.
"""

import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from app.core.config import Settings
from app.main import create_app
from app.services import permisos
from app.services.permisos import Permiso


class API(tuple):
    def __new__(cls, *codigos):
        return super().__new__(cls, codigos)


class SERVICIO(tuple):
    def __new__(cls, *codigos):
        return super().__new__(cls, codigos)


SESION = "SESION"
SISTEMA = "SISTEMA"
PUBLICA = "PUBLICA"
EN_LA_RUTA = "EN_LA_RUTA"

MATRIZ = {
    ("GET", "/health"): PUBLICA,
    ("GET", "/api/me"): SESION,
    ("GET", "/api/catalogs/repair-types"): SESION,
    ("GET", "/api/catalogs/stations"): SESION,
    ("GET", "/api/catalogs/users"): SESION,
    ("GET", "/api/catalogs/priorities"): SESION,
    ("GET", "/api/catalogs/payment-methods"): SESION,
    ("GET", "/api/catalogs/reasons"): SESION,
    ("GET", "/api/catalogs/checklist"): SESION,
    ("GET", "/api/catalogs/equipment"): SESION,
    ("POST", "/api/catalogs/equipment/sync"): API(
        "CATALOGO_EQUIPOS_SINCRONIZAR"
    ),
    ("GET", "/api/catalogs/device-models"): SESION,
    ("GET", "/api/clients/lookup"): API("CLIENTE_BUSCAR"),
    ("GET", "/api/orders"): API("ORDENES_CONSULTAR"),
    ("GET", "/api/orders/authorizations/pending"): API("ORDENES_CONSULTAR"),
    ("GET", "/api/orders/{orden_id}"): API("ORDENES_CONSULTAR"),
    ("GET", "/api/orders/{orden_id}/finances"): API("ORDENES_CONSULTAR"),
    ("GET", "/api/orders/{orden_id}/custody"): API("ORDENES_CONSULTAR"),
    ("GET", "/api/orders/{orden_id}/documents"): API("ORDENES_CONSULTAR"),
    ("GET", "/api/orders/{orden_id}/documents/preview/{tipo}"): API(
        "ORDENES_CONSULTAR"
    ),
    ("GET", "/api/orders/{orden_id}/documents/{documento_id}/pdf"): API(
        "ORDENES_CONSULTAR"
    ),
    ("GET", "/api/orders/{orden_id}/documents/{documento_id}"): API(
        "ORDENES_CONSULTAR"
    ),
    ("GET", "/api/orders/{orden_id}/authorizations"): API("ORDENES_CONSULTAR"),
    (
        "GET",
        "/api/orders/{orden_id}/details/{detalle_id}/resources/override-preview",
    ): API("ORDENES_CONSULTAR"),
    ("POST", "/api/orders"): SERVICIO("ORDEN_CREAR"),
    ("POST", "/api/orders/rt-interno"): SERVICIO("ORDEN_CREAR"),
    ("POST", "/api/orders/{orden_id}/details"): SERVICIO(
        "DETALLE_DEFINIR_RECEPCION", "DETALLE_DEFINIR_TECNICO"
    ),
    ("POST", "/api/orders/{orden_id}/definition/finalize"): SERVICIO(
        "DETALLE_DEFINIR_RECEPCION", "DETALLE_DEFINIR_TECNICO"
    ),
    ("POST", "/api/orders/{orden_origen_id}/warranty-rma"): SERVICIO(
        "GARANTIA_RMA_CREAR", "GARANTIA_EXCEPCION"
    ),
    ("POST", "/api/orders/{orden_id}/send-to-review"): SERVICIO(
        "ENVIAR_A_REVISION"
    ),
    ("POST", "/api/orders/{orden_id}/technical-review"): SERVICIO(
        "REVISION_TECNICA"
    ),
    ("POST", "/api/orders/{orden_id}/review/details"): SERVICIO(
        "DETALLE_DEFINIR_TECNICO"
    ),
    ("POST", "/api/orders/{orden_id}/review/without-repair"): SERVICIO(
        "ENVIAR_A_REVISION"
    ),
    (
        "POST",
        "/api/orders/{orden_id}/details/{detalle_id}/resources/override",
    ): SERVICIO("RECURSOS_OVERRIDE"),
    ("POST", "/api/orders/{orden_id}/resources/wait"): SISTEMA,
    ("POST", "/api/orders/{orden_id}/resources/revalidate"): SISTEMA,
    ("POST", "/api/orders/{orden_id}/queue"): SERVICIO("PRIORIDAD_DEFINIR"),
    ("POST", "/api/orders/{orden_id}/take"): SERVICIO("ORDEN_TOMAR"),
    (
        "POST",
        "/api/orders/{orden_id}/details/{detalle_id}/evaluation",
    ): SERVICIO("EVALUACION_TECNICA"),
    ("POST", "/api/orders/{orden_id}/details/additional"): SERVICIO(
        "DETALLE_ADICIONAL"
    ),
    ("POST", "/api/orders/{orden_id}/details/{detalle_id}/start"): SERVICIO(
        "ORDEN_TOMAR"
    ),
    (
        "POST",
        "/api/orders/{orden_id}/executions/{ejecucion_id}/complete",
    ): SERVICIO("EJECUCION"),
    (
        "POST",
        "/api/orders/{orden_id}/executions/{ejecucion_id}/interrupt",
    ): SERVICIO("EJECUCION"),
    (
        "POST",
        "/api/orders/{orden_id}/executions/{ejecucion_id}/requires-redefinition",
    ): SERVICIO("EJECUCION"),
    (
        "POST",
        "/api/orders/{orden_id}/details/{detalle_id}/technical-review",
    ): SERVICIO("DETALLE_DEFINIR_TECNICO"),
    ("POST", "/api/orders/{orden_id}/details/{detalle_id}/redefine"): SERVICIO(
        "DETALLE_DEFINIR_TECNICO"
    ),
    ("POST", "/api/orders/{orden_id}/control/approve"): SERVICIO(
        "CONTROL_TECNICO"
    ),
    ("POST", "/api/orders/{orden_id}/control/reject"): SERVICIO(
        "CONTROL_TECNICO"
    ),
    ("POST", "/api/orders/{orden_id}/details/{detalle_id}/cancel"): SERVICIO(
        "CANCELACION"
    ),
    ("POST", "/api/orders/{orden_id}/cancel"): SERVICIO("CANCELACION"),
    ("POST", "/api/orders/{orden_id}/authorizations"): SERVICIO(
        "DECISION_CLIENTE"
    ),
    ("POST", "/api/orders/{orden_id}/withdrawal"): SERVICIO(
        "DECISION_CLIENTE"
    ),
    (
        "POST",
        "/api/orders/{orden_id}/details/{detalle_id}/withdrawal",
    ): SERVICIO("DECISION_CLIENTE"),
    ("POST", "/api/orders/{orden_id}/return-equipment"): SERVICIO("ENTREGA"),
    ("PUT", "/api/orders/{orden_id}/reception"): SERVICIO(
        "CUSTODIA", "INGRESO_CORREGIR"
    ),
    ("POST", "/api/orders/{orden_id}/reception/confirm"): SERVICIO("CUSTODIA"),
    ("POST", "/api/orders/{orden_id}/reception/not-received"): SERVICIO(
        "CUSTODIA"
    ),
    ("POST", "/api/orders/{orden_id}/reception/notes"): SERVICIO("CUSTODIA"),
    ("POST", "/api/orders/{orden_id}/documents/reception-receipt"): SERVICIO(
        "CUSTODIA"
    ),
    ("POST", "/api/orders/{orden_id}/documents/intake-receipt"): SERVICIO(
        "DETALLE_DEFINIR_RECEPCION"
    ),
    (
        "POST",
        "/api/orders/{orden_id}/documents/authorization-receipt",
    ): SERVICIO("COMPROBANTE_AUTORIZACION"),
    ("POST", "/api/orders/{orden_id}/release"): SERVICIO(
        "ORDEN_TOMAR", "LIBERACION_AJENA"
    ),
    ("POST", "/api/orders/{orden_id}/priority"): SERVICIO("PRIORIDAD_CAMBIAR"),
    ("POST", "/api/orders/{orden_id}/discount"): SERVICIO(
        "DESCUENTO", "CORTESIA"
    ),
    ("POST", "/api/orders/{orden_id}/details/{detalle_id}/warranty"): SERVICIO(
        "GARANTIA_AJUSTAR"
    ),
    ("POST", "/api/orders/{orden_id}/notify"): SERVICIO("CLIENTE_NOTIFICAR"),
    ("POST", "/api/orders/{orden_id}/payments"): SERVICIO("PAGO_REGISTRAR"),
    ("POST", "/api/orders/{orden_id}/payments/{pago_id}/void"): SERVICIO(
        "PAGO_ANULAR"
    ),
    ("POST", "/api/orders/{orden_id}/refunds"): SERVICIO("DEVOLUCION_DINERO"),
    ("POST", "/api/orders/{orden_id}/photos"): API("FOTOS_CARGAR"),
    ("GET", "/api/orders/{orden_id}/photos/{foto_id}"): API(
        "ORDENES_CONSULTAR"
    ),
    ("POST", "/api/orders/{orden_id}/checkin"): SERVICIO("CHECKIN"),
    ("POST", "/api/orders/{orden_id}/deliver"): SERVICIO("ENTREGA"),
    ("POST", "/api/orders/{orden_id}/inform-rt"): SISTEMA,
    ("POST", "/api/orders/{orden_id}/return-rt"): SERVICIO("ENTREGA"),
    ("POST", "/api/orders/{orden_id}/pickup-followups"): SERVICIO(
        "RETIRO_SEGUIMIENTO"
    ),
    (
        "POST",
        "/api/orders/{orden_id}/consumptions/{consumo_id}/return",
    ): SERVICIO("DEVOLUCION_STOCK"),
    ("POST", "/api/orders/{orden_id}/checklist"): SERVICIO(
        "CHECKLIST_REGISTRAR"
    ),
    ("POST", "/api/orders/{orden_id}/missing-info-ack"): SERVICIO(
        "CHECKLIST_REGISTRAR"
    ),
    ("GET", "/api/inventory"): API("INVENTARIO_CONSULTAR"),
    ("GET", "/api/inventory/movements"): API("INVENTARIO_CONSULTAR"),
    ("POST", "/api/inventory/revalidate-orders"): API("RECURSOS_REVALIDAR"),
    ("GET", "/api/inventory/{insumo_id}"): API("INVENTARIO_CONSULTAR"),
    ("POST", "/api/inventory/{insumo_id}/receipts"): API("STOCK_GESTIONAR"),
    ("POST", "/api/inventory/{insumo_id}/adjustments"): API("STOCK_GESTIONAR"),
    ("GET", "/api/inventory/{insumo_id}/lots"): API("INVENTARIO_CONSULTAR"),
    ("GET", "/api/work/inbox"): API("ORDENES_CONSULTAR"),
    ("GET", "/api/work/workshop"): API("ORDENES_CONSULTAR"),
    ("POST", "/api/maintenance/photos/cleanup"): API("FOTOS_ADMINISTRAR"),
    ("GET", "/api/equipment/history"): API("ANTECEDENTES_CONSULTAR"),
    ("GET", "/api/reports/operational"): API("REPORTES_CONSULTAR"),
    ("GET", "/api/admin/catalog"): API(
        "TIPO_REPARACION_GESTIONAR",
        "MESA_TIPOS_GESTIONAR",
    ),
    ("POST", "/api/admin/repair-types"): API("TIPO_REPARACION_GESTIONAR"),
    ("PUT", "/api/admin/repair-types/{codigo}"): API(
        "TIPO_REPARACION_GESTIONAR"
    ),
    ("PUT", "/api/admin/stations/{codigo}/repair-types"): API(
        "MESA_TIPOS_GESTIONAR"
    ),
    ("GET", "/api/admin/config-changes"): EN_LA_RUTA,
    ("GET", "/api/admin/users"): API("ROLES_ADMINISTRAR"),
    ("PUT", "/api/admin/users/{codigo}/roles"): API("ROLES_ADMINISTRAR"),
    ("GET", "/api/admin/permissions"): API("ROLES_ADMINISTRAR"),
    ("PUT", "/api/admin/permissions/{codigo}"): API("ROLES_ADMINISTRAR"),
    ("GET", "/api/admin/reasons"): API("MOTIVO_GESTIONAR"),
    ("POST", "/api/admin/reasons"): API("MOTIVO_GESTIONAR"),
    ("PUT", "/api/admin/reasons/{codigo}"): API("MOTIVO_GESTIONAR"),
    ("GET", "/api/admin/parameters"): API("CONFIGURACION_ADMINISTRAR"),
    ("PUT", "/api/admin/parameters/{clave}"): API("CONFIGURACION_ADMINISTRAR"),
    ("GET", "/api/admin/payment-methods"): API("CONFIGURACION_ADMINISTRAR"),
    ("PUT", "/api/admin/payment-methods/{codigo}"): API(
        "CONFIGURACION_ADMINISTRAR"
    ),
    ("GET", "/api/admin/supplies"): API("INSUMO_GESTIONAR"),
    ("POST", "/api/admin/supplies"): API("INSUMO_GESTIONAR"),
    ("PUT", "/api/admin/supplies/{clave}"): API("INSUMO_GESTIONAR"),
    ("GET", "/api/admin/checklist"): API("CHECKLIST_GESTIONAR"),
    ("POST", "/api/admin/equipment-types/sync"): API("CHECKLIST_GESTIONAR"),
    ("POST", "/api/admin/checklist-questions"): API("CHECKLIST_GESTIONAR"),
    ("PUT", "/api/admin/checklist-questions/{codigo}"): API(
        "CHECKLIST_GESTIONAR"
    ),
    ("GET", "/api/warranty-claims"): API("RECLAMOS_CONSULTAR"),
    ("GET", "/api/warranty-claims/{codigo}"): API("RECLAMOS_CONSULTAR"),
    ("POST", "/api/warranty-claims/{codigo}/continue"): SERVICIO(
        "RECLAMO_CONTINUAR"
    ),
    ("GET", "/api/communications/templates"): SESION,
    ("GET", "/api/orders/{orden_id}/messages/prepare"): API(
        "ORDENES_CONSULTAR"
    ),
    ("POST", "/api/orders/{orden_id}/messages"): SERVICIO(
        "COMUNICACION_ENVIAR"
    ),
    (
        "POST",
        "/api/orders/{orden_id}/messages/{comunicacion_id}/confirm",
    ): SERVICIO("COMUNICACION_ENVIAR"),
    ("GET", "/api/clients/{cliente_id}/consents"): API("ORDENES_CONSULTAR"),
    ("POST", "/api/clients/{cliente_id}/consents"): SERVICIO(
        "CONSENTIMIENTO_REGISTRAR"
    ),
    ("GET", "/api/admin/message-templates"): API("PLANTILLA_GESTIONAR"),
    ("POST", "/api/admin/message-templates"): API("PLANTILLA_GESTIONAR"),
    ("PUT", "/api/admin/message-templates/{codigo}"): API(
        "PLANTILLA_GESTIONAR"
    ),
    ("GET", "/api/orders/{orden_id}/signatures"): API("ORDENES_CONSULTAR"),
    (
        "POST",
        "/api/orders/{orden_id}/documents/{documento_id}/signatures",
    ): SERVICIO("FIRMA_REGISTRAR"),
    ("GET", "/api/orders/{orden_id}/signatures/{firma_id}"): API(
        "ORDENES_CONSULTAR"
    ),
    ("GET", "/api/equipment/identify"): API("ANTECEDENTES_CONSULTAR"),
    ("GET", "/api/equipment/{equipo_id}/orders"): API(
        "ANTECEDENTES_CONSULTAR"
    ),
    ("POST", "/api/orders/{orden_id}/equipment-link"): SERVICIO(
        "EQUIPO_VINCULO_CORREGIR"
    ),
    ("GET", "/api/purchases/status"): SESION,
    ("GET", "/api/purchases/suppliers"): API("COMPRAS_CONSULTAR"),
    ("GET", "/api/purchases/requests"): API("COMPRAS_CONSULTAR"),
    ("POST", "/api/purchases/requests"): API("COMPRA_SOLICITAR"),
    ("POST", "/api/purchases/requests/{solicitud_id}/discard"): API(
        "COMPRA_SOLICITAR"
    ),
    ("GET", "/api/purchases/suggestions"): API("COMPRAS_CONSULTAR"),
    ("GET", "/api/purchases/orders"): API("COMPRAS_CONSULTAR"),
    ("GET", "/api/purchases/orders/{orden_id}"): API("COMPRAS_CONSULTAR"),
    ("POST", "/api/purchases/orders"): API("OC_CREAR"),
    ("POST", "/api/purchases/orders/{orden_id}/confirm"): API("OC_CONFIRMAR"),
    ("POST", "/api/purchases/orders/{orden_id}/cancel"): API(
        "OC_CANCELAR", "OC_CREAR"
    ),
    ("POST", "/api/purchases/orders/{compra_id}/receipts"): API(
        "COMPRA_RECIBIR"
    ),
    ("GET", "/api/purchases/costs"): API("COMPRAS_CONSULTAR"),
    ("GET", "/api/admin/suppliers"): API("PROVEEDOR_GESTIONAR"),
    ("POST", "/api/admin/suppliers"): API("PROVEEDOR_GESTIONAR"),
    ("PUT", "/api/admin/suppliers/{codigo}"): API("PROVEEDOR_GESTIONAR"),
    ("GET", "/api/rt-products"): API("PRODUCTOS_RT_CONSULTAR"),
    ("GET", "/api/rt-products/syncs"): API("PRODUCTOS_RT_SINCRONIZAR"),
    ("POST", "/api/rt-products/sync"): API("PRODUCTOS_RT_SINCRONIZAR"),
    ("GET", "/api/rt-products/{producto_id}"): API("PRODUCTOS_RT_CONSULTAR"),
}


def rutas(app):
    """Las rutas efectivas de la app (FastAPI agrupa las incluidas)."""
    for ruta in app.routes:
        if isinstance(ruta, APIRoute):
            yield ruta
        elif hasattr(ruta, "effective_route_contexts"):
            contextos = ruta.effective_route_contexts
            yield from (contextos() if callable(contextos) else contextos)


def permisos_en_la_api(ruta) -> list[tuple]:
    """Los ``exigir_rol`` de la ruta (de la ruta y de su router)."""
    encontrados = []

    def recorrer(dependiente):
        for dependencia in dependiente.dependencies:
            permitidos = getattr(dependencia.call, "permisos", None)
            if permitidos is not None:
                encontrados.append(tuple(permitidos))
            recorrer(dependencia)

    recorrer(ruta.dependant)
    return encontrados


@pytest.fixture(scope="module")
def actuales() -> dict[tuple[str, str], list[tuple]]:
    app = create_app(Settings(_env_file=None))
    return {
        (metodo, ruta.path): permisos_en_la_api(ruta)
        for ruta in rutas(app)
        for metodo in ruta.methods
    }


def test_toda_ruta_esta_clasificada(actuales):
    sin_clasificar = sorted(set(actuales) - set(MATRIZ))
    inexistentes = sorted(set(MATRIZ) - set(actuales))
    assert sin_clasificar == [], (
        f"Rutas nuevas sin clasificar: {sin_clasificar}"
    )
    assert inexistentes == [], (
        f"Rutas clasificadas que ya no existen: {inexistentes}"
    )


def test_la_api_exige_exactamente_los_permisos_de_la_matriz(actuales):
    for clave, esperado in MATRIZ.items():
        actual = actuales[clave]
        if isinstance(esperado, API):
            assert len(actual) == 1, (clave, actual)
            codigos = tuple(
                p.codigo if isinstance(p, Permiso) else p for p in actual[0]
            )
            assert codigos == tuple(esperado), (clave, codigos)
        else:
            assert actual == [], (clave, actual)


def test_ninguna_ruta_usa_un_rol_fijo(actuales):
    # CFG-02 (brecha 3): las rutas exigen permisos configurables, no
    # tuplas de roles escritas en el codigo.
    for clave, dependencias in actuales.items():
        for permitidos in dependencias:
            for permiso in permitidos:
                assert isinstance(permiso, Permiso), (clave, permiso)


def test_los_permisos_de_la_matriz_existen():
    for clave, esperado in MATRIZ.items():
        if isinstance(esperado, (API, SERVICIO)):
            for codigo in esperado:
                assert codigo in permisos.REGISTRO, (clave, codigo)


def test_ningun_permiso_queda_sin_uso():
    """Cada permiso del registro se exige en algun punto del backend; los
    de solo presentacion (BF-07), en el frontend, y en ningun endpoint."""
    raiz = Path(__file__).resolve().parents[1] / "app"
    fuentes = "\n".join(
        archivo.read_text(encoding="utf-8")
        for archivo in raiz.rglob("*.py")
        if archivo.name != "permisos.py"
    )
    sin_uso = [
        codigo
        for codigo in permisos.REGISTRO
        if not re.search(rf"\b{codigo}\b", fuentes)
    ]
    assert sorted(sin_uso) == sorted(permisos.SOLO_PRESENTACION)

    frontend = Path(__file__).resolve().parents[2] / "frontend" / "src"
    pantalla = "\n".join(
        archivo.read_text(encoding="utf-8")
        for archivo in frontend.rglob("*.ts*")
    )
    for codigo in permisos.SOLO_PRESENTACION:
        assert re.search(rf"\b{codigo}\b", pantalla), codigo


def test_los_comandos_de_servicio_no_tienen_rol_fijo_en_el_codigo():
    """CFG-02 (brechas 1 y 2): ningun caso de uso exige un rol fijo con
    ``roles=(RolUsuario.X,)``: lo que se exige es un permiso."""
    raiz = Path(__file__).resolve().parents[1] / "app"
    patron = re.compile(r"\(RolUsuario\.[A-Z_]+,\)")
    hallados = [
        f"{archivo.relative_to(raiz)}:{numero}"
        for archivo in raiz.rglob("*.py")
        for numero, linea in enumerate(
            archivo.read_text(encoding="utf-8").splitlines(), 1
        )
        if patron.search(linea)
        and "validar" not in linea
        and ("roles=" in linea or "exigir_rol" in linea)
        # Brecha 16 (registrada en DEUDA_TECNICA): el responsable que
        # muestra la situacion de la Orden es una vista por puesto, no una
        # autorizacion.
        and archivo.name != "situacion.py"
    ]
    assert hallados == []


def test_cada_permiso_requerido_existe_y_es_consulta():
    for permiso in permisos.REGISTRO.values():
        for codigo in permiso.requiere:
            assert permisos.REGISTRO[codigo].consulta, (permiso.codigo, codigo)


# --- El frontend (CFG-02, seccion 8) ------------------------------------------

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _fuentes_frontend():
    for archivo in FRONTEND.rglob("*.ts*"):
        yield archivo, archivo.read_text(encoding="utf-8")


def test_el_frontend_usa_solo_permisos_que_existen():
    """Todo codigo de ``puede(usuario, "X")`` y de las secciones de
    Configuracion existe en el registro (o es el alias de Compras para una
    API anterior)."""
    if not FRONTEND.exists():
        pytest.skip("Sin el frontend junto al backend.")
    validos = set(permisos.REGISTRO) | {permisos.ALIAS_COMPRAS_GESTIONAR}
    usados: dict[str, str] = {}
    for archivo, texto in _fuentes_frontend():
        for codigo in re.findall(r'puede\([^,()]+,\s*"([A-Z_]+)"', texto):
            usados[codigo] = archivo.name
        if archivo.name in ("secciones.ts", "recepcion.ts"):
            for codigo in re.findall(r'"([A-Z][A-Z_]{4,})"', texto):
                if codigo.endswith(
                    (
                        "_GESTIONAR",
                        "_ADMINISTRAR",
                        "_CREAR",
                        "_CONFIRMAR",
                        "_CANCELAR",
                        "_RECIBIR",
                        "_SOLICITAR",
                    )
                ):
                    usados[codigo] = archivo.name
    desconocidos = {c: a for c, a in usados.items() if c not in validos}
    assert desconocidos == {}
    assert usados, "no se encontraron permisos en el frontend"


def test_el_frontend_no_habilita_acciones_por_rol_fijo():
    """CFG-02 (brecha 18): ninguna pantalla habilita por ``tieneRol``; los
    ``tieneAlguno`` que quedan usan los roles que manda la API para cada
    accion (``accion.roles``, con la politica vigente)."""
    if not FRONTEND.exists():
        pytest.skip("Sin el frontend junto al backend.")
    hallados = []
    for archivo, texto in _fuentes_frontend():
        if archivo.name == "roles.ts" and archivo.parent.name == "lib":
            continue
        for numero, linea in enumerate(texto.splitlines(), 1):
            if "tieneRol(" in linea:
                hallados.append(f"{archivo.name}:{numero}")
            if (
                "tieneAlguno(" in linea
                and "roles" not in linea.split("tieneAlguno(")[1]
            ):
                hallados.append(f"{archivo.name}:{numero}")
    assert hallados == []


# Comparaciones con un rol escrito en el codigo que NO habilitan acciones.
COMPARACIONES_DE_ROL_PERMITIDAS = {
    # Regla de la pantalla de roles: nunca queda el sistema sin un
    # Administrador activo (la API la valida igual).
    "roles.ts",
    # Atajo de navegacion por puesto ("Ver el taller"): no es una accion;
    # la pantalla de destino aplica sus permisos (como la brecha 16).
    "PantallasTrabajo.tsx",
}


def test_el_frontend_no_compara_roles_para_habilitar_acciones():
    """QA D, M2: tampoco ``.includes("RECEPCION")`` ni ``=== "TECNICO"``
    para mostrar una accion: se usa el permiso."""
    if not FRONTEND.exists():
        pytest.skip("Sin el frontend junto al backend.")
    roles = "RECEPCION|TECNICO|COORDINADOR_RMA|ADMINISTRADOR"
    patron = re.compile(
        rf'(includes\("({roles})"\)|===\s*"({roles})"|"({roles})"\s*===)'
    )
    hallados = [
        f"{archivo.name}:{numero}"
        for archivo, texto in _fuentes_frontend()
        if archivo.name not in COMPARACIONES_DE_ROL_PERMITIDAS
        and not (archivo.name == "roles.ts" and archivo.parent.name == "lib")
        for numero, linea in enumerate(texto.splitlines(), 1)
        if patron.search(linea)
    ]
    assert hallados == []
