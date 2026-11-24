"""Configuracion operativa en el modo JSON: los valores iniciales, de solo
lectura (como los demas catalogos administrables, DC23)."""

from app.domain.models.comunicaciones import PLANTILLAS_INICIALES
from app.domain.models.operativa import (
    MOTIVOS_INICIALES,
    PARAMETROS_INICIALES,
    MotivoOperativo,
    TipoMotivo,
)


class JsonConfiguracionOperativa:
    editable = False

    def reservar_codigo(self, prefijo: str) -> str:
        raise NotImplementedError

    def listar_motivos(
        self, tipo: TipoMotivo | None = None
    ) -> list[MotivoOperativo]:
        return [m for m in MOTIVOS_INICIALES if tipo is None or m.tipo is tipo]

    def guardar_motivo(self, motivo, *, nuevo, cambios) -> None:
        raise NotImplementedError

    def parametros(self) -> dict[str, str]:
        return dict(PARAMETROS_INICIALES)

    def guardar_parametro(self, clave, valor, cambio) -> None:
        raise NotImplementedError

    def listar_plantillas(self):
        return list(PLANTILLAS_INICIALES)

    def guardar_plantilla(self, plantilla, *, nuevo, cambios) -> None:
        raise NotImplementedError

    def guardar_insumo(self, insumo, *, nuevo, cambios) -> None:
        raise NotImplementedError

    # DEC-AJ-14: sin clasificacion en el modo JSON (los insumos quedan sin
    # clasificar y universales).
    def listar_categorias_insumo(self):
        return []

    def guardar_categoria_insumo(self, categoria, *, nuevo, cambios) -> None:
        raise NotImplementedError

    def listar_fabricantes_repuesto(self):
        return []

    def guardar_fabricante_repuesto(self, fabricante, *, nuevo, cambios):
        raise NotImplementedError

    def guardar_recargo_medio_pago(self, medio_id, porcentaje, cambio) -> None:
        raise NotImplementedError

    def guardar_datos_empresa(self, empresa, cambios) -> None:
        raise NotImplementedError

    def publicar_texto_legal(self, texto, cambio) -> None:
        raise NotImplementedError

    # DC12: en la demo JSON el catalogo del checklist esta vacio.
    def listar_tipos_equipo(self):
        return []

    def aplicar_tipos_equipo(self, tipos, cambios) -> None:
        raise NotImplementedError

    def listar_preguntas_checklist(self):
        return []

    def guardar_pregunta_checklist(self, pregunta, *, nuevo, cambios) -> None:
        raise NotImplementedError
