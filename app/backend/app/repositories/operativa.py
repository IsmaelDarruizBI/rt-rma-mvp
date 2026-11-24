"""Contrato de la configuracion operativa: motivos y parametros
(DEC-MI-13, 14 y 15). En JSON es de solo lectura (los valores iniciales);
en PostgreSQL se administra con auditoria."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

from app.domain.models import (
    CambioConfiguracion,
    CategoriaInsumo,
    DatosEmpresa,
    FabricanteRepuesto,
    Insumo,
    TextoLegal,
)
from app.domain.models.checklist import PreguntaChecklist, TipoEquipo
from app.domain.models.comunicaciones import (
    ConsentimientoComunicacion,
    PlantillaMensaje,
)
from app.domain.models.firmas import FirmaDocumento
from app.domain.models.operativa import MotivoOperativo, TipoMotivo


class ConfiguracionOperativaRepository(Protocol):
    editable: bool

    def reservar_codigo(self, prefijo: str) -> str:
        """CFG-01: el codigo siguiente libre de ``prefijo`` (CANC, INT, INS,
        CHK, CAT, FAB) dentro de la transaccion del alta."""
        ...

    def listar_motivos(
        self, tipo: TipoMotivo | None = None
    ) -> list[MotivoOperativo]: ...

    def guardar_motivo(
        self,
        motivo: MotivoOperativo,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None: ...

    def parametros(self) -> dict[str, str]: ...

    def guardar_parametro(
        self, clave: str, valor: str, cambio: CambioConfiguracion
    ) -> None: ...

    # DEC-MI-13: alta y edicion de insumos (sin tocar el stock). DEC-AJ-14:
    # tambien su clasificacion y el conjunto de modelos compatibles, que
    # reemplaza al anterior en la misma transaccion.
    def guardar_insumo(
        self,
        insumo: Insumo,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None: ...

    # DEC-AJ-14: categorias (dos niveles) y fabricantes de repuestos. En
    # JSON, listas vacias y de solo lectura.
    def listar_categorias_insumo(self) -> list[CategoriaInsumo]: ...

    def guardar_categoria_insumo(
        self,
        categoria: CategoriaInsumo,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None: ...

    def listar_fabricantes_repuesto(self) -> list[FabricanteRepuesto]: ...

    def guardar_fabricante_repuesto(
        self,
        fabricante: FabricanteRepuesto,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None: ...

    # UX-08: recargo porcentual de un medio de pago, con su auditoria.
    def guardar_recargo_medio_pago(
        self, medio_id: str, porcentaje: Decimal, cambio: CambioConfiguracion
    ) -> None: ...

    # DEC-AJ-09: datos de la empresa (una sola fila) y versiones nuevas de
    # los textos legales (nunca se modifica una publicada), con auditoria.
    def guardar_datos_empresa(
        self,
        empresa: DatosEmpresa,
        cambios: Sequence[CambioConfiguracion],
    ) -> None: ...

    def publicar_texto_legal(
        self, texto: TextoLegal, cambio: CambioConfiguracion
    ) -> None:
        """Agrega la version (``CodigoExistenteError`` si ese numero ya
        existe: otra publicacion concurrente)."""
        ...

    # DC12: copia de los tipos de equipo del catalogo de Ventas y
    # preguntas del checklist.
    def listar_tipos_equipo(self) -> list[TipoEquipo]: ...

    def aplicar_tipos_equipo(
        self,
        tipos: Sequence[TipoEquipo],
        cambios: Sequence[CambioConfiguracion],
    ) -> None:
        """Alta o actualizacion de cada tipo (por su identificador de
        Ventas) y su auditoria, en la transaccion del comando."""
        ...

    def listar_preguntas_checklist(self) -> list[PreguntaChecklist]: ...

    def guardar_pregunta_checklist(
        self,
        pregunta: PreguntaChecklist,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None: ...

    # DEC-MI-08: plantillas de WhatsApp.
    def listar_plantillas(self) -> list[PlantillaMensaje]: ...

    def guardar_plantilla(
        self,
        plantilla: PlantillaMensaje,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None: ...


class ConsentimientosRepository(Protocol):
    """Historial de consentimiento por cliente (DEC-MI-08): solo crece."""

    def listar(self, cliente_id: str) -> list[ConsentimientoComunicacion]: ...

    def agregar(self, registro: ConsentimientoComunicacion) -> None: ...


class FirmasRepository(Protocol):
    """Firmas de documentos emitidos (DEC-MI-06): solo crecen."""

    def de_la_orden(self, orden_id: str) -> list[FirmaDocumento]: ...

    def agregar(self, firma: FirmaDocumento) -> None: ...
