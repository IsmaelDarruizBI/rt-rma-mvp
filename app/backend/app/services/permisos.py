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
nunca: gestionar roles y permisos y administrar la configuracion del
sistema son de Administracion, para que ningun cambio deje el sistema sin
quien lo administre.

Configuracion v2 (CFG-03): los catalogos operativos (tipos de reparacion,
precios, Mesas, motivos, insumos, plantillas, checklist, proveedores) tienen
permisos propios y configurables, inicialmente solo de Administracion (D2);
Compras se divide por accion y hereda los roles de ``COMPRAS_GESTIONAR``
(DF-4). Un permiso puede ``requerir`` otro (su consulta): la configuracion
no deja a un rol con la accion y sin lo que necesita para verla.
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
        "requiere",
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
        requiere: tuple[str, ...] = (),
    ) -> None:
        self.codigo = codigo
        self.descripcion = descripcion
        self.grupo = grupo
        self.predeterminados = tuple(predeterminados)
        self.configurable = configurable
        self.consulta = consulta
        self.requiere = tuple(requiere)

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
    requiere: tuple[str, ...] = (),
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
        requiere=requiere,
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
# DEC-MI-11: corregir una vinculacion erronea con un Equipo.
EQUIPO_VINCULO_CORREGIR = _definir(
    "EQUIPO_VINCULO_CORREGIR",
    "Corregir la vinculación de una Orden con un Equipo",
    (RECEP, COORD, ADMIN),
    INGRESO,
)
# DC12: checklist de recepcion y advertencia por informacion faltante;
# por defecto, quienes corrigen los datos del ingreso.
CHECKLIST_REGISTRAR = _definir(
    "CHECKLIST_REGISTRAR",
    "Registrar el checklist de recepción",
    (RECEP, COORD, ADMIN),
    INGRESO,
)
DETALLE_DEFINIR_RECEPCION = _definir(
    "DETALLE_DEFINIR_RECEPCION",
    "Cargar y finalizar los trabajos en el ingreso",
    (RECEP,),
    INGRESO,
)
ENVIAR_A_REVISION = _definir(
    "ENVIAR_A_REVISION",
    "Enviar a revisión técnica y finalizar la revisión sin reparación",
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
# DEC-MI-08: no fija los roles; por defecto, los de atencion al cliente.
COMUNICACION_ENVIAR = _definir(
    "COMUNICACION_ENVIAR",
    "Preparar y registrar mensajes de WhatsApp al cliente",
    (RECEP, COORD, ADMIN),
    CLIENTE,
)
# DEC-MI-06: no fija los roles; por defecto, los de atencion al cliente.
FIRMA_REGISTRAR = _definir(
    "FIRMA_REGISTRAR",
    "Registrar la firma de un documento",
    (RECEP, COORD, ADMIN),
    CLIENTE,
)
CONSENTIMIENTO_REGISTRAR = _definir(
    "CONSENTIMIENTO_REGISTRAR",
    "Registrar o revocar consentimientos de comunicación",
    (RECEP, COORD, ADMIN),
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
# DEC-AJ-14 (D-14.4, precision b; BR-REP-039): elegir o sustituir la pieza
# concreta de un requisito del trabajo, antes de reservar o, ya reservada,
# antes de consumirla. Inicialmente Tecnico, Coordinacion RMA y
# Administracion (quien prepara el trabajo).
PIEZA_ELEGIR = _definir(
    "PIEZA_ELEGIR",
    "Elegir o sustituir la pieza concreta de un trabajo",
    (TECH, COORD, ADMIN),
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
# DEC-AJ-10 (D-10.2): revertir o corregir un ajuste comercial equivocado;
# inicialmente solo Administracion, como la anulacion de pagos.
AJUSTE_REVERTIR = _definir(
    "AJUSTE_REVERTIR",
    "Revertir o corregir un ajuste comercial",
    (ADMIN,),
    COMERCIAL,
)
# DEC-AJ-12 (D-12.2, precision a): precio manual de un trabajo cuyo Tipo
# tiene precio por modelo y no tiene precio para el modelo de la Orden (o el
# equipo no tiene modelo tecnico). Nunca cambia el catalogo. Inicialmente
# Coordinacion RMA y Administracion; el Tecnico no fija precios.
PRECIO_MANUAL = _definir(
    "PRECIO_MANUAL",
    "Autorizar un precio manual cuando falta el precio de catálogo",
    (COORD, ADMIN),
    COMERCIAL,
)

# --- Salida ---
SALIDA = "Custodia, check-in y entrega"
CUSTODIA = _definir(
    "CUSTODIA",
    "Recepción física, equipo no recibido y notas de la recepción",
    (RECEP, ADMIN),
    SALIDA,
)
CHECKIN = _definir("CHECKIN", "Registrar el check-in", (ADMIN, RECEP), SALIDA)
GARANTIA_AJUSTAR = _definir(
    "GARANTIA_AJUSTAR", "Ajustar el plazo de garantía", (RECEP, COORD), SALIDA
)
RETIRO_SEGUIMIENTO = _definir(
    "RETIRO_SEGUIMIENTO",
    "Registrar seguimientos de un retiro demorado",
    (RECEP, ADMIN),
    SALIDA,
)
ENTREGA = _definir(
    "ENTREGA",
    "Entregar el equipo, devolverlo sin reparar o a RT",
    (ADMIN, RECEP),
    SALIDA,
)

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
# DEC-MI-10: devolver al stock lo consumido; por defecto, quienes
# gestionan el stock (no se concede acceso nuevo).
DEVOLUCION_STOCK = _definir(
    "DEVOLUCION_STOCK",
    "Devolver al stock un insumo consumido",
    (ADMIN, COORD),
    INVENTARIO,
)
CATALOGO_EQUIPOS_SINCRONIZAR = _definir(
    "CATALOGO_EQUIPOS_SINCRONIZAR",
    "Sincronizar el catálogo de equipos de Ventas",
    (ADMIN, COORD),
    INVENTARIO,
)
# Reparacion RT (DEC-RT-05): a pedido, inicialmente solo Administracion.
PRODUCTOS_RT_SINCRONIZAR = _definir(
    "PRODUCTOS_RT_SINCRONIZAR",
    "Sincronizar los Productos de Gestión RT en reparación",
    (ADMIN,),
    INVENTARIO,
)

# --- Compras (CFG-03, D5; DEC-MI-09) ---
# Antes un solo permiso, COMPRAS_GESTIONAR. Cada accion hereda sus roles
# (DF-4: nadie pierde acceso; la migracion copia lo configurado).
COMPRAS = "Compras"
ROLES_COMPRAS = (RECEP, COORD, ADMIN)
COMPRA_SOLICITAR = _definir(
    "COMPRA_SOLICITAR",
    "Crear y descartar solicitudes de compra",
    ROLES_COMPRAS,
    COMPRAS,
    requiere=("COMPRAS_CONSULTAR",),
)
OC_CREAR = _definir(
    "OC_CREAR",
    "Crear órdenes de compra (y descartar el borrador propio)",
    ROLES_COMPRAS,
    COMPRAS,
    requiere=("COMPRAS_CONSULTAR",),
)
OC_CONFIRMAR = _definir(
    "OC_CONFIRMAR",
    "Confirmar órdenes de compra",
    ROLES_COMPRAS,
    COMPRAS,
    requiere=("COMPRAS_CONSULTAR",),
)
# DF-5: cancelar una OC confirmada (y cualquier borrador).
OC_CANCELAR = _definir(
    "OC_CANCELAR",
    "Cancelar órdenes de compra confirmadas o borradores ajenos",
    ROLES_COMPRAS,
    COMPRAS,
    requiere=("COMPRAS_CONSULTAR",),
)
COMPRA_RECIBIR = _definir(
    "COMPRA_RECIBIR",
    "Registrar recepciones de compra (ingresan stock)",
    ROLES_COMPRAS,
    COMPRAS,
    requiere=("COMPRAS_CONSULTAR",),
)
PROVEEDOR_GESTIONAR = _definir(
    "PROVEEDOR_GESTIONAR",
    "Dar de alta y editar proveedores",
    (ADMIN,),
    COMPRAS,
    requiere=("COMPRAS_CONSULTAR",),
)

# Alias de lectura para el frontend publicado antes de CFG-03: lo informa
# ``permisos_de`` a quien puede crear OC. No es un permiso: no se configura
# ni habilita nada en el backend.
ALIAS_COMPRAS_GESTIONAR = "COMPRAS_GESTIONAR"

# --- Configuracion operativa (CFG-03, D2 y D3) ---
# Antes, CONFIGURACION_ADMINISTRAR (fijo). Configurables y, al inicio, solo
# de Administracion: nadie gana acceso sin que Administracion lo decida.
OPERATIVA = "Configuración operativa"
TIPO_REPARACION_GESTIONAR = _definir(
    "TIPO_REPARACION_GESTIONAR",
    "Tipos de reparación: alta, nombre, puntaje, garantías y vigencia",
    (ADMIN,),
    OPERATIVA,
)
PRECIOS_GESTIONAR = _definir(
    "PRECIOS_GESTIONAR",
    "Precios de los tipos de reparación y de los insumos",
    (ADMIN,),
    OPERATIVA,
)
MESA_TIPOS_GESTIONAR = _definir(
    "MESA_TIPOS_GESTIONAR",
    "Tipos de reparación habilitados en cada Mesa de trabajo",
    (ADMIN,),
    OPERATIVA,
)
MOTIVO_GESTIONAR = _definir(
    "MOTIVO_GESTIONAR",
    "Motivos de cancelación e interrupción",
    (ADMIN,),
    OPERATIVA,
)
INSUMO_GESTIONAR = _definir(
    "INSUMO_GESTIONAR",
    "Insumos: alta, nombre, unidad, control por lote, vigencia y stock mínimo",
    (ADMIN,),
    OPERATIVA,
    requiere=("INVENTARIO_CONSULTAR",),
)
PLANTILLA_GESTIONAR = _definir(
    "PLANTILLA_GESTIONAR",
    "Plantillas de WhatsApp",
    (ADMIN,),
    OPERATIVA,
)
CHECKLIST_GESTIONAR = _definir(
    "CHECKLIST_GESTIONAR",
    "Checklist de recepción y tipos de equipo",
    (ADMIN,),
    OPERATIVA,
)
# DEC-AJ-12 (D-12.5): alta y edicion del catalogo tecnico de modelos.
MODELO_EQUIPO_GESTIONAR = _definir(
    "MODELO_EQUIPO_GESTIONAR",
    "Gestionar modelos de equipo",
    (ADMIN,),
    OPERATIVA,
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
# DC27B: consultas configurables; por defecto, todos los roles (como hoy).
ORDENES_CONSULTAR = _definir(
    "ORDENES_CONSULTAR",
    "Consultar las Órdenes y sus documentos",
    TODOS,
    CONSULTAS,
    consulta=True,
)
INVENTARIO_CONSULTAR = _definir(
    "INVENTARIO_CONSULTAR",
    "Consultar el inventario, sus movimientos y lotes",
    TODOS,
    CONSULTAS,
    consulta=True,
)
COMPRAS_CONSULTAR = _definir(
    "COMPRAS_CONSULTAR",
    "Consultar compras, proveedores y costos",
    (RECEP, COORD, ADMIN),
    COMPRAS,
    consulta=True,
)
# Reparacion RT (DEC-RT-07).
PRODUCTOS_RT_CONSULTAR = _definir(
    "PRODUCTOS_RT_CONSULTAR",
    "Consultar los Productos de Gestión RT en reparación",
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
# BF-07 (D-01, 23/11/2026): qué muestra el detalle de la Orden. Sin este
# permiso, la pantalla oculta antecedentes, ejecuciones, movimientos y
# devoluciones de insumos, insumos previstos y los bloques técnicos del
# historial. Es PRESENTACIÓN: la API sigue devolviendo esos datos a quien
# consulta la Orden (ORDENES_CONSULTAR) y ningún endpoint lo exige; no es un
# control de seguridad. Sin fila en rma.permiso rige este predeterminado.
DETALLE_TECNICO_CONSULTAR = _definir(
    "DETALLE_TECNICO_CONSULTAR",
    "Consultar la información técnica de la Orden",
    (TECH, COORD, ADMIN),
    CONSULTAS,
    consulta=True,
)

# Permisos que solo decide la pantalla (llegan con la sesión, en
# ``/api/me``): ningún endpoint los exige. La prueba de permisos sin uso
# los busca en el frontend en lugar del backend.
SOLO_PRESENTACION = frozenset({DETALLE_TECNICO_CONSULTAR.codigo})

# --- Administracion (no configurables) ---
ADMINISTRACION = "Administración"
# CFG-03: queda para lo sensible del sistema; los catalogos operativos
# tienen sus permisos (grupo "Configuracion operativa").
CONFIGURACION_ADMINISTRAR = _definir(
    "CONFIGURACION_ADMINISTRAR",
    "Parámetros del sistema, recargos por medio de pago, datos de la "
    "empresa, términos y condiciones y auditoría",
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


def requeridos_por(codigo: str) -> list[Permiso]:
    """Los permisos que requieren ``codigo`` (sus acciones dependen de el)."""
    return [p for p in REGISTRO.values() if codigo in p.requiere]


for _permiso in REGISTRO.values():
    for _requerido in _permiso.requiere:
        if _requerido not in REGISTRO:
            raise ValueError(
                f"{_permiso.codigo} requiere un permiso inexistente: "
                f"{_requerido}"
            )


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
