"""Contrato de la administracion de catalogos (DC23, DC23AUD).

Cada escritura guarda el catalogo y su auditoria en la misma transaccion
(diseno logico V1.4, seccion 4). Solo la implementa PostgreSQL: DC23 pide
la administracion sobre la persistencia definitiva, no sobre los JSON.
"""

from collections.abc import Collection, Sequence
from typing import Protocol

from app.domain.models import (
    CambioConfiguracion,
    EntidadConfiguracion,
    ImportacionPrecios,
    ModeloEquipo,
    PrecioTipoModelo,
    RolUsuario,
    TipoReparacion,
)


class ConfiguracionRepository(Protocol):
    def reservar_codigo(self, prefijo: str) -> str:
        """El codigo siguiente libre de ``prefijo`` (CFG-01), dentro de la
        transaccion del alta."""
        ...

    def guardar_tipo_reparacion(
        self,
        tipo: TipoReparacion,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None:
        """Alta o edicion del Tipo, con sus cambios auditados."""
        ...

    def guardar_modelo_equipo(
        self,
        modelo: ModeloEquipo,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None:
        """Alta o edicion de un modelo de equipo (DEC-AJ-12, D-12.5), con
        sus cambios auditados. ``CodigoExistenteError`` si ya existe el
        codigo o la misma marca, modelo y variante."""
        ...

    def guardar_precios_modelo(
        self,
        precios: Sequence[PrecioTipoModelo],
        cambios: Sequence[CambioConfiguracion],
    ) -> None:
        """Fija o retira (``precio`` None) precios por modelo en bloque, con
        su auditoria, en la transaccion en curso: todo o nada (DEC-AJ-12;
        la importacion masiva de DEC-AJ-13 usa esta misma escritura)."""
        ...

    def registrar_importacion_precios(
        self, importacion: ImportacionPrecios
    ) -> None:
        """Registra una importacion masiva de precios por modelo
        (DEC-AJ-13) en la transaccion en curso, antes que sus cambios: la
        auditoria de cada uno la referencia."""
        ...

    def guardar_tipos_de_mesa(
        self,
        estacion_id: str,
        tipo_ids: Collection[str],
        cambio: CambioConfiguracion,
    ) -> None:
        """Reemplaza los Tipos habilitados de la Mesa, con su auditoria."""
        ...

    def guardar_roles_de_usuario(
        self,
        usuario_id: str,
        roles: Sequence[RolUsuario],
        cambio: CambioConfiguracion,
    ) -> None:
        """Reemplaza los roles del usuario, con su auditoria (DC27A)."""
        ...

    def guardar_permiso(
        self,
        codigo: str,
        roles: Sequence[RolUsuario],
        cambio: CambioConfiguracion,
    ) -> None:
        """Fija los roles de un permiso configurable, con su auditoria."""
        ...

    def leer_permisos(self) -> dict[str, tuple[RolUsuario, ...]]:
        """Los permisos configurados (sin fila rige el predeterminado)."""
        ...

    def listar_cambios(
        self,
        *,
        entidad: EntidadConfiguracion | None = None,
        clave: str | None = None,
    ) -> list[CambioConfiguracion]:
        """La auditoria, de la mas vieja a la mas nueva."""
        ...
