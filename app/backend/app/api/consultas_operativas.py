"""Consultas de solo lectura: antecedentes del Equipo y reportes operativos.

    GET /api/equipment/history?imei=...&numero_serie=...&excluir_orden_id=...
    GET /api/reports/operational

No modifican nada. Como el resto de las consultas, para cualquier usuario
autenticado (DC27B, permisos de consulta configurables, sigue pendiente).
"""

from dataclasses import asdict

from fastapi import APIRouter

from app.application.consultas_operativas import (
    antecedentes_del_equipo,
    reporte_operativo,
)

from .dependencias import ContextoDep

router = APIRouter(tags=["consultas operativas"])


@router.get("/api/equipment/history")
def get_antecedentes_equipo(
    contexto: ContextoDep,
    imei: str | None = None,
    numero_serie: str | None = None,
    excluir_orden_id: str | None = None,
) -> dict:
    """Ordenes anteriores del Equipo por IMEI o numero de serie (BR-REP-022).

    Solo consulta: no confirma que sea el mismo Equipo fisico (ABI-05).
    """
    antecedentes = antecedentes_del_equipo(
        contexto,
        imei=imei,
        numero_serie=numero_serie,
        excluir_orden_id=excluir_orden_id,
    )
    return asdict(antecedentes)


@router.get("/api/reports/operational")
def get_reporte_operativo(contexto: ContextoDep) -> dict:
    """Reporte operativo, primera version (solo metricas del modelo)."""
    return asdict(reporte_operativo(contexto))
