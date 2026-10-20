"""Bandejas de trabajo por rol y cola de taller (``/api/work``).

Las bandejas no deducen nada de los estados: salen de las tareas y los
avisos de la situacion operativa, con las acciones que el usuario elegido
puede ejecutar. La cola son las Ordenes con Tomar disponible, por
prioridad (1 a 4) y antiguedad. Todo es de solo lectura.
"""

import json

import pytest

from app.application import AccionDisponible, puede_ejecutar
from app.domain.models import RolUsuario, Usuario
from tests.fixtures.api_salidas import (
    ADMINISTRADOR,
    BATERIA,
    COORDINADOR,
    PANTALLA,
    RECEPCION,
    TECNICO,
    TECNICO_B,
    agregar,
    aprobar,
    archivo,
    autorizar_todo,
    cancelar_orden,
    cerrar_ejecucion,
    conflicto,
    crear,
    decidir,
    definida,
    encolar,
    finalizar,
    iniciar,
    ok,
    tomada,
    tomar,
)
from tests.fixtures.custodia import confirmar_recepcion, entregar
from tests.test_api_hp_rep_002 import _crear_orden_rt
from tests.test_inventario_operativo import _cliente

ROLES = (RECEPCION, TECNICO, COORDINADOR, ADMINISTRADOR)


def _bandejas(cliente, usuario, vista="inbox") -> dict[str, dict]:
    datos = ok(
        cliente.get(f"/api/work/{vista}", params={"usuario_id": usuario})
    )
    return {bandeja["codigo"]: bandeja for bandeja in datos["bandejas"]}


def _ids(bandeja: dict) -> list[str]:
    return [item["orden"]["id"] for item in bandeja["ordenes"]]


def _item(bandeja: dict, orden_id: str) -> dict:
    return next(i for i in bandeja["ordenes"] if i["orden"]["id"] == orden_id)


def _encolar(cliente, orden_id, prioridad):
    """A la cola con esa prioridad (si ya entro sola, se la cambia)."""
    return ok(encolar(cliente, orden_id, prioridad))


def _en_cola(cliente, prioridad, *tipos) -> str:
    orden_id = definida(cliente, *tipos)
    _encolar(cliente, orden_id, prioridad)
    return orden_id


def _notificar(cliente, orden_id) -> dict:
    return ok(
        cliente.post(
            f"/api/orders/{orden_id}/notify", json={"usuario_id": RECEPCION}
        )
    )


def _pagar(cliente, orden_id, monto):
    return ok(
        cliente.post(
            f"/api/orders/{orden_id}/payments",
            json={
                "usuario_id": RECEPCION,
                "monto": monto,
                "metodo": "EFECTIVO",
            },
        )
    )


def _reparada(cliente) -> str:
    """Trabajo realizado, esperando el control de Recepcion."""
    orden_id = definida(cliente)
    tomada(cliente, orden_id)
    ok(cerrar_ejecucion(cliente, orden_id, iniciar(cliente, orden_id)))
    return orden_id


# --- 1, 2 y 16. Bandejas por rol y contadores --------------------------------


def test_cada_rol_ve_sus_bandejas(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        esperadas = {
            RECEPCION: [
                "RECEPCION_FISICA",
                "DEFINICION",
                "AUTORIZACION",
                "CONTROL",
                "AVISO",
                "INFORMAR_RT",
                "COBROS",
                "ENTREGA",
                "DEVOLUCION_EQUIPO",
                "PRIORIZAR",
                "EN_OTROS_SECTORES",
            ],
            TECNICO: ["MIS_TOMADAS", "COLA", "REVISIONES"],
            COORDINADOR: [
                "RECURSOS",
                "PRIORIZAR",
                "REVISION_PENDIENTE",
                "COLA",
                "EN_TALLER",
                "INSUMOS_NEGATIVOS",
            ],
            ADMINISTRADOR: [
                "COBROS",
                "CREDITO",
                "SALDOS",
                "INSUMOS_NEGATIVOS",
            ],
        }

        for usuario, codigos in esperadas.items():
            assert list(_bandejas(cliente, usuario)) == codigos, usuario
        assert list(_bandejas(cliente, TECNICO, "workshop")) == [
            "MIS_TOMADAS",
            "COLA",
            "REVISIONES",
            "EN_TALLER",
        ]
        assert list(_bandejas(cliente, COORDINADOR, "workshop")) == [
            "COLA",
            "EN_TALLER",
            "REVISION_PENDIENTE",
        ]
        assert (
            cliente.get(
                "/api/work/inbox", params={"usuario_id": "NADIE"}
            ).status_code
            == 404
        )


def test_los_contadores_son_lo_que_se_lista(tmp_path):
    with _cliente(tmp_path, stock_bateria="2", stock_pantalla="0") as cliente:
        crear(cliente)
        definida(cliente, autorizar=False)
        _en_cola(cliente, 2)
        definida(cliente, BATERIA, PANTALLA)  # pantalla sin stock
        _reparada(cliente)

        for usuario in (*ROLES, TECNICO_B):
            for vista in ("inbox", "workshop"):
                for codigo, bandeja in _bandejas(
                    cliente, usuario, vista
                ).items():
                    assert bandeja["cantidad"] == len(
                        bandeja["ordenes"]
                    ) + len(bandeja["insumos"]), (usuario, vista, codigo)


def test_consultar_las_bandejas_no_modifica_nada(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        ordenes = [crear(cliente), _en_cola(cliente, 3)]
        tomada(cliente, definida(cliente))
        antes = {o: archivo(tmp_path, o) for o in ordenes}

        for usuario in ROLES:
            _bandejas(cliente, usuario)
            _bandejas(cliente, usuario, "workshop")

        assert {o: archivo(tmp_path, o) for o in ordenes} == antes


# --- 3, 4 y 5. Recepcion -----------------------------------------------------


def test_orden_recien_ingresada_en_definicion(tmp_path):
    """Ingreso inicial (MVP v2): la confirmacion fisica va dentro del
    comprobante de ingreso, asi que la Orden no espera en "Confirmar la
    recepcion": esta en "Definir reparaciones"."""
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = crear(cliente)

        bandejas = _bandejas(cliente, RECEPCION)

        assert _ids(bandejas["RECEPCION_FISICA"]) == []
        assert _ids(bandejas["DEFINICION"]) == [orden_id]
        item = _item(bandejas["DEFINICION"], orden_id)
        assert item["tarea"] == "Cargar los trabajos"
        assert item["puede_resolver"] is True
        assert item["orden"]["situacion"]["codigo"] == "PENDIENTE_RECEPCION"
        # No es del taller ni de Coordinacion.
        assert not _bandejas(cliente, TECNICO)["COLA"]["ordenes"]

        agregar(cliente, orden_id)
        item = _item(_bandejas(cliente, RECEPCION)["DEFINICION"], orden_id)
        assert item["tarea"] == (
            "Generar el comprobante de ingreso y autorización"
        )

        confirmar_recepcion(cliente, orden_id)
        bandejas = _bandejas(cliente, RECEPCION)

        assert _ids(bandejas["RECEPCION_FISICA"]) == []
        assert _ids(bandejas["DEFINICION"]) == [orden_id]


def test_autorizacion_pendiente_del_cliente(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = definida(cliente, autorizar=False)

        item = _item(_bandejas(cliente, RECEPCION)["AUTORIZACION"], orden_id)

        assert item["tarea"] == "Registrar la decisión del cliente"
        assert item["orden"]["situacion"]["codigo"] == "ESPERANDO_AUTORIZACION"
        assert item["trabajos"][0]["pendiente_autorizacion"] is True
        # Lo resuelve Recepcion: el tecnico no lo ve en su inicio.
        assert orden_id not in _ids(_bandejas(cliente, TECNICO)["COLA"])


# --- 6. Control, cobro y entrega ---------------------------------------------


def test_control_aviso_cobro_y_entrega(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _reparada(cliente)
        assert _ids(_bandejas(cliente, RECEPCION)["CONTROL"]) == [orden_id]

        ok(aprobar(cliente, orden_id, "DET-001"))
        bandejas = _bandejas(cliente, RECEPCION)
        assert _ids(bandejas["CONTROL"]) == []
        assert _ids(bandejas["AVISO"]) == [orden_id]
        # Obligacion independiente: el saldo ya se puede cobrar.
        assert _ids(bandejas["COBROS"]) == [orden_id]

        saldo = _notificar(cliente, orden_id)["resumen"]["saldo"]
        bandejas = _bandejas(cliente, RECEPCION)
        assert _ids(bandejas["AVISO"]) == []
        cobro = _item(bandejas["COBROS"], orden_id)
        assert cobro["tarea"] == "Registrar el pago pendiente"
        assert _ids(_bandejas(cliente, ADMINISTRADOR)["COBROS"]) == [orden_id]
        assert _ids(bandejas["ENTREGA"]) == []

        _pagar(cliente, orden_id, saldo)
        bandejas = _bandejas(cliente, RECEPCION)
        assert _ids(bandejas["COBROS"]) == []
        assert _ids(bandejas["ENTREGA"]) == [orden_id]

        ok(entregar(cliente, orden_id))
        bandejas = _bandejas(cliente, RECEPCION)
        assert all(orden_id not in _ids(b) for b in bandejas.values())


# --- 7, 8, 18 y 19. Mis tomadas, otro tecnico y toma desde la cola -----------


def test_mis_ordenes_tomadas(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _en_cola(cliente, 2)
        assert _ids(_bandejas(cliente, TECNICO)["COLA"]) == [orden_id]

        tomar(cliente, orden_id)  # el endpoint de siempre

        mias = _bandejas(cliente, TECNICO)["MIS_TOMADAS"]
        assert _ids(mias) == [orden_id]
        item = _item(mias, orden_id)
        assert item["estacion_id"] == "EST-001"
        assert item["tomada_desde"] is not None
        assert item["desde"] == item["tomada_desde"]
        assert item["tarea"] == "Iniciar la reparación"
        assert item["puede_resolver"] is True
        assert item["falla"] == "No carga."
        assert [t["trabajable"] for t in item["trabajos"]] == [True]
        assert _ids(_bandejas(cliente, TECNICO)["COLA"]) == []

        iniciar(cliente, orden_id)
        item = _item(_bandejas(cliente, TECNICO)["MIS_TOMADAS"], orden_id)
        assert item["trabajo_en_curso"] == item["trabajos"][0]["nombre"]
        assert item["en_curso_desde"] is not None
        assert item["tarea"] == "Completar la reparación"


def test_una_orden_tomada_no_esta_disponible_para_otro_tecnico(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _en_cola(cliente, 1)
        tomar(cliente, orden_id, TECNICO)

        otro = _bandejas(cliente, TECNICO_B, "workshop")
        assert _ids(otro["MIS_TOMADAS"]) == []
        assert _ids(otro["COLA"]) == []
        ajena = _item(otro["EN_TALLER"], orden_id)
        assert ajena["orden"]["tecnico_id"] == TECNICO
        assert ajena["puede_resolver"] is False

        # Tomarla de nuevo no duplica la toma.
        conflicto(
            cliente.post(
                f"/api/orders/{orden_id}/take",
                json={"usuario_id": TECNICO_B, "estacion_id": "EST-001"},
            )
        )
        orden = ok(cliente.get(f"/api/orders/{orden_id}"))
        activas = [t for t in orden["tomas"] if t["estado"] == "ACTIVA"]
        assert [t["usuario_id"] for t in activas] == [TECNICO]
        coordinacion = _bandejas(cliente, COORDINADOR)["EN_TALLER"]
        assert _ids(coordinacion) == [orden_id]


# --- 9, 10 y 11. Cola por prioridad ------------------------------------------


def test_cola_de_1_a_4_y_a_igual_prioridad_la_mas_antigua(tmp_path):
    with _cliente(tmp_path, stock_bateria="9") as cliente:
        media = _en_cola(cliente, 3)
        alta_antigua = _en_cola(cliente, 2)
        normal = _en_cola(cliente, 4)
        urgente = _en_cola(cliente, 1)
        alta_nueva = _en_cola(cliente, 2)

        cola = _bandejas(cliente, TECNICO, "workshop")["COLA"]

        assert _ids(cola) == [urgente, alta_antigua, alta_nueva, media, normal]
        assert [i["orden"]["prioridad_texto"] for i in cola["ordenes"]] == [
            "Prioridad 1 · Urgente",
            "Prioridad 2 · Alta",
            "Prioridad 2 · Alta",
            "Prioridad 3 · Media",
            "Prioridad 4 · Normal",
        ]
        assert all(i["puede_tomar"] for i in cola["ordenes"])
        assert [e["id"] for e in cola["ordenes"][0]["estaciones"]] == [
            "EST-001"
        ]
        assert cola["tipo"] == "TAREAS"
        # Coordinacion la sigue, pero no toma.
        para_coordinar = _bandejas(cliente, COORDINADOR)["COLA"]
        assert _ids(para_coordinar) == _ids(cola)
        assert para_coordinar["tipo"] == "SEGUIMIENTO"
        assert not any(i["puede_tomar"] for i in para_coordinar["ordenes"])


def test_la_cola_excluye_cerradas_canceladas_y_tomadas(tmp_path):
    with _cliente(tmp_path, stock_bateria="9") as cliente:
        disponible = _en_cola(cliente, 4)
        cancelada = _en_cola(cliente, 1)
        ok(cancelar_orden(cliente, cancelada))
        tomada_id = _en_cola(cliente, 1)
        tomar(cliente, tomada_id)
        entregada = _reparada(cliente)
        ok(aprobar(cliente, entregada, "DET-001"))
        saldo = _notificar(cliente, entregada)["resumen"]["saldo"]
        _pagar(cliente, entregada, saldo)
        ok(entregar(cliente, entregada))

        assert _ids(_bandejas(cliente, TECNICO_B, "workshop")["COLA"]) == [
            disponible
        ]


# --- 12, 13 y estados mixtos -------------------------------------------------


def test_factibilidad_parcial_en_la_cola_y_en_recursos(tmp_path):
    with _cliente(tmp_path, stock_bateria="5", stock_pantalla="0") as cliente:
        orden_id = definida(cliente, BATERIA, PANTALLA)
        _encolar(cliente, orden_id, 3)

        cola = _item(_bandejas(cliente, TECNICO)["COLA"], orden_id)
        recursos = _bandejas(cliente, COORDINADOR)["RECURSOS"]

        # No se la trata como bloqueada: tiene un trabajo para hacer.
        assert cola["orden"]["situacion"]["codigo"] == "EN_COLA"
        trabajos = {t["detalle_id"]: t for t in cola["trabajos"]}
        assert trabajos["DET-001"]["trabajable"] is True
        assert trabajos["DET-002"]["condicion"] == "BLOQUEADO_POR_RECURSOS"
        assert trabajos["DET-002"]["faltantes"]
        assert any(c.startswith("Sin repuestos") for c in cola["condiciones"])
        item = _item(recursos, orden_id)
        assert item["tarea"].startswith("Sin repuestos")
        assert item["puede_resolver"] is True  # override de Coordinacion
        assert recursos["destino"] == "INVENTARIO"


def test_un_trabajo_pendiente_de_autorizacion_no_frena_al_otro(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = definida(cliente, BATERIA, PANTALLA, autorizar=False)
        ok(decidir(cliente, orden_id, {"DET-001": "AUTORIZADO"}))
        _encolar(cliente, orden_id, 2)

        assert orden_id in _ids(_bandejas(cliente, TECNICO)["COLA"])
        autorizacion = _bandejas(cliente, RECEPCION)["AUTORIZACION"]
        item = _item(autorizacion, orden_id)
        assert item["tarea"].startswith("Esperando la decisión del cliente")

        # Con la ejecucion en curso la decision sigue pendiente aparte.
        tomar(cliente, orden_id)
        iniciar(cliente, orden_id)
        assert orden_id in _ids(_bandejas(cliente, RECEPCION)["AUTORIZACION"])
        mia = _item(_bandejas(cliente, TECNICO)["MIS_TOMADAS"], orden_id)
        trabajos = {t["detalle_id"]: t for t in mia["trabajos"]}
        assert trabajos["DET-001"]["en_curso"] is True
        assert trabajos["DET-002"]["pendiente_autorizacion"] is True


# --- 14. Coordinacion y recursos ---------------------------------------------


def test_coordinacion_ve_faltantes_y_disponible_negativo(tmp_path):
    with _cliente(tmp_path, stock_bateria="1") as cliente:
        en_taller = definida(cliente)
        tomada(cliente, en_taller)
        iniciar(cliente, en_taller)  # reserva la unica bateria
        esperando = crear(cliente)
        ok(
            cliente.post(
                f"/api/orders/{esperando}/details",
                json={"usuario_id": RECEPCION, "tipo_reparacion_id": BATERIA},
            )
        )
        finalizar(cliente, esperando)  # comprobante de ingreso: autoriza
        # Se rompe la unica bateria del stock: queda reservada sin fisico.
        ok(
            cliente.post(
                "/api/inventory/INS-001/adjustments",
                json={
                    "usuario_id": ADMINISTRADOR,
                    "diferencia": "-1",
                    "motivo": "Unidad danada",
                    "confirmado": True,
                },
            )
        )

        bandejas = _bandejas(cliente, COORDINADOR)

        item = _item(bandejas["RECURSOS"], esperando)
        assert item["orden"]["situacion"]["codigo"] == "ESPERANDO_RECURSOS"
        assert item["trabajos"][0]["faltantes"] == ["Bateria"]
        negativos = bandejas["INSUMOS_NEGATIVOS"]
        assert [i["id"] for i in negativos["insumos"]] == ["INS-001"]
        assert negativos["insumos"][0]["disponible"] == "-1"
        assert negativos["cantidad"] == 1
        assert _ids(bandejas["EN_TALLER"]) == [en_taller]
        assert [
            i["id"]
            for i in _bandejas(cliente, ADMINISTRADOR)["INSUMOS_NEGATIVOS"][
                "insumos"
            ]
        ] == ["INS-001"]


# --- 15. Administracion y saldos ---------------------------------------------


def test_administracion_cobros_credito_y_saldos(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        con_sena = crear(cliente)
        _pagar(cliente, con_sena, "50000")  # sena antes de definir
        ok(cancelar_orden(cliente, con_sena))
        en_curso = definida(cliente)  # total definido, nada cobrado
        lista = _reparada(cliente)
        ok(aprobar(cliente, lista, "DET-001"))
        _notificar(cliente, lista)

        bandejas = _bandejas(cliente, ADMINISTRADOR)

        assert _ids(bandejas["COBROS"]) == [lista]
        credito = _item(bandejas["CREDITO"], con_sena)
        assert credito["credito"] == "50000"
        assert credito["tarea"] == "Devolver el dinero al cliente"
        assert _ids(bandejas["SALDOS"]) == [en_curso]
        assert bandejas["SALDOS"]["tipo"] == "SEGUIMIENTO"
        recepcion = _bandejas(cliente, RECEPCION)["COBROS"]
        assert set(_ids(recepcion)) == {lista, con_sena}


# --- Seguimiento de Recepcion ------------------------------------------------


def test_recepcion_distingue_lo_que_resuelve_otro_sector(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        en_cola = _en_cola(cliente, 2)
        propia = crear(cliente)

        otros = _bandejas(cliente, RECEPCION)["EN_OTROS_SECTORES"]

        assert otros["tipo"] == "SEGUIMIENTO"
        assert _ids(otros) == [en_cola]
        item = _item(otros, en_cola)
        assert item["puede_resolver"] is False
        assert item["responsable"] == "Técnico"
        assert propia not in _ids(otros)


# --- Permisos: la misma regla que el servidor --------------------------


def _usuario(usuario_id, rol, activo=True) -> Usuario:
    return Usuario(id=usuario_id, nombre=usuario_id, rol=rol, activo=activo)


def _accion(
    roles, requiere_actor=True, usuario_id=None, usuario_excluido_id=None
) -> AccionDisponible:
    return AccionDisponible(
        codigo="X",
        etiqueta="X",
        roles=tuple(roles),
        requiere_actor=requiere_actor,
        usuario_id=usuario_id,
        usuario_excluido_id=usuario_excluido_id,
    )


_RECEPCION = _usuario(RECEPCION, RolUsuario.RECEPCION)
_TECNICO = _usuario(TECNICO, RolUsuario.TECNICO)
_OTRO_TECNICO = _usuario(TECNICO_B, RolUsuario.TECNICO)
_ADMINISTRACION = _usuario(ADMINISTRADOR, RolUsuario.ADMINISTRADOR)
_INACTIVO = _usuario("RECEP-009", RolUsuario.RECEPCION, activo=False)

# Los mismos casos que ``tests/permisos.test.ts`` del frontend.
CASOS_DE_PERMISO = [
    ("sistema", _accion([], requiere_actor=False), _INACTIVO, True),
    ("rol autorizado", _accion([RolUsuario.RECEPCION]), _RECEPCION, True),
    ("otro rol", _accion([RolUsuario.RECEPCION]), _TECNICO, False),
    (
        "varios roles sin jerarquia",
        _accion([RolUsuario.COORDINADOR_RMA, RolUsuario.RECEPCION]),
        _RECEPCION,
        True,
    ),
    ("sin rol definido", _accion([]), _ADMINISTRACION, True),
    (
        "titular de la toma",
        _accion([RolUsuario.TECNICO], usuario_id=TECNICO),
        _TECNICO,
        True,
    ),
    (
        "otro tecnico",
        _accion([RolUsuario.TECNICO], usuario_id=TECNICO),
        _OTRO_TECNICO,
        False,
    ),
    ("usuario inactivo", _accion([RolUsuario.RECEPCION]), _INACTIVO, False),
    ("inactivo sin rol definido", _accion([]), _INACTIVO, False),
    (
        "liberar la de otro: no el titular",
        _accion([RolUsuario.TECNICO], usuario_excluido_id=TECNICO),
        _TECNICO,
        False,
    ),
    (
        "liberar la de otro: otro tecnico",
        _accion([RolUsuario.TECNICO], usuario_excluido_id=TECNICO),
        _OTRO_TECNICO,
        True,
    ),
]


@pytest.mark.parametrize(
    ("accion", "usuario", "esperado"),
    [caso[1:] for caso in CASOS_DE_PERMISO],
    ids=[caso[0] for caso in CASOS_DE_PERMISO],
)
def test_puede_ejecutar_como_valida_el_servidor(accion, usuario, esperado):
    assert puede_ejecutar(accion, usuario) is esperado


def test_un_usuario_inactivo_no_ve_como_suyo_lo_que_el_servidor_rechaza(
    tmp_path,
):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        catalogo = tmp_path / "catalogs" / "usuarios.json"
        usuarios = json.loads(catalogo.read_text("utf-8"))
        usuarios.append(
            {
                "id": "RECEP-009",
                "nombre": "Recepcion inactiva",
                "rol": "RECEPCION",
                "activo": False,
            }
        )
        catalogo.write_text(json.dumps(usuarios), "utf-8")
        orden_id = ok(
            cliente.post(
                "/api/orders",
                json={
                    "usuario_id": RECEPCION,
                    "cliente": {"nombre": "Ana", "telefono": "341-1"},
                    "equipo": {
                        "marca": "Apple",
                        "modelo": "iPhone 14",
                        "falla_reportada": "No carga.",
                    },
                    "recepcion": {"estado_fisico": "Sin golpes."},
                },
            )
        )["id"]

        activa = _bandejas(cliente, RECEPCION)
        inactiva = _bandejas(cliente, "RECEP-009")

        assert _ids(activa["DEFINICION"]) == [orden_id]
        assert not [
            codigo
            for codigo, bandeja in inactiva.items()
            if bandeja["tipo"] == "TAREAS" and bandeja["ordenes"]
        ]
        # El servidor lo rechaza igual.
        conflicto(
            cliente.post(
                f"/api/orders/{orden_id}/reception/confirm",
                json={"usuario_id": "RECEP-009"},
            )
        )


def test_lo_del_titular_no_se_ofrece_a_otro_tecnico(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = _en_cola(cliente, 2)
        tomar(cliente, orden_id, TECNICO)
        ejecucion = iniciar(cliente, orden_id)

        propia = _bandejas(cliente, TECNICO, "workshop")
        ajena = _bandejas(cliente, TECNICO_B, "workshop")

        assert _item(propia["MIS_TOMADAS"], orden_id)["puede_resolver"] is True
        assert _ids(ajena["MIS_TOMADAS"]) == []
        assert _item(ajena["EN_TALLER"], orden_id)["puede_resolver"] is False
        conflicto(
            cerrar_ejecucion(cliente, orden_id, ejecucion, tecnico=TECNICO_B),
            "TOMA_DE_OTRO_TECNICO",
        )


# --- Avisar al cliente e informar a Gestion RT --------------------------


def test_avisar_al_cliente_e_informar_a_gestion_rt_por_separado(tmp_path):
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        interna = _crear_orden_rt(cliente)
        agregar(cliente, interna)
        finalizar(cliente, interna, confirmar_recepcion=False)
        tomada(cliente, interna)
        ok(cerrar_ejecucion(cliente, interna, iniciar(cliente, interna)))
        ok(aprobar(cliente, interna, "DET-001"))
        externa = _reparada(cliente)
        ok(aprobar(cliente, externa, "DET-001"))

        bandejas = _bandejas(cliente, RECEPCION)

        assert _ids(bandejas["AVISO"]) == [externa]
        assert _ids(bandejas["INFORMAR_RT"]) == [interna]
        item = _item(bandejas["INFORMAR_RT"], interna)
        assert item["tarea"] == "Informar el resultado a Gestión RT"
        assert item["orden"]["origen"] == "RT_INTERNO"
        assert (
            _item(bandejas["AVISO"], externa)["tarea"] == "Avisar al cliente"
        )
        # Las bandejas de los demas roles no cambian.
        assert "INFORMAR_RT" not in _bandejas(cliente, TECNICO)


# --- Priorizar desde Recepcion ------------------------------------------


def test_recepcion_prioriza_desde_su_bandeja_una_sola_vez(tmp_path):
    """Una Orden habilitada fuera del ingreso inicial (revision con la
    autorizacion explicita del cliente) espera que la prioricen."""
    with _cliente(tmp_path, stock_bateria="5") as cliente:
        orden_id = definida(cliente, autorizar=False)
        autorizar_todo(cliente, orden_id)
        item = _item(_bandejas(cliente, RECEPCION)["PRIORIZAR"], orden_id)
        assert item["puede_resolver"] is True

        orden = ok(
            cliente.post(
                f"/api/orders/{orden_id}/queue",
                json={"usuario_id": RECEPCION, "prioridad": 2},
            )
        )

        assert orden["prioridad"] == 2
        for usuario in (RECEPCION, COORDINADOR):
            assert orden_id not in _ids(
                _bandejas(cliente, usuario)["PRIORIZAR"]
            )
        historial = [paso["referencia_id"] for paso in orden["historial"]]
        assert historial.count("PROC-REP-140") == 1
        assert historial.count("PROC-REP-150") == 1
        conflicto(
            cliente.post(
                f"/api/orders/{orden_id}/queue",
                json={"usuario_id": COORDINADOR, "prioridad": 1},
            )
        )
