"""Permisos configurables por accion (DC08, DC27A, DC27B; DEC-MI-12).

Cada accion del proceso -un nodo con actor o una capacidad transversal- se
habilita con un ``Permiso``. Sus roles predeterminados son los que el
producto ya validaba (los responsables declarados en el proceso y los
predeterminados aprobados): esa es la configuracion inicial. Administracion
puede cambiarlos desde Configuracion (con auditoria); el cambio se guarda
en PostgreSQL y rige desde el pedido siguiente.

Un permiso es necesario pero no suficiente: cada caso de uso sigue
validando sus restricciones de contexto (el titular de la toma, el tecnico
de la Ejecucion en curso, el estado de la Orden...). Un usuario con varios
roles tiene la union de sus permisos (DC27A).

``Permiso`` se comporta como la tupla de roles que lo habilitan *ahora*
(iterable, ``in``, ``len``, igualdad con una tupla): por eso las
constantes ``ROLES_*`` de los services son permisos y sus usos existentes
(``validar_alguno_de(usuario, ROLES_PAGO)``, ``AccionDisponible(roles=...)``)
quedan configurables sin cambiar.

La politica vigente la fija la capa de API para cada pedido
(``politica_vigente``); sin politica (pruebas, scripts, modo JSON) rigen
los predeterminados. Los permisos ``configurable=False`` no se cambian
nunca: gestionar roles y permisos y administrar la configuracion son de
Administracion, para que ningun cambio deje el sistema sin quien lo
administre.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar

from app.domain.models import RolUsuario

ADMIN = RolUsuario.ADMINISTRADOR
RECEP = RolUsuario.RECEPCION
COORD = RolUsuario.COORDINADOR_RMA
TECH = RolUsuario.TECNICO
TODOS = (ADMIN, RECEP, COORD, TECH)

Politica = Mapping[str, tuple[RolUsuario, ...]]


class Permiso:
    """Una accion habilitable por rol."""

    __slots__ = (
        "codigo",
        "descripcion",
        "grupo",
        "predeterminados",
        "configurable",
        "consulta",
    )

    def __init__(
        self,
        codigo: str,
        descripcion: str,
        predeterminados: tuple[RolUsuario, ...],
        *,
        grupo: str,
        configurable: bool = True,
        consulta: bool = False,
    ) -> None:
        self.codigo = codigo
        self.descripcion = descripcion
        self.grupo = grupo
        self.predeterminados = tuple(predeterminados)
        self.configurable = configurable
        self.consulta = consulta

    @property
    def roles(self) -> tuple[RolUsuario, ...]:
        """Los roles que lo habilitan con la politica vigente."""
        if not self.configurable:
            return self.predeterminados
        proveedor = _POLITICA.get()
        if proveedor is None:
            return self.predeterminados
        return tuple(proveedor().get(self.codigo, self.predeterminados))

    def __iter__(self) -> Iterator[RolUsuario]:
        return iter(self.roles)

    def __contains__(self, rol: object) -> bool:
        return rol in self.roles

    def __len__(self) -> int:
        return len(self.roles)

    def __bool__(self) -> bool:
        return True

    def __eq__(self, otro: object) -> bool:
        if isinstance(otro, Permiso):
            return self.codigo == otro.codigo
        if isinstance(otro, (tuple, list)):
            return self.roles == tuple(otro)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.codigo)

    def __repr__(self) -> str:
        return (
            f"Permiso({self.codigo}: {', '.join(r.value for r in self.roles)})"
        )


REGISTRO: dict[str, Permiso] = {}


def _definir(
    codigo: str,
    descripcion: str,
    roles: tuple[RolUsuario, ...],
    grupo: str,
    *,
    configurable: bool = True,
    consulta: bool = False,
) -> Permiso:
    if codigo in REGISTRO:
        raise ValueError(f"Permiso duplicado: {codigo}")
    permiso = Permiso(
        codigo,
        descripcion,
        roles,
        grupo=grupo,
        configurable=configurable,
        consulta=consulta,
    )
    REGISTRO[codigo] = permiso
    return permiso


# --- Ingreso y definicion ---
INGRESO = "Ingreso y definición"
ORDEN_CREAR = _definir(
    "ORDEN_CREAR",
    "Crear Órdenes (cliente externo y RT interno)",
    (RECEP,),
    INGRESO,
)
GARANTIA_RMA_CREAR = _definir(
    "GARANTIA_RMA_CREAR",
    "Ingresar un reclamo de garantía RMA",
    (RECEP,),
    INGRESO,
)
GARANTIA_EXCEPCION = _definir(
    "GARANTIA_EXCEPCION",
    "Autorizar la excepción de una garantía vencida",
    (RECEP, COORD, ADMIN),
    INGRESO,
)
INGRESO_CORREGIR = _definir(
    "INGRESO_CORREGIR",
    "Corregir datos del ingreso ya registrados (con motivo)",
    (RECEP, COORD, ADMIN),
    INGRESO,
)
RECLAMO_CONTINUAR = _definir(
    "RECLAMO_CONTINUAR",
    "Continuar un reclamo de garantía rechazado como reparación paga",
    (RECEP,),
    INGRESO,
)
CLIENTE_BUSCAR = _definir(
    "CLIENTE_BUSCAR",
    "Buscar clientes por DNI",
    (RECEP, ADMIN),
    INGRESO,
    consulta=True,
)
DETALLE_DEFINIR_RECEPCION = _definir(
    "DETALLE_DEFINIR_RECEPCION",
    "Cargar y finalizar los trabajos en el ingreso",
    (RECEP,),
    INGRESO,
)
ENVIAR_A_REVISION = _definir(
    "ENVIAR_A_REVISION",
    "Enviar a revisión técnica y finalizar sin reparación",
    (RECEP,),
    INGRESO,
)
COMPROBANTE_AUTORIZACION = _definir(
    "COMPROBANTE_AUTORIZACION",
    "Emitir el comprobante de autorización",
    (RECEP,),
    INGRESO,
)
FOTOS_CARGAR = _definir(
    "FOTOS_CARGAR",
    "Cargar fotografías del equipo",
    (RECEP, TECH, COORD, ADMIN),
    INGRESO,
)
FOTOS_ADMINISTRAR = _definir(
    "FOTOS_ADMINISTRAR",
    "Limpiar imágenes sin Orden (mantenimiento)",
    (ADMIN,),
    INGRESO,
)

# --- Cliente ---
CLIENTE = "Cliente y comunicación"
DECISION_CLIENTE = _definir(
    "DECISION_CLIENTE",
    "Registrar las decisiones y el desistimiento del cliente",
    (RECEP,),
    CLIENTE,
)
CLIENTE_NOTIFICAR = _definir(
    "CLIENTE_NOTIFICAR",
    "Avisar al cliente que el equipo está listo",
    (RECEP,),
    CLIENTE,
)

# --- Taller ---
TALLER = "Taller"
PRIORIDAD_DEFINIR = _definir(
    "PRIORIDAD_DEFINIR",
    "Ingresar a la cola con prioridad",
    (COORD, RECEP),
    TALLER,
)
PRIORIDAD_CAMBIAR = _definir(
    "PRIORIDAD_CAMBIAR", "Cambiar la prioridad", (TECH, COORD, RECEP), TALLER
)
ORDEN_TOMAR = _definir(
    "ORDEN_TOMAR",
    "Tomar, elegir trabajo y liberar la Orden propia",
    (TECH,),
    TALLER,
)
LIBERACION_AJENA = _definir(
    "LIBERACION_AJENA",
    "Liberar una Orden tomada por otro técnico",
    (TECH, COORD),
    TALLER,
)
REVISION_TECNICA = _definir(
    "REVISION_TECNICA", "Registrar la revisión técnica", (TECH,), TALLER
)
DETALLE_DEFINIR_TECNICO = _definir(
    "DETALLE_DEFINIR_TECNICO",
    "Definir y redefinir trabajos desde el diagnóstico técnico",
    (TECH,),
    TALLER,
)
EVALUACION_TECNICA = _definir(
    "EVALUACION_TECNICA",
    "Evaluar el trabajo antes de la primera Ejecución",
    (TECH,),
    TALLER,
)
DETALLE_ADICIONAL = _definir(
    "DETALLE_ADICIONAL", "Registrar reparaciones adicionales", (TECH,), TALLER
)
EJECUCION = _definir(
    "EJECUCION",
    "Iniciar, completar e interrumpir Ejecuciones",
    (TECH,),
    TALLER,
)
CONTROL_TECNICO = _definir(
    "CONTROL_TECNICO",
    "Aprobar o rechazar el control técnico",
    (RECEP,),
    TALLER,
)
RECURSOS_OVERRIDE = _definir(
    "RECURSOS_OVERRIDE",
    "Override de recursos y de Mesa de trabajo",
    (RECEP, TECH, COORD, ADMIN),
    TALLER,
)
CANCELACION = _definir(
    "CANCELACION",
    "Cancelar trabajos y Órdenes (cancelación administrativa)",
    (RECEP, COORD),
    TALLER,
)

# --- Comercial ---
COMERCIAL = "Comercial"
PAGO_REGISTRAR = _definir(
    "PAGO_REGISTRAR", "Registrar pagos", (ADMIN, RECEP, COORD), COMERCIAL
)
PAGO_ANULAR = _definir("PAGO_ANULAR", "Anular pagos", (ADMIN,), COMERCIAL)
DEVOLUCION_DINERO = _definir(
    "DEVOLUCION_DINERO",
    "Registrar devoluciones de dinero",
    (ADMIN, RECEP),
    COMERCIAL,
)
DESCUENTO = _definir(
    "DESCUENTO",
    "Otorgar, modificar o quitar descuentos",
    (RECEP, COORD, ADMIN),
    COMERCIAL,
)
CORTESIA = _definir(
    "CORTESIA",
    "Otorgar, modificar o quitar cortesías",
    (RECEP, COORD, ADMIN),
    COMERCIAL,
)

# --- Salida ---
SALIDA = "Custodia, check-in y entrega"
CUSTODIA = _definir(
    "CUSTODIA",
    "Recepción física, no recibido y devolución sin reparar",
    (RECEP, ADMIN),
    SALIDA,
)
CHECKIN = _definir("CHECKIN", "Registrar el check-in", (ADMIN, RECEP), SALIDA)
GARANTIA_AJUSTAR = _definir(
    "GARANTIA_AJUSTAR", "Ajustar el plazo de garantía", (RECEP, COORD), SALIDA
)
ENTREGA = _definir("ENTREGA", "Entregar el equipo", (ADMIN, RECEP), SALIDA)

# --- Inventario y catalogos ---
INVENTARIO = "Inventario y catálogos"
STOCK_GESTIONAR = _definir(
    "STOCK_GESTIONAR",
    "Ingresos y ajustes de stock",
    (ADMIN, COORD),
    INVENTARIO,
)
RECURSOS_REVALIDAR = _definir(
    "RECURSOS_REVALIDAR",
    "Revalidar recursos de las Órdenes",
    (ADMIN, COORD),
    INVENTARIO,
)
CATALOGO_EQUIPOS_SINCRONIZAR = _definir(
    "CATALOGO_EQUIPOS_SINCRONIZAR",
    "Sincronizar el catálogo de equipos de Ventas",
    (ADMIN, COORD),
    INVENTARIO,
)

# --- Consultas (DC27B) ---
CONSULTAS = "Consultas"
REPORTES_CONSULTAR = _definir(
    "REPORTES_CONSULTAR",
    "Consultar los reportes",
    TODOS,
    CONSULTAS,
    consulta=True,
)
RECLAMOS_CONSULTAR = _definir(
    "RECLAMOS_CONSULTAR",
    "Consultar los reclamos de garantía rechazados",
    (RECEP, COORD, ADMIN),
    CONSULTAS,
    consulta=True,
)
ANTECEDENTES_CONSULTAR = _definir(
    "ANTECEDENTES_CONSULTAR",
    "Consultar los antecedentes del equipo",
    TODOS,
    CONSULTAS,
    consulta=True,
)

# --- Administracion (no configurables) ---
ADMINISTRACION = "Administración"
CONFIGURACION_ADMINISTRAR = _definir(
    "CONFIGURACION_ADMINISTRAR",
    "Administrar catálogos y configuración",
    (ADMIN,),
    ADMINISTRACION,
    configurable=False,
)
ROLES_ADMINISTRAR = _definir(
    "ROLES_ADMINISTRAR",
    "Asignar roles y configurar permisos",
    (ADMIN,),
    ADMINISTRACION,
    configurable=False,
)


def configurables() -> list[Permiso]:
    return [p for p in REGISTRO.values() if p.configurable]


# --- Politica vigente del pedido ---

_POLITICA: ContextVar[Callable[[], Politica] | None] = ContextVar(
    "politica_permisos", default=None
)


@contextmanager
def politica_vigente(cargar: Callable[[], Politica]):
    """Rige ``cargar()`` (leida una sola vez, al primer uso) en este flujo."""
    memoria: list[Politica] = []

    def proveedor() -> Politica:
        if not memoria:
            memoria.append(cargar())
        return memoria[0]

    token = _POLITICA.set(proveedor)
    try:
        yield
    finally:
        _POLITICA.reset(token)


def fijar_politica(cargar: Callable[[], Politica]):
    """Como ``politica_vigente``, para un pedido entero: devuelve el token
    que ``restablecer_politica`` usa al terminar."""
    memoria: list[Politica] = []

    def proveedor() -> Politica:
        if not memoria:
            memoria.append(cargar())
        return memoria[0]

    return _POLITICA.set(proveedor)


def restablecer_politica(token) -> None:
    _POLITICA.reset(token)


# --- Rol habilitante ---

_ROL_HABILITANTE: ContextVar[tuple[str, RolUsuario] | None] = ContextVar(
    "rol_habilitante", default=None
)


def anotar_rol_habilitante(usuario_id: str, rol: RolUsuario | None) -> None:
    """El rol con el que ``usuario_id`` quedo habilitado en esta accion."""
    _ROL_HABILITANTE.set((usuario_id, rol) if rol is not None else None)


def rol_habilitante(usuario_id: str | None) -> RolUsuario | None:
    actual = _ROL_HABILITANTE.get()
    if actual is None or usuario_id is None or actual[0] != usuario_id:
        return None
    return actual[1]
