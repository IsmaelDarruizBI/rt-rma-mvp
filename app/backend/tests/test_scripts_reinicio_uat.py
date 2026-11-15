"""Scripts de reinicio y limpieza del UAT: seguros por defecto y coherentes.

``01_reiniciar.sql`` (reinicio completo) y ``06_limpiar_e2e.sql`` (limpieza
selectiva del E2E) clasifican las tablas de ``rma`` con las mismas listas: si
una migración agrega una tabla, las dos se actualizan juntas. La cobertura de
esas listas sobre el esquema completo está en
``tests/postgres/test_reinicio_clasificacion.py``.
"""

import re
from pathlib import Path

REINICIO = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "scripts"
    / "reinicio_uat"
)


def _texto(nombre: str) -> str:
    return (REINICIO / nombre).read_text(encoding="utf-8")


def lista(texto: str, nombre: str) -> list[str]:
    """Los elementos de ``<nombre> constant text[] := array[...]``."""
    m = re.search(
        rf"{nombre} constant text\[\] := array\[(.*?)\];", texto, re.S
    )
    assert m, nombre
    sin_comentarios = re.sub(r"--[^\n]*", "", m.group(1))
    return sorted(re.findall(r"'([a-z_]+)'", sin_comentarios))


def test_la_limpieza_y_el_reinicio_clasifican_igual():
    reinicio, limpieza = (
        _texto("01_reiniciar.sql"),
        _texto("06_limpiar_e2e.sql"),
    )
    for nombre in ("c_operativas", "c_maestras"):
        assert lista(limpieza, nombre) == lista(reinicio, nombre), nombre
    assert not set(lista(reinicio, "c_operativas")) & set(
        lista(reinicio, "c_maestras")
    )


def test_los_scripts_que_escriben_vienen_en_modo_seguro():
    assert "v_modo constant text := 'ensayo';" in _texto("01_reiniciar.sql")
    assert "v_modo constant text := 'ensayo';" in _texto("06_limpiar_e2e.sql")
    assert "v_confirmar constant boolean := false;" in _texto(
        "04_eliminar_respaldo.sql"
    )


def test_el_ensayo_de_la_limpieza_no_toca_las_secuencias():
    """setval no es transaccional: solo puede ir después del ensayo."""
    texto = _texto("06_limpiar_e2e.sql")
    antes_de_aplicar = texto.split("-- 5. Aplicar")[0]
    assert "setval(" not in antes_de_aplicar
    assert "setval(" in texto.split("-- 5. Aplicar")[1]


def test_la_limpieza_no_vacia_tablas():
    """Borra fila por fila contra la línea de base: nunca TRUNCATE."""
    codigo = re.sub(r"--[^\n]*", "", _texto("06_limpiar_e2e.sql"))
    assert "truncate" not in codigo.lower()
