# Validación manual local de los ajustes funcionales

Guía para probar a mano, en un navegador y sobre PostgreSQL local, los ocho bloques de ajustes funcionales (iteraciones 1 y 2) de la rama `feat/ajustes-funcionales-uat`. Complementa la sección 12 de [`ajustes-funcionales-discovery.md`](ajustes-funcionales-discovery.md): esta guía prepara el entorno y los datos; el recorrido paso a paso (A1 a E6) sigue estando allá.

Todo es local: no se toca el UAT, Supabase, Cloud Run ni Vercel. Los comandos son para **PowerShell** (Windows). Esta guía no contiene contraseñas, tokens ni claves.

## 1. Qué se usa

| Pieza | Dónde |
|---|---|
| PostgreSQL 17 local | `%USERPROFILE%\pg-rma`, puerto `54329` (instalación: [`CHECKPOINT_PRE_DEPLOY.md`](CHECKPOINT_PRE_DEPLOY.md), sección 7) |
| Base de validación | `rma_validacion`, **solo para esto**. `rma_dev`, `rma_ensayo_integral` y las demás bases no se tocan |
| Archivos del backend (fotos) y planillas de ejemplo | `%USERPROFILE%\rma-validacion-data`, fuera del repositorio |
| Backend | `http://127.0.0.1:8000`, acceso de prueba (`RMA_AUTH_MODO=demo`, el valor por defecto) |
| Frontend | `http://localhost:5173` (`npm run dev`); llama a `http://localhost:8000` por defecto, sin `.env` |
| Scripts | [`supabase/scripts/validacion_local/`](../supabase/scripts/validacion_local/) |

Los scripts de esa carpeta:

| Script | Qué hace |
|---|---|
| `crear_base_validacion.ps1` (y `.py`) | Borra y vuelve a crear **solo** `rma_validacion` con las 51 migraciones, las 4 cargas de referencia y la de desarrollo. Rechaza cualquier otro nombre de base y cualquier servidor que no sea local |
| `cargar_datos_validacion.py` | Carga los datos ficticios **por la API** del backend que está corriendo, así se aplican las reglas, los códigos, la auditoría y el historial. Se corre **una sola vez sobre una base recién creada**: si ya hay datos, no escribe nada |
| `verificar_edicion.py` | Opcional. Comprueba por la API que cada sección de Configuración responde `editable: true` y que un cambio de ida y vuelta se guarda. Deja esos cambios en el historial (con el valor original al final) |

## 2. Puesta en marcha

Hacen falta **dos ventanas de PowerShell** abiertas a la vez: una para el backend y otra para el frontend. Los demás comandos se pueden correr en una tercera o en cualquiera de las dos antes de levantar los servidores.

### 2.1 Una sola vez: rama y dependencias

```powershell
Set-Location "$env:USERPROFILE\RepositoriosRT\rt-rma-mvp"
git switch feat/ajustes-funcionales-uat
npm install
Set-Location app\backend
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -e ".[dev,postgres]"
Set-Location ..\frontend
npm install
Set-Location ..\..
```

Si el repositorio está en otra carpeta, cambiar la primera línea. `openpyxl` (nueva en la iteración 2) entra con el `pip install`.

### 2.2 PostgreSQL

Ver si está corriendo y, si no, iniciarlo:

```powershell
$pgbin = "$env:USERPROFILE\pg-rma\node_modules\@embedded-postgres\windows-x64\native\bin"
& "$pgbin\pg_ctl.exe" -D "$env:USERPROFILE\pg-rma\data" status
& "$pgbin\pg_ctl.exe" -D "$env:USERPROFILE\pg-rma\data" -o "-p 54329 -c listen_addresses=127.0.0.1" -l "$env:USERPROFILE\pg-rma\pg.log" start
```

**Esperado:** `status` informa el servidor y su PID si está corriendo; si dice «no hay servidor en ejecución», correr `start`, que termina con «servidor iniciado».

### 2.3 Crear (o volver a crear) `rma_validacion`

**Antes, detener el backend** si está corriendo sobre esa base (Ctrl+C en su ventana): la base se borra y se crea de nuevo, y todo lo que se haya cargado en ella se pierde.

```powershell
Set-Location "$env:USERPROFILE\RepositoriosRT\rt-rma-mvp"
powershell -ExecutionPolicy Bypass -File supabase\scripts\validacion_local\crear_base_validacion.ps1
```

**Esperado:** `56 archivos SQL; 80 tablas en rma`.

### 2.4 Ventana 1: backend

```powershell
Set-Location "$env:USERPROFILE\RepositoriosRT\rt-rma-mvp\app\backend"
$env:RMA_PERSISTENCIA = "postgres"
$env:RMA_DATABASE_URL = "postgresql://postgres@127.0.0.1:54329/rma_validacion"
$env:RMA_DATA_DIR = "$env:USERPROFILE\rma-validacion-data"
$env:RMA_FOTOS_DIR = "$env:USERPROFILE\rma-validacion-data\fotos"
Remove-Item Env:RMA_AUTH_MODO -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $env:RMA_FOTOS_DIR | Out-Null
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Esperado:** «Uvicorn running on http://127.0.0.1:8000». Desde otra ventana, `Invoke-RestMethod http://127.0.0.1:8000/health` devuelve `status: ok`. La ventana queda ocupada mientras el backend corre.

Si el puerto 8000 está ocupado, usar otro (por ejemplo `--port 8001`) y levantar el frontend con `$env:VITE_API_BASE_URL = "http://localhost:8001"` antes de `npm run dev`.

### 2.5 Cargar los datos ficticios (una vez, con el backend corriendo)

```powershell
Set-Location "$env:USERPROFILE\RepositoriosRT\rt-rma-mvp"
.\app\backend\.venv\Scripts\python.exe supabase\scripts\validacion_local\cargar_datos_validacion.py
```

**Esperado:** la lista de lo creado (sección 4) y, al final, la vista previa de las planillas de ejemplo. Si la base ya tenía datos, el script dice «La base no está recién creada» y no escribe nada.

Opcional, para confirmar que toda la configuración se puede editar:

```powershell
.\app\backend\.venv\Scripts\python.exe supabase\scripts\validacion_local\verificar_edicion.py
```

**Esperado:** `11 de 11 áreas OK.`

### 2.6 Ventana 2: frontend

```powershell
Set-Location "$env:USERPROFILE\RepositoriosRT\rt-rma-mvp\app\frontend"
npm run dev
```

Abrir `http://localhost:5173`. Si en `app\frontend` hay un `.env` o `.env.local` con `VITE_AUTH_MODO=supabase`, el acceso pide Supabase: para esta validación, sacar esa línea.

### 2.7 Detener todo

1. Ctrl+C en la ventana del frontend y en la del backend.
2. PostgreSQL puede quedar corriendo. Para detenerlo (no borra ninguna base):

   ```powershell
   & "$env:USERPROFILE\pg-rma\node_modules\@embedded-postgres\windows-x64\native\bin\pg_ctl.exe" -D "$env:USERPROFILE\pg-rma\data" stop
   ```

`rma_validacion` conserva lo cargado. Al volver, alcanza con 2.2, 2.4 y 2.6.

### 2.8 Empezar de cero

Detener el backend, correr 2.3, levantar el backend (2.4) y volver a cargar los datos (2.5).

## 3. Usuarios

El acceso es de prueba: no hay cuentas reales. La pantalla de acceso pide usuario y contraseña; el usuario es uno de los cuatro de abajo y la contraseña es la de prueba que fija el frontend (`CREDENCIALES_DEMO`, en `app/frontend/src/features/ordenes-reparacion/usuarioDemo.ts`), la misma para los cuatro. No protege nada y solo existe con `npm run dev`. Para cambiar de usuario: «Cerrar sesión» y volver a entrar.

| Usuario en la pantalla | Usuario de la base | Rol | Para qué sirve en la validación |
|---|---|---|---|
| `recepcion` | `RECEP-001` · Recepcion Demo | Recepción | Ingreso de Órdenes, comprobantes, autorización del cliente, cobros, descuentos y cortesías, entrega. No ve la información técnica, no elige piezas, no fija precios manuales ni revierte ajustes |
| `tecnico` | `TECH-001` · Tecnico Demo | Técnico | Revisión técnica, trabajos según la revisión, elegir y sustituir piezas, iniciar, completar e interrumpir ejecuciones, consumo |
| `coordinacion` | `COORD-001` · Coordinacion Demo | Coordinación RMA | Precio manual («Definir precio»), elegir piezas, stock (ingresos y ajustes), Compras, bandeja «Insumos a reponer». No entra a la configuración de insumos ni de precios |
| `administracion` | `ADMIN-001` · Administracion Demo | Administración | Toda la Configuración (empresa, términos, modelos, tipos, precios, importación, categorías, fabricantes, insumos, permisos), revertir y corregir ajustes, Compras. **No crea Órdenes ni ejecuta trabajos**: eso es de Recepción y del Técnico |

Los permisos son los predeterminados y se pueden cambiar en Configuración → Permisos (paso D2).

## 4. Datos ficticios

Todo es inventado: personas, teléfonos (`341-555-01xx`), correos `@example.com`, fabricantes y proveedor. Los códigos son los que asignó la base en la carga del 24/11/2026; en una base recreada salen iguales.

**Ya estaban** (carga de desarrollo): TR-001 «Cambio bateria iPhone 14» y TR-002 (precio único, de antes), la Mesa EST-001, el insumo INS-001 «Bateria iPhone 14» (2 unidades, sin clasificar) y los modelos MOD-0001 a MOD-0036.

### 4.1 Configuración

| Qué | Códigos | Detalle |
|---|---|---|
| Datos de la empresa | — | «Rosario Tecno (validación local)», dirección, teléfono `341-555-0100`, horario y pie de comprobante de prueba |
| Modelos nuevos | MOD-0037, MOD-0038 | Apple «iPhone 18 · Prueba local», **sin ningún precio**; Samsung «Galaxy A54», para el error «otra marca» de la importación |
| Categorías | CAT-001 a CAT-009 | Baterías (001); Módulos (002) › OLED (003), Incell (004); Flex (005) › Carga (006); Cámaras (007) › Trasera (008); Adhesivos y consumibles (009) |
| Fabricantes | FAB-001 a FAB-003 | Voltix Parts, Nordcell Repuestos y Pantallas Delta, todos «(ficticio)» |
| Proveedor | PRV-0001 | Distribuidora Ficticia de Repuestos |

### 4.2 Insumos

| Código | Insumo | Compatible con | Disponible | Mínimo | Estado | Caso |
|---|---|---|---|---|---|---|
| INS-002 | Batería iPhone 11 · Voltix | iPhone 11 | 1 | 3 | Bajo mínimo | Única para iPhone 11: se elige sola |
| INS-003 | Batería iPhone 12 / 12 Pro · Voltix | iPhone 12, 12 Pro | 4 | 2 | Suficiente | Única para iPhone 12: se elige sola (OR-000001) |
| INS-004 | Batería iPhone 14 · Voltix · Estándar | iPhone 14 | 1 | 2 | Bajo mínimo | Una de **dos** para iPhone 14: hay que elegir |
| INS-005 | Batería iPhone 14 · Nordcell · Alta capacidad | iPhone 14 | 3 (lote `NRC-B14-2611`) | — | Sin mínimo | La otra batería de iPhone 14; control por lote |
| INS-006 | Módulo iPhone 13 · Pantallas Delta · OLED | iPhone 13 | 2 | 1 | Suficiente | Uno de **dos** módulos de iPhone 13 |
| INS-007 | Módulo iPhone 13 · Nordcell · Incell | iPhone 13 | 3 | — | Sin mínimo | El otro módulo de iPhone 13 |
| INS-008 | Módulo iPhone 14 · Pantallas Delta · OLED | iPhone 14 | 1 | — | Sin mínimo | Único de iPhone 14: se elige solo (OR-000004) |
| INS-009 | Flex de carga iPhone 12 / 12 Pro · Voltix | iPhone 12, 12 Pro | 1 (+2 en camino) | 3 | Bajo mínimo · reposición solicitada | Solicitud SC-000001 pendiente |
| INS-010 | Flex de carga iPhone 14 · Nordcell | iPhone 14 | 0 (+2 en camino) | — | Sin mínimo | Sin stock: un cambio de flex de iPhone 14 queda bloqueado por recursos hasta recibir OC-000001 |
| INS-011 | Cámara trasera iPhone 13 · Pantallas Delta | iPhone 13 | 2 (lote `DLT-C13-2611`) | — | Sin mínimo | Única cámara de iPhone 13; por lote |
| INS-012 | Adhesivo de pantalla y batería · Universal | Todos (universal) | 20 (lote `ADH-2611-A`) | 5 | Suficiente | Previsto concreto de batería y módulo |

No hay ninguna batería compatible con iPhone 13 ni ninguna batería universal: es a propósito (pasos B4, C7 y C9).

### 4.3 Compras

- **SC-000001:** solicitud por stock mínimo de 2 × INS-009, pendiente.
- **OC-000001:** orden de compra a PRV-0001 por 2 × INS-010, **confirmada y sin recibir**.
- **Sugerencias de reposición** al empezar: INS-002 (2 unidades) e INS-004 (1 unidad), las dos por stock mínimo.

### 4.4 Tipos de reparación

Todos habilitados en la Mesa EST-001.

| Código | Tipo | Precio | Sin precio a propósito | Insumos necesarios |
|---|---|---|---|---|
| TR-003 | Cambio de batería | Por modelo (35 modelos) | **iPhone 13** (MOD-0010) e iPhone 18 | Requisito «Baterías» × 1 + INS-012 × 1 |
| TR-004 | Cambio de módulo | Por modelo (35) | **iPhone 14 Pro Max** (MOD-0017) e iPhone 18 | Requisito «Módulos» × 1 + INS-012 × 1 |
| TR-005 | Cambio de flex de carga | Por modelo (36) | iPhone 18 | Requisito «Flex» × 1 |
| TR-006 | Cambio de cámara trasera | Por modelo (19: iPhone 11 a 15) | iPhone 8, X, SE, 16, 17 e iPhone 18 | Requisito «Cámaras» × 1 |
| TR-007 | Diagnóstico | Único, $15.000 | — | Ninguno |
| TR-008 | Limpieza y mantenimiento | Único, $20.000 | — | Ninguno |

Ejemplos de precio: batería iPhone 12 $48.000, iPhone 14 $62.000; módulo iPhone 14 $155.000.

### 4.5 Órdenes de ejemplo

Cuatro Órdenes de Cliente Externo, creadas por `recepcion` y todavía en el ingreso (sin comprobante): sirven para que las listas no estén vacías y para ver cada caso sin cargarlo. El resto se crea a mano.

| Orden | Cliente | Equipo | Trabajo | Qué muestra |
|---|---|---|---|---|
| OR-000001 | Lucía Ficticia Gómez · 341-555-0101 | iPhone 12 | Cambio de batería | Precio del modelo ($48.000) y batería INS-003 «Elegida automáticamente» |
| OR-000002 | Martín Prueba Rossi · 341-555-0102 | iPhone 13 | Cambio de batería | «Precio pendiente de definir» y «Baterías» pendiente, sin ninguna compatible |
| OR-000003 | Carla Ejemplo Díaz · 341-555-0103 | Apple a mano, sin modelo técnico, «IMEI no disponible» | Ninguno: «Trabajo solicitado» en texto libre | Ingreso sin trabajos y sin IMEI; se identifica con su `EQP-…` |
| OR-000004 | Diego Demo Fernández · 341-555-0104 | iPhone 14 | Cambio de módulo | Precio del modelo ($155.000) y módulo INS-008 elegido solo |

### 4.6 Planillas para la importación de precios

En `%USERPROFILE%\rma-validacion-data\planillas` (fuera del repositorio). **Ninguna se aplicó.**

| Archivo | Vista previa esperada |
|---|---|
| `plantilla_original.xlsx` y `.csv` | Las plantillas tal como se descargan: 0 cambios, 0 errores, «no hay cambios» |
| `precios_ejemplo_valido.xlsx` | 2 nuevos (batería y módulo del iPhone 18) y 1 que cambia (batería iPhone 14: $62.000 → $66.000). Se puede aplicar |
| `precios_ejemplo_con_errores.csv` | 2 errores: «80,000» en C4 (ambiguo) y la fila del Samsung MOD-0038 en A39 (otra marca); la columna «TR001 · columna mal escrita» entre las ignoradas; «Aplicar» deshabilitado |

La batería del iPhone 13 no está en ninguna planilla, para no romper los pasos B2 a B4.

### 4.7 Cómo se ajusta el recorrido de la sección 12.2

El recorrido se escribió para una base sin configuración. Con estos datos:

- **A3:** el próximo modelo nuevo es `MOD-0039` (MOD-0037 y MOD-0038 ya existen). Para el duplicado, repetir «iPhone 18 · Prueba local».
- **A4, A8, A9 y A11:** ya hay un ejemplo cargado de cada uno (TR-003, CAT-…, FAB-…, INS-004/005, insumos necesarios de TR-003). Para probar el alta, crear otros con nombres nuevos (por ejemplo, el tipo «Cambio de parlante», la categoría «Parlantes» con la subcategoría «Inferior», un cuarto fabricante y un insumo de esa subcategoría). En A9, «Sin clasificar» muestra solo INS-001: el adhesivo de estos datos ya está clasificado.
- **A5 a A7:** usar las planillas de 4.6.
- **A12 y A13:** INS-004 ya está «Bajo mínimo»; la sugerencia ya aparece. E6 convierte esa solicitud en orden de compra.
- **B1 a B7 y C:** las Órdenes nuevas empiezan en OR-000005. La «Orden 1» del recorrido es un iPhone 14 con «Cambio de batería» (dos baterías: hay que elegir); la «Orden 2» puede ser OR-000002 o una nueva igual; la «Orden 3», OR-000003 o una nueva igual.

## 5. Guía de prueba por proceso

Cada punto dice qué hacer y qué debería pasar. Entre paréntesis, el paso de la sección 12.2 de [`ajustes-funcionales-discovery.md`](ajustes-funcionales-discovery.md#122-recorrido) que lo detalla.

### 5.1 Configuración inicial (`administracion`)

1. Configuración → «Datos de la empresa»: cambiar el horario y el pie → se guarda, queda en el historial y sale en los comprobantes nuevos (A1).
2. «Términos y condiciones»: publicar una versión 3 → rige para los comprobantes nuevos; la 2 se conserva (A2).
3. «Modelos de equipo»: crear un modelo → `MOD-0039`; repetir «iPhone 18 · Prueba local» con otras mayúsculas → se rechaza; `coordinacion` no ve la sección (A3).
4. Tipos de reparación: abrir la grilla de TR-003 → iPhone 13 sin precio; crear un tipo nuevo con «Precio por modelo», cargar dos precios y quitar uno → todo o nada, el quitado queda inactivo y el historial muestra el modelo (A4).
5. Categorías, fabricantes e insumos: crear una categoría con subcategoría, un fabricante y un insumo con «Solo para algunos modelos» → códigos `CAT-010`, `FAB-004`, `INS-013`; un nombre repetido se rechaza (A8, A9).
6. Tipos de reparación → «Insumos necesarios» de TR-003: intentar agregar INS-004 como previsto concreto → se rechaza, porque no es universal (A11).
7. Con `coordinacion`, intentar editar el stock mínimo de un insumo → no puede (A10).

### 5.2 Ingreso de la Orden (`recepcion`)

1. Nueva Orden de Cliente Externo: iPhone 14, «Cambio de batería», verificación de funcionalidades → el selector muestra $62.000 ($66.000 si ya se aplicó la planilla de 5.9); la verificación es obligatoria; «Crear y generar el comprobante» ofrece «Imprimir» sin imprimir solo (B1).
2. Nueva Orden con iPhone 13 y «Cambio de batería» → «Sin precio para este modelo», se crea la Orden pero no el comprobante; el trabajo dice «Precio pendiente de definir», nunca $0 (B2). OR-000002 ya muestra este caso.
3. En la Orden del iPhone 13, corregir el modelo a iPhone 14 y después volver → toma el precio de catálogo y vuelve a quedar pendiente; el historial lo registra (B3).
4. Nueva Orden sin trabajos, con el equipo a mano e «IMEI no disponible» → se identifica con su `EQP-…`; después, «Registrar el IMEI real» con motivo (B5, B6). OR-000003 ya muestra el ingreso.
5. Abrir la Orden del paso 1 → Recepción no ve antecedentes, ejecuciones, insumos previstos, «Datos técnicos» ni piezas (B7).

### 5.3 Diagnóstico y presupuesto

1. Con `coordinacion`, «Definir precio» en la Orden del iPhone 13 con precio manual y motivo → marca «Precio manual» con el motivo y quién (B4).
2. Intentar lo mismo en la Orden del iPhone 14 → se rechaza: tiene precio de catálogo; para bajarlo está el ajuste comercial (B4).
3. Con `recepcion`, generar el comprobante de la Orden del iPhone 13 → ahora se puede; el trabajo queda bloqueado por recursos porque no hay batería compatible (B4, C9).
4. Probar «Cambio de módulo» en un iPhone 14 Pro Max → precio pendiente (TR-004 no tiene precio para ese modelo).
5. Con `tecnico`, en una Orden en revisión, agregar un trabajo según la revisión (por ejemplo «Diagnóstico», precio único) → toma $15.000 sin pedir precio.
6. Autorización del cliente con precio pendiente: con `tecnico`, en una Orden ya recibida, agregar según la revisión un trabajo sin precio para el modelo (por ejemplo «Cambio de módulo» en un iPhone 14 Pro Max). Con `recepcion`, intentar registrar «Autorizado» → se rechaza (`PRECIO_PENDIENTE`) hasta que `coordinacion` defina el precio; el rechazo del cliente sí se admite.

### 5.4 Preparación del trabajo: piezas, stock y reserva

1. Con `tecnico`, Orden del iPhone 14 con «Cambio de batería» → «Baterías» está «Pendiente de elegir» (dos compatibles). En OR-000001 (iPhone 12) y OR-000004 (módulo iPhone 14) la pieza está «Elegida automáticamente» (C1).
2. Tomar la Orden e iniciar sin elegir → rechazo `PIEZA_SIN_ELEGIR`, sin reserva ni paso nuevo (C2).
3. Con `recepcion`, buscar «Elegir pieza» → no aparece (C3).
4. Con `tecnico`, «Elegir pieza»: INS-004 (muestra disponible 1) e iniciar → se reservan INS-004 e INS-012; Inventario los muestra reservados (C4).
5. Con la Ejecución en curso, «Sustituir» por INS-005 sin motivo → se rechaza; con motivo → libera INS-004, reserva INS-005 y deja un solo paso en el historial (C5).
6. Orden sin modelo técnico (OR-000003 o una igual): agregar «Cambio de batería» → precio pendiente; elegir la pieza → se ofrece cualquier batería, con motivo obligatorio y «Compatibilidad no verificada» (C7).
7. Una Orden de iPhone 14 con «Cambio de flex de carga» → INS-010 se elige sola (es la única compatible), pero no tiene stock: al generar el comprobante, el trabajo queda bloqueado por recursos hasta recibir OC-000001 (5.8.5).

### 5.5 Reparación y consumo (`tecnico`)

1. Completar la Ejecución del paso 5.4.5 → el formulario de consumo marca «· pieza elegida» y consume INS-005 del lote `NRC-B14-2611` (C6).
2. Intentar sustituir la pieza consumida → ya no se puede (C6).
3. Con una Ejecución en curso de Cliente Externo, agregar un trabajo adicional → espera la autorización; la Orden aparece en «Pendientes de mi sector» de `recepcion`; iniciarlo sin autorizar da 409 (C8).
4. En Inventario, ver el libro de INS-004 e INS-005: la liberación con la observación «Sustitución de pieza», la reserva nueva y el consumo.

### 5.6 Cobro, descuentos y cortesías

1. Con `recepcion`, «Ajuste comercial» en una Orden: descuento al trabajo y cortesía a la Orden → un solo formulario con la vista previa del precio original, el ajuste y el final (D1).
2. Con `administracion`, quitar la cortesía a Recepción en Permisos; con `recepcion`, intentar cambiar o quitar la cortesía → no puede; restaurar el permiso (D2).
3. Con `recepcion`, buscar «Revertir» y «Corregir» → no aparecen (D3).
4. Con `administracion`, revertir el descuento y corregir la cortesía a otro importe → el revertido tachado, la corrección enlazada, el saldo recalculado y los pagos intactos (D4).
5. Redefinir o cancelar un trabajo con ajuste → aviso de recálculo y el recálculo en el historial, sin un ajuste nuevo (D5).
6. Registrar el pago hasta saldo 0 (D7).

### 5.7 Entrega y comprobantes (`recepcion`)

1. Orden lista para retirar: entregar sin avisar al cliente → se permite; el progreso muestra el aviso como opcional y salteado (E1).
2. En la misma confirmación: check-in y «¿Retira otra persona?» Sí con datos ficticios → un solo «Comprobante de entrega y garantía» con los términos vigentes, la garantía desde la entrega y quién retiró (E2).
3. Con `administracion`, intentar un ajuste en la Orden entregada → se rechaza (E3).
4. Cambiar otra vez el pie de la empresa y reimprimir el comprobante de entrega → conserva los datos con que se emitió (E4).
5. Emitir la versión nueva del comprobante de autorización y ver el de ingreso anterior → precio, ajuste y precio final por trabajo; el ajuste de la Orden en una línea aparte (D6).
6. Otra Orden lista: enviar el WhatsApp «equipo listo para retirar» → se registra una vez; el retiro demorado cuenta desde que quedó lista (E5).

### 5.8 Inventario, stock mínimo y compras

1. Inventario → filtro «Bajo mínimo» → INS-002 e INS-004 «Bajo mínimo» (ámbar) e INS-009 «Bajo mínimo · reposición solicitada» (azul) (A12).
2. Inicio con `coordinacion` y `administracion` → bandeja «Insumos a reponer»; con `recepcion` y `tecnico`, no aparece (A12).
3. Compras → «Sugerencias de reposición»: crear la solicitud de INS-004 → la causa es el stock mínimo; INS-004 pasa a azul y deja de sugerirse (A13).
4. Registrar un ingreso de INS-005 sin lote → lo pide (control por lote); con lote → suma al lote.
5. Compras → OC-000001: recibir las 2 unidades de INS-010 → el flex queda con stock y la Orden bloqueada del punto 5.4.7 se puede revalidar.
6. Convertir la solicitud del punto 3 en orden de compra, confirmarla y recibirla → INS-004 pasa a «Suficiente» y sale de la bandeja (E6).
7. Compras → «Trabajos sin pieza elegida» → aparece la Orden del iPhone 13 bloqueada, sin sumar demanda a ningún SKU (C9).
8. Nueva solicitud con el selector: filtrar por categoría, fabricante y modelo → etiquetas «INS-… · nombre · fabricante · variante» (A14).

### 5.9 Importación de precios (`administracion`)

1. Configuración → «Importar precios»: subir `plantilla_original.xlsx` y `.csv` → «No hay cambios», sin errores (A5).
2. Subir `precios_ejemplo_con_errores.csv` → errores en C4 y A39, «TR001» entre las ignoradas, «Aplicar» deshabilitado (A6).
3. Subir `precios_ejemplo_valido.xlsx` → 2 nuevos y 1 cambia, con el precio anterior y el nuevo; aplicar → el historial de precios muestra el identificador de la importación (A7).
4. Subirla otra vez → «No hay cambios».
5. Descargar la plantilla, editarla en Excel o Google Sheets y pegar las celdas copiadas → misma vista previa que el archivo (A7).
6. Nueva Orden con iPhone 18 y «Cambio de batería» → toma el precio importado ($98.000).

## 6. Cómo registrar el feedback

Una línea por diferencia, en una planilla o un documento, con estas columnas:

| Columna | Ejemplo |
|---|---|
| Paso | `C5` (de la sección 12.2) o `5.4.5` (de esta guía) |
| Usuario | `tecnico` |
| Orden o código | `OR-000005`, `INS-004` |
| Qué hice | «Sustituir sin motivo» |
| Esperado | «Se rechaza» |
| Observado | Lo que pasó, con el texto exacto del mensaje |
| Captura | Opcional |

Una diferencia que ya figure en [`pendientes-producto.md`](pendientes-producto.md) se anota igual, como confirmación. Lo que no cubre esta validación está en la sección 12.3 del discovery.
