"""E2: los 13 reemplazos de ``listar()`` dan el mismo resultado que antes.

Un corpus armado por la API (reserva pendiente, reserva consumida y
entregada, cancelada, clientes con DNI, fotos) se lee con dos contextos:

- el real, con las consultas dedicadas;
- uno de referencia, cuyo repository responde cada consulta dedicada
  con ``listar()``, como antes de E2.

Cada caso de uso reemplazado tiene que devolver lo mismo en los dos. Los
que escriben se comparan sobre dos copias del mismo directorio.

Diseno: ``docs/postgresql/e2-consultas-dedicadas.md`` (secciones B y C).
"""

import ast
import re
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.application import (
    bandejas_de_inicio,
    bandejas_de_taller,
    buscar_cliente_por_dni,
    construir_contexto,
    consultar_inventario,
    crear_orden,
    detalle_de_insumo,
    limpiar_fotos_huerfanas,
    movimientos_de_inventario,
    pendientes_de_autorizacion,
    registrar_ingreso_stock,
    revalidar_ordenes_pendientes,
    siguiente_orden_id,
)
from app.core.config import Settings
from app.domain.models import Cliente, Equipo, TipoMovimientoInsumo
from app.main import create_app
from app.services import (
    ClienteExistenteError,
    cargar_reservas_externas,
    fotos_referenciadas,
    reservas_externas_a,
)
from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    COORDINADOR,
    INSUMO_BATERIA,
    RECEPCION,
    TECNICO,
    TECNICO_B,
    aprobar,
    cancelar_orden,
    definida,
    ejecutar,
    iniciar,
    notificar_pagar_entregar,
    ok,
    sembrar,
    tomada,
)
from tests.test_fotos_orden import JPEG

AHORA = datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc)
DNI = "30111222"
USUARIOS = (RECEPCION, COORDINADOR, TECNICO, TECNICO_B, ADMINISTRADOR)
RAIZ_APP = Path(__file__).resolve().parents[1] / "app"
_PATRON_ORDEN = re.compile(r"^OR-(\d+)$")


class _ComoAntes:
    """Responde cada consulta dedicada como antes de E2: con todo."""

    def __init__(self, repo):
        self._repo = repo

    def __getattr__(self, nombre):
        return getattr(self._repo, nombre)

    def obtener_para_modificar(self, orden_id):
        return self._repo.obtener(orden_id)

    def reservar_codigo(self):
        # El algoritmo de identificadores.siguiente_orden_id antes de E2.
        maximo = 0
        for orden in self._repo.listar():
            encontrado = _PATRON_ORDEN.match(orden.id)
            if encontrado:
                maximo = max(maximo, int(encontrado.group(1)))
        return f"OR-{maximo + 1:06d}"

    def listar_abiertas(self):
        return self._repo.listar()

    def listar_por_dni_cliente(self, dni):
        return self._repo.listar()

    def listar_con_reservas(self, insumo_ids=None):
        return self._repo.listar()

    def listar_con_movimientos(self, insumo_id=None):
        return self._repo.listar()

    def claves_de_fotos(self):
        return frozenset(fotos_referenciadas(self._repo.listar()))


def _settings(directorio: Path) -> Settings:
    return Settings(data_dir=directorio, fotos_dir=directorio / "fotos")


def _contextos(directorio: Path):
    real = replace(
        construir_contexto(_settings(directorio)), ahora=lambda: AHORA
    )
    return real, replace(real, ordenes=_ComoAntes(real.ordenes))


def _crear_con_dni(cliente: TestClient, cliente_id: str | None = None):
    datos = {"nombre_apellido": "Ana Paz", "telefono": "341-2", "dni": DNI}
    if cliente_id:
        datos["id"] = cliente_id
    return ok(
        cliente.post(
            "/api/orders",
            json={
                "usuario_id": RECEPCION,
                "cliente": datos,
                "equipo": {
                    "marca": "Apple",
                    "modelo": "iPhone 13",
                    "falla_reportada": "No enciende.",
                },
            },
        )
    )


def _subir_foto(cliente: TestClient, orden_id: str) -> None:
    ok(
        cliente.post(
            f"/api/orders/{orden_id}/photos",
            params={"usuario_id": RECEPCION},
            content=JPEG,
            headers={"Content-Type": "application/octet-stream"},
        )
    )


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> Path:
    """Ordenes en estados distintos, armadas por la API."""
    directorio = tmp_path_factory.mktemp("corpus_e2")
    sembrar(directorio, "5")
    with TestClient(create_app(_settings(directorio))) as cliente:
        # Reserva consumida, aprobada y entregada (cerrada), con foto.
        entregada = definida(cliente)
        tomada(cliente, entregada)
        ejecutar(cliente, entregada)
        ok(aprobar(cliente, entregada, "DET-001"))
        _subir_foto(cliente, entregada)
        notificar_pagar_entregar(cliente, entregada)
        # Reserva pendiente: tomada e iniciada (PROC-REP-185), con foto.
        con_reserva = definida(cliente)
        tomada(cliente, con_reserva, TECNICO_B)
        iniciar(cliente, con_reserva, tecnico=TECNICO_B)
        _subir_foto(cliente, con_reserva)
        # Cancelada: sigue abierta (esta_cerrada es ENTREGADA o 999).
        ok(cancelar_orden(cliente, definida(cliente)))
        # El mismo cliente con DNI en dos Ordenes.
        primera = _crear_con_dni(cliente)
        _crear_con_dni(cliente, primera["cliente"]["id"])
        # Sin DNI y sin trabajos.
        definida(cliente)
    return directorio


def _copia(corpus: Path, tmp_path: Path, nombre: str) -> Path:
    destino = tmp_path / nombre
    shutil.copytree(corpus, destino)
    return destino


def test_el_corpus_cubre_los_casos_de_los_reemplazos(corpus):
    real, _ = _contextos(corpus)
    ordenes = real.ordenes.listar()
    assert any(o.esta_cerrada for o in ordenes)
    assert any(o.estado_workflow.value == "CANCELADA" for o in ordenes)
    tipos = {m.tipo for o in ordenes for m in o.movimientos_insumo}
    assert {TipoMovimientoInsumo.RESERVA, TipoMovimientoInsumo.CONSUMO} <= (
        tipos
    )
    assert len(real.ordenes.listar_por_dni_cliente(DNI)) == 2
    assert len(real.ordenes.claves_de_fotos()) == 2
    # La cerrada conserva su reserva (consumida): el prefiltro la trae.
    cerradas_con_reserva = [
        o for o in real.ordenes.listar_con_reservas() if o.esta_cerrada
    ]
    assert cerradas_con_reserva


# --- Lecturas: mismo resultado con y sin consultas dedicadas ----------------


@pytest.mark.parametrize("usuario_id", USUARIOS)
def test_q06_bandejas_iguales(corpus, usuario_id):
    real, antes = _contextos(corpus)
    for bandejas in (bandejas_de_inicio, bandejas_de_taller):
        assert bandejas(real, usuario_id=usuario_id) == bandejas(
            antes, usuario_id=usuario_id
        )


def test_q05_pendientes_de_autorizacion_iguales(corpus):
    real, antes = _contextos(corpus)
    assert pendientes_de_autorizacion(real) == pendientes_de_autorizacion(
        antes
    )


@pytest.mark.parametrize(
    "filtros",
    [{}, {"solo_faltantes": True}, {"buscar": "bat"}, {"buscar": "zzz"}],
)
def test_q08_inventario_igual(corpus, filtros):
    real, antes = _contextos(corpus)
    assert consultar_inventario(real, **filtros) == consultar_inventario(
        antes, **filtros
    )


def test_q09_detalle_de_cada_insumo_igual(corpus):
    real, antes = _contextos(corpus)
    for insumo in real.catalogos.listar_insumos():
        assert detalle_de_insumo(real, insumo.id) == detalle_de_insumo(
            antes, insumo.id
        )


def test_q10_movimientos_iguales_con_y_sin_filtros(corpus):
    real, antes = _contextos(corpus)
    filtros = [{}]
    filtros += [{"insumo_id": i.id} for i in real.catalogos.listar_insumos()]
    filtros += [{"tipo": tipo} for tipo in TipoMovimientoInsumo]
    filtros += [{"insumo_id": INSUMO_BATERIA, "tipo": "RESERVA"}]
    for filtro in filtros:
        assert movimientos_de_inventario(
            real, **filtro
        ) == movimientos_de_inventario(antes, **filtro)


@pytest.mark.parametrize("dni", [DNI, "99999999"])
def test_q02_busqueda_por_dni_igual(corpus, dni):
    real, antes = _contextos(corpus)
    argumentos = {
        "dni": dni,
        "usuario_id": RECEPCION,
        "incluir_externa": False,
    }
    assert buscar_cliente_por_dni(real, **argumentos) == (
        buscar_cliente_por_dni(antes, **argumentos)
    )


def test_q13_q14_reservas_externas_iguales(corpus):
    real, _ = _contextos(corpus)
    todas = real.ordenes.listar()
    for orden_id in [o.id for o in todas] + ["OR-999999"]:
        assert cargar_reservas_externas(orden_id, real.ordenes) == (
            reservas_externas_a(orden_id, todas)
        )
        # _tope_por_override usa la misma lista (services/inventario_global).
        assert reservas_externas_a(
            orden_id, real.ordenes.listar_con_reservas()
        ) == reservas_externas_a(orden_id, todas)


def test_q07_claves_de_fotos_y_limpieza_iguales(corpus):
    real, antes = _contextos(corpus)
    assert real.ordenes.claves_de_fotos() == fotos_referenciadas(
        real.ordenes.listar()
    )
    assert limpiar_fotos_huerfanas(
        real, usuario_id=ADMINISTRADOR
    ) == limpiar_fotos_huerfanas(antes, usuario_id=ADMINISTRADOR)


def test_q01_q15_numero_y_lectura_para_modificar_iguales(corpus):
    real, antes = _contextos(corpus)
    with real.transaccion():
        assert siguiente_orden_id(real.ordenes) == siguiente_orden_id(
            antes.ordenes
        )
        for orden in real.ordenes.listar():
            assert real.ordenes.obtener_para_modificar(orden.id) == (
                real.ordenes.obtener(orden.id)
            )


# --- Escrituras: mismas respuestas sobre dos copias -------------------------


def test_q12_revalidacion_igual(corpus, tmp_path):
    real, _ = _contextos(_copia(corpus, tmp_path, "real"))
    otro, _ = _contextos(_copia(corpus, tmp_path, "antes"))
    antes = replace(otro, ordenes=_ComoAntes(otro.ordenes))
    assert revalidar_ordenes_pendientes(
        real, usuario_id=COORDINADOR
    ) == revalidar_ordenes_pendientes(antes, usuario_id=COORDINADOR)
    assert real.ordenes.listar() == antes.ordenes.listar()


def test_q11_ingreso_de_stock_igual(corpus, tmp_path):
    real, _ = _contextos(_copia(corpus, tmp_path, "real"))
    otro, _ = _contextos(_copia(corpus, tmp_path, "antes"))
    antes = replace(otro, ordenes=_ComoAntes(otro.ordenes))
    argumentos = {
        "insumo_id": INSUMO_BATERIA,
        "usuario_id": ADMINISTRADOR,
        "cantidad": Decimal("2"),
        "motivo": "Compra",
    }
    uno = registrar_ingreso_stock(real, **argumentos)
    dos = registrar_ingreso_stock(antes, **argumentos)
    assert uno.situacion == dos.situacion
    assert uno.movimiento.model_dump(exclude={"id"}) == (
        dos.movimiento.model_dump(exclude={"id"})
    )


def _cliente_nuevo(dni: str) -> Cliente:
    return Cliente(
        id="CLI-NUEVO", dni=dni, nombre_apellido="Otra", telefono="1"
    )


def _equipo() -> Equipo:
    return Equipo(
        id="EQ-NUEVO",
        marca="Apple",
        modelo="iPhone 12",
        falla_reportada="Pantalla.",
    )


def test_q03_alta_con_dni_ya_usado_rechaza_igual(corpus, tmp_path):
    real, _ = _contextos(_copia(corpus, tmp_path, "real"))
    otro, _ = _contextos(_copia(corpus, tmp_path, "antes"))
    antes = replace(otro, ordenes=_ComoAntes(otro.ordenes))
    mensajes = []
    for contexto in (real, antes):
        with pytest.raises(ClienteExistenteError) as error:
            crear_orden(
                contexto,
                usuario_id=RECEPCION,
                cliente=_cliente_nuevo(DNI),
                equipo=_equipo(),
            )
        mensajes.append(str(error.value))
    assert mensajes[0] == mensajes[1]
    assert real.ordenes.listar() == antes.ordenes.listar()


@pytest.mark.parametrize("dni", ["40111222", None])
def test_q01_q03_alta_valida_igual(corpus, tmp_path, dni):
    real, _ = _contextos(_copia(corpus, tmp_path, "real"))
    otro, _ = _contextos(_copia(corpus, tmp_path, "antes"))
    antes = replace(otro, ordenes=_ComoAntes(otro.ordenes))
    argumentos = {
        "usuario_id": RECEPCION,
        "cliente": _cliente_nuevo(dni),
        "equipo": _equipo(),
    }
    existentes = len(real.ordenes.listar())
    nueva = crear_orden(real, **argumentos)
    assert nueva == crear_orden(antes, **argumentos)
    assert nueva.id == f"OR-{existentes + 1:06d}"  # sin huecos en JSON
    assert real.ordenes.listar() == antes.ordenes.listar()


# --- Control estatico -------------------------------------------------------

# Unicos recorridos completos autorizados (diseno E2, seccion C):
# el listado general (Q04) y las evidencias de faltante (F-03).
LISTAR_AUTORIZADO = {
    ("application/consultas.py", "listar_ordenes"),
    ("application/inventario.py", "detalle_de_insumo"),
}


def _usos_de_listar() -> set[tuple[str, str]]:
    usos = set()
    for archivo in sorted(RAIZ_APP.rglob("*.py")):
        relativo = archivo.relative_to(RAIZ_APP).as_posix()
        if relativo.split("/")[0] not in ("application", "services", "api"):
            continue
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for funcion in ast.walk(arbol):
            if not isinstance(funcion, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for nodo in ast.walk(funcion):
                if (
                    isinstance(nodo, ast.Call)
                    and isinstance(nodo.func, ast.Attribute)
                    and nodo.func.attr == "listar"
                    and "ordenes" in ast.unparse(nodo.func.value)
                ):
                    usos.add((relativo, funcion.name))
    return usos


def test_ningun_caso_de_uso_recorre_todas_las_ordenes_sin_autorizacion():
    assert _usos_de_listar() == LISTAR_AUTORIZADO
