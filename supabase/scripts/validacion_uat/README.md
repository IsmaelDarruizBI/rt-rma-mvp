# Validación funcional del UAT

Recorrido autenticado y E2E de la macroiteración V1.4 sobre el UAT de São Paulo, con datos ficticios, y su limpieza. Se usó el 12/11/2026, con el resultado en [`docs/ESTADO_PROYECTO.md`](../../../docs/ESTADO_PROYECTO.md), sección B.

**Escribe en el UAT:** cada ejecución necesita autorización explícita, y la limpieza es un paso aparte, también autorizado.

## Piezas

| Archivo | Qué hace |
|---|---|
| [`validar_uat.ps1`](validar_uat.ps1) | Corre los tres pasos en orden y guarda las salidas. Pide las contraseñas sin eco |
| [`../migracion_sp/probar_entornos.py`](../migracion_sp/probar_entornos.py) | Paso 1, solo lectura: inicio de sesión, aislamiento de tokens entre Oregón y São Paulo, catálogos, Inicio, Taller, cero Órdenes y stock |
| [`../migracion_sp/medir_api.py`](../migracion_sp/medir_api.py) | Paso 2, solo lectura: lecturas autenticadas con sus tiempos |
| [`probar_macro_v14.py`](probar_macro_v14.py) | Paso 3, **escribe**: 6 escenarios, 67 comprobaciones con las cuatro cuentas |

**Escenarios de `probar_macro_v14.py`:**

1. Evaluación técnica obligatoria, confirmación y adicionales.
2. Redefinición en la evaluación y descarte técnico.
3. Desistimiento total con una reparación activa (DC07C).
4. Antecedentes del equipo.
5. Reporte operativo.
6. Administración de Tipos de Reparación y de Mesas.

Reutiliza los helpers de `app/backend/tests/fixtures`, así que recorre los mismos caminos que las pruebas automáticas.

**Guardas de `probar_macro_v14.py`:**

- **Destino:** solo la API pública con el proyecto de São Paulo, o una API local con `--sin-autenticacion`.
- **Escritura:** sin `--escribir` solo verifica las precondiciones, y no escribe nada si el UAT ya tiene Órdenes.
- **Datos:** todos ficticios (cliente «Cliente Ficticio E2E V14», teléfono 000-0000, IMEI de ejemplo).
- **Catálogo:** el precio y la Mesa que cambia vuelven a su valor al final, aunque falle una comprobación.
- **Tipos de Reparación:** no crea ninguno, porque `tipo_reparacion` no admite borrado y quedaría para siempre.

## Recorrido

1. **Antes:**
   - el UAT tiene que estar en cero Órdenes;
   - registrar el estado inicial (catálogos, stock, secuencias, cuentas);
   - comprobar un respaldo cifrado reciente ([`docs/RESPALDOS.md`](../../../docs/RESPALDOS.md)).
2. **Ensayo local, sin contraseñas.** Base con migraciones y semillas, como en [`docs/CHECKPOINT_PRE_DEPLOY.md`](../../../docs/CHECKPOINT_PRE_DEPLOY.md), sección 7, y backend local en modo demo:

   ```bash
   app/backend/.venv/Scripts/python supabase/scripts/validacion_uat/probar_macro_v14.py --api http://127.0.0.1:8000 --sin-autenticacion --escribir
   ```

3. **En el UAT, la persona responsable:** cargar las claves publicables en `SUPABASE_PUBLISHABLE_KEY_ORIGEN` y `SUPABASE_PUBLISHABLE_KEY_DESTINO`, y ejecutar `validar_uat.ps1 -Salida <carpeta>`. Usar `-SinOregon` si Oregón ya no está.
4. **Identificar los datos creados.** Comparar con el informe JSON:
   - las Órdenes y su horario;
   - que todos los clientes sean ficticios;
   - que no haya eventos fuera de esas Órdenes;
   - los movimientos y los cambios de configuración.
5. **Limpieza con [`../reinicio_uat/`](../reinicio_uat/):**
   1. fijar `v_ordenes` en `01_reiniciar.sql` con las Órdenes identificadas;
   2. correrlo en modo `ensayo`;
   3. tomar un respaldo cifrado;
   4. correrlo en modo `aplicar`, sobre una copia con `v_modo` cambiado, sin tocar el archivo versionado;
   5. correr `03_verificar.sql`.

   El reinicio respalda lo que borra en el esquema `rma_respaldo_reinicio`. Mientras ese esquema exista, el próximo reinicio no corre: se elimina con `04_eliminar_respaldo.sql`, con autorización.
6. **Después:**
   - ensayo de restauración en la nube;
   - estado igual al inicial (el `updated_at` de Auth cambia por los inicios de sesión).
