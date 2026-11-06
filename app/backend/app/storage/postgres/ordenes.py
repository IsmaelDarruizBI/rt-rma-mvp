"""``OrdenReparacionRepository`` sobre PostgreSQL (E4: A1, A2, A3 y A4).

Guardado por agregado sin borrar ni reinsertar (DA-1): ``rma_backend``
no tiene ``DELETE`` y las historias son inmutables por trigger. ``guardar``
compara la Orden que llega con la persistida y emite solo:

- ``INSERT`` de lo nuevo: el alta, los Detalles, sus versiones de
  definicion, decisiones, ajustes y controles, las tomas, ejecuciones e
  insumos utilizados, y los pasos nuevos del historial;
- ``UPDATE`` de lo mutable: la raiz, la recepcion antes de decidir la
  custodia, el estado de Detalles, tomas y ejecuciones en curso.

En cada lista que solo crece, lo ya guardado tiene que ser el principio
de lo que llega. Si no lo es, el comando altero una entrada inmutable, un
error de programacion: ``PersistenciaError``.

Precondicion de ``guardar`` (QA-A2-H1). Una Orden nueva se inserta sin mas.
Una Orden que ya existe solo se guarda si viene de
``obtener_para_modificar`` en esta misma transaccion; si no, se rechaza con
``PersistenciaError``, sin escribir nada, y el comando se revierte. El
contenido no permite distinguir un valor viejo de un cambio legitimo, y
sin instantanea la version se compararia consigo misma: una lectura vieja
pisaria en silencio cualquier campo que no deja historial. Por eso la
Orden entregada lleva una marca de esta transaccion, fuera de sus campos:
no se serializa, no cuenta en la igualdad y pasa a las copias de los
services (``model_copy``). Una Orden reconstruida la pierde y se rechaza.
JSON no exige esto todavia (B4): ahi la red es la seccion critica del caso
de uso.

Concurrencia (DA-2):

- ``obtener_para_modificar`` toma ``FOR NO KEY UPDATE`` sobre la Orden:
  los comandos sobre la misma Orden se serializan, y el segundo lee lo que
  confirmo el primero. ``FOR NO KEY UPDATE`` no choca con el ``FOR KEY
  SHARE`` de las claves foraneas que la referencian.
- ``rma.orden.version`` sube 1 en cada ``guardar`` que cambia algo de la
  Orden (tambien lo que no deja historial, como un check-in o un
  descuento). El ``UPDATE`` final exige la version leida: si no coincide,
  ``ConflictoDeEscrituraError`` y la transaccion se revierte. Guardar la
  misma Orden otra vez no escribe nada ni cambia la version.
- Orden de bloqueo: Orden, Cliente, Documento, Equipo y, en E5, los
  insumos por ``clave`` ascendente (A2-3). Un alta bloquea Cliente,
  Documento y Equipo: su Orden todavia no la ve nadie.

Cada evento del historial necesita la accion del comando
(``acciones.py``, DA-3), que se registra en la misma transaccion.

La marca depende de pydantic: que ``model_copy`` y ``deepcopy`` conserven
``__dict__``, y que ``__eq__`` y la serializacion ignoren lo que no es un
campo, como con un ``cached_property``. Verificado con pydantic 2.13.5; al
actualizarlo, las pruebas ``test_h1_la_marca_*`` dicen si sigue valiendo.

Recepcion, documentos, fotos y salida (A4): las versiones, notas y check-in
de la recepcion, las fotos y los documentos solo crecen, con su ``posicion``
en la lista. ``rma.recepcion`` no se actualiza despues de decidir la
custodia: el check-in posterior va a ``rma.checkin``. Lo que el esquema no
puede representar se rechaza antes de escribir, nunca se pierde.

Finanzas (A3): pagos, devoluciones de dinero y descuentos solo crecen, con
su ``posicion``. Lo unico mutable de un Pago es su anulacion, que se
completa una sola vez (un trigger lo exige). El medio de pago se resuelve
por codigo: uno que no existe en ``rma.medio_pago`` es un error (DA-10).
Las devoluciones y los pasos del historial referencian su Pago por uuid.

Consultas (A5): cada consulta dedicada de E2 es un filtro SQL que trae
las candidatas con su version; las Ordenes se cargan por lote y el
resultado lo decide el mismo predicado que usa JSON, sobre la Orden
cargada. Fuera de un comando, la lectura breve es REPEATABLE READ: un
solo instante. Dentro de un comando (READ COMMITTED) cada consulta ve el
suyo, y una carga son varias (QA-A2-M2). Por eso, en un comando:

- la carga se valida por version: al terminar se releen las versiones de
  las candidatas, y si un comando confirmo en el medio se carga otra vez.
  Alcanza porque todo cambio del agregado sube ``rma.orden.version``
  (DA-2), y la confirmacion de otro comando es atomica. No bloquea a nadie
  ni cambia el aislamiento;
- una Orden que el comando no bloqueo ni escribio se ve en una sola
  version: la primera que leyo (QA-E2-1, ``application/bandejas.py``).
  Cada consulta se evalua sobre esa vista. Las que bloqueo
  (``obtener_para_modificar``) o escribio se leen siempre como estan.

Reservas (A6): los movimientos de la Orden solo crecen, con su
``posicion``, en el libro ``rma.movimiento_inventario``; el trigger del libro
aplica el stock. Antes del primer movimiento se bloquean sus insumos por
``clave`` (DI-2), despues de la Orden: el orden de bloqueos de A2-3. Los
movimientos llevan la accion del comando.

Consumos y liberaciones (A7): cierran su RESERVA de origen, que el trigger
verifica. Despues de insertarlos, ``guardar`` verifica el stock que espera
el service (DI-1, ``verificar_stock_esperado``).

Fuera de alcance: DEVOLUCION y DESPERDICIO no tienen operacion habilitada
(DI-5) y se rechazan con ``PersistenciaError``.

Diseno: ``docs/postgresql/e4-e7-diseno-integrado.md`` (secciones 3 y 4).
"""

import json
from collections.abc import Callable, Collection, Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.domain.models import (
    EstadoWorkflow,
    OrdenReparacion,
    TipoMovimientoInsumo,
)
from app.domain.models.pagos import Pago
from app.domain.models.recepcion import RecepcionEquipo
from app.domain.models.reparacion import ReparacionDetail
from app.repositories.exceptions import (
    ConflictoDeEscrituraError,
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
)

from .acciones import accion_del_comando
from .catalogos import bloquear_insumos, verificar_stock_esperado
from .consultas import ESCRITURA, LECTURA, Consulta, consulta
from .ejecutor import EjecutorSql
from .ordenes_lectura import (
    FILTRO_ABIERTAS,
    FILTRO_DNI,
    FILTRO_MOVIMIENTOS,
    FILTRO_RESERVAS,
    FILTRO_TODAS,
    FILTRO_UNA,
    Instantanea,
    cargar_ordenes,
    claves_de_fotos,
    versiones_de,
)
from .transaccion import UnidadDeTrabajoPostgres

_INSTANTANEAS = "ordenes.instantaneas"
# Primera version leida de cada Orden no bloqueada, por comando (QA-E2-1).
_LEIDAS = "ordenes.leidas"
# Cargas que un comando que confirma en el medio puede invalidar seguidas.
_INTENTOS_DE_LECTURA = 3
# Los que el libro admite en una Orden: DEVOLUCION y DESPERDICIO no (DI-5).
_TIPOS_DE_MOVIMIENTO = frozenset(
    {
        TipoMovimientoInsumo.RESERVA,
        TipoMovimientoInsumo.CONSUMO,
        TipoMovimientoInsumo.LIBERACION_RESERVA,
    }
)
# Atributo de la Orden entregada por ``obtener_para_modificar`` (QA-A2-H1).
_MARCA = "_marca_de_instantanea"
_DOS_DECIMALES = Decimal("0.01")
_TRES_DECIMALES = Decimal("0.001")

# --- Consultas -------------------------------------------------------------

_BLOQUEAR = consulta(
    "ordenes.bloquear",
    "SELECT id, version FROM rma.orden WHERE codigo = %(codigo)s "
    "FOR NO KEY UPDATE",
    modo=ESCRITURA,
)
_SIGUIENTE_NUMERO = consulta(
    "ordenes.siguiente_numero",
    "SELECT rma.formatear_numero_orden(nextval('rma.orden_numero_seq')) "
    "AS codigo",
    modo=ESCRITURA,
)
_EXISTE = consulta(
    "ordenes.existe",
    "SELECT 1 AS existe FROM rma.orden WHERE codigo = %(codigo)s",
    modo=LECTURA,
)

_IDS = {
    tabla: consulta(
        f"ordenes.ids_{tabla}",
        f"SELECT {columna} AS codigo, id FROM rma.{tabla} "
        f"WHERE {columna} = ANY(%(codigos)s)",
        modo=LECTURA,
    )
    for tabla, columna in (
        ("usuario", "codigo"),
        ("tipo_reparacion", "codigo"),
        ("mesa_trabajo", "codigo"),
        ("insumo", "clave"),
        ("modelo_equipo", "codigo"),
        ("orden", "codigo"),
        ("medio_pago", "codigo"),
    )
}
_INSERTAR_VERSION_RECEPCION = consulta(
    "ordenes.insertar_version_recepcion",
    """
    INSERT INTO rma.recepcion_version
        (orden_id, datos, registrado_por, registrado_en, reemplazado_por,
         reemplazado_en, posicion)
    VALUES (%(orden)s, %(datos)s::jsonb, %(registrado_por)s,
            %(registrado_en)s, %(reemplazado_por)s, %(reemplazado_en)s,
            %(posicion)s)
    """,
    modo=ESCRITURA,
)
_INSERTAR_NOTA_RECEPCION = consulta(
    "ordenes.insertar_nota_recepcion",
    """
    INSERT INTO rma.recepcion_nota
        (orden_id, texto, interna, usuario_id, registrada_en, posicion)
    VALUES (%(orden)s, %(texto)s, %(interna)s, %(usuario)s, %(fecha)s,
            %(posicion)s)
    """,
    modo=ESCRITURA,
)
_INSERTAR_CHECKIN = consulta(
    "ordenes.insertar_checkin",
    """
    INSERT INTO rma.checkin
        (orden_id, realizado, usuario_id, registrado_en, posicion)
    VALUES (%(orden)s, %(realizado)s, %(usuario)s, %(fecha)s, %(posicion)s)
    """,
    modo=ESCRITURA,
)
_INSERTAR_FOTO = consulta(
    "ordenes.insertar_foto",
    """
    INSERT INTO rma.foto
        (codigo, orden_id, objeto_clave, tipo_contenido, tamano_bytes,
         nombre_original, usuario_id, registrada_en, posicion)
    VALUES (%(codigo)s, %(orden)s, %(objeto)s, %(tipo)s, %(tamano)s,
            %(nombre)s, %(usuario)s, %(fecha)s, %(posicion)s)
    """,
    modo=ESCRITURA,
)
_INSERTAR_DOCUMENTO_EMITIDO = consulta(
    "ordenes.insertar_documento_emitido",
    """
    INSERT INTO rma.documento_emitido
        (codigo, orden_id, tipo, version, emitido_en, usuario_id, motivo,
         reemplaza_a, contenido, posicion)
    VALUES (%(codigo)s, %(orden)s, %(tipo)s, %(version)s, %(fecha)s,
            %(usuario)s, %(motivo)s, %(reemplaza)s, %(contenido)s::jsonb,
            %(posicion)s)
    RETURNING id
    """,
    modo=ESCRITURA,
)
_INSERTAR_SALIDA = consulta(
    "ordenes.insertar_salida",
    """
    INSERT INTO rma.salida
        (orden_id, tipo, entregado_por, retira_nombre,
         retira_identificacion, registrada_en, observaciones)
    VALUES (%(orden)s, %(tipo)s, %(entregado_por)s, %(recibido_por)s,
            %(identificacion)s, %(fecha)s, %(observaciones)s)
    """,
    modo=ESCRITURA,
)
_INSERTAR_PAGO = consulta(
    "ordenes.insertar_pago",
    """
    INSERT INTO rma.pago
        (codigo, orden_id, monto, tipo_pago, medio_pago_id, referencia,
         usuario_id, registrado_en, anulado_por, anulado_en,
         anulacion_motivo, operacion_id, posicion)
    VALUES (%(codigo)s, %(orden)s, %(monto)s, %(tipo)s, %(medio)s,
            %(referencia)s, %(usuario)s, %(fecha)s, %(anulado_por)s,
            %(anulado_en)s, %(anulacion_motivo)s, %(operacion)s,
            %(posicion)s)
    RETURNING id
    """,
    modo=ESCRITURA,
)
_ANULAR_PAGO = consulta(
    "ordenes.anular_pago",
    """
    UPDATE rma.pago SET anulado_por = %(anulado_por)s,
        anulado_en = %(anulado_en)s, anulacion_motivo = %(anulacion_motivo)s
    WHERE id = %(id)s
    """,
    modo=ESCRITURA,
)
_INSERTAR_DEVOLUCION_DINERO = consulta(
    "ordenes.insertar_devolucion_dinero",
    """
    INSERT INTO rma.devolucion_dinero
        (codigo, orden_id, pago_id, monto, medio_pago_id, motivo,
         referencia, usuario_id, registrada_en, operacion_id, posicion)
    VALUES (%(codigo)s, %(orden)s, %(pago)s, %(monto)s, %(medio)s,
            %(motivo)s, %(referencia)s, %(usuario)s, %(fecha)s,
            %(operacion)s, %(posicion)s)
    """,
    modo=ESCRITURA,
)
_INSERTAR_DESCUENTO = consulta(
    "ordenes.insertar_descuento",
    """
    INSERT INTO rma.descuento
        (orden_id, tipo, valor, motivo, usuario_id, registrado_en, posicion)
    VALUES (%(orden)s, %(tipo)s, %(valor)s, %(motivo)s, %(usuario)s,
            %(fecha)s, %(posicion)s)
    """,
    modo=ESCRITURA,
)
_INSERTAR_MOVIMIENTO = consulta(
    "ordenes.insertar_movimiento",
    """
    INSERT INTO rma.movimiento_inventario
        (codigo, tipo, insumo_id, cantidad, orden_id, detalle_id,
         ejecucion_id, movimiento_origen_id, observacion, usuario_id,
         accion_id, registrado_en, posicion)
    VALUES (%(codigo)s, %(tipo)s, %(insumo)s, %(cantidad)s, %(orden)s,
            %(detalle)s, %(ejecucion)s, %(origen)s, %(observacion)s,
            %(usuario)s, %(accion)s, %(fecha)s, %(posicion)s)
    RETURNING id
    """,
    modo=ESCRITURA,
)
_DETALLE_DE_ORDEN = consulta(
    "ordenes.detalle_de_orden",
    "SELECT id FROM rma.detalle "
    "WHERE orden_id = %(orden)s AND codigo = %(codigo)s",
    modo=LECTURA,
)
_TIPO_DNI = consulta(
    "ordenes.tipo_dni",
    "SELECT id, exige_unicidad FROM rma.tipo_documento WHERE codigo = 'DNI'",
    modo=LECTURA,
)
_EQUIVALENCIAS = consulta(
    "ordenes.equivalencias",
    """
    SELECT tipo_referencia, referencia_id, accion, tipo_evento_id
    FROM rma.equivalencia_historial
    WHERE referencia_id = ANY(%(referencias)s)
    """,
    modo=LECTURA,
)

_CLIENTE = consulta(
    "ordenes.cliente",
    "SELECT id, nombre, telefono, email FROM rma.cliente "
    "WHERE codigo = %(codigo)s FOR UPDATE",
    modo=ESCRITURA,
)
_INSERTAR_CLIENTE = consulta(
    "ordenes.insertar_cliente",
    """
    INSERT INTO rma.cliente (codigo, nombre, telefono, email)
    VALUES (%(codigo)s, %(nombre)s, %(telefono)s, %(email)s)
    ON CONFLICT (codigo) DO NOTHING
    RETURNING id
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_CLIENTE = consulta(
    "ordenes.actualizar_cliente",
    "UPDATE rma.cliente SET nombre = %(nombre)s, telefono = %(telefono)s, "
    "email = %(email)s WHERE id = %(id)s",
    modo=ESCRITURA,
)
_DOCUMENTO_VIGENTE = consulta(
    "ordenes.documento_vigente",
    """
    SELECT id, numero_normalizado FROM rma.documento_cliente
    WHERE cliente_id = %(cliente)s AND tipo_documento_id = %(tipo)s
      AND vigente_hasta IS NULL
    FOR UPDATE
    """,
    modo=ESCRITURA,
)
_CERRAR_DOCUMENTO = consulta(
    "ordenes.cerrar_documento",
    "UPDATE rma.documento_cliente SET vigente_hasta = now() WHERE id = %(id)s",
    modo=ESCRITURA,
)
_INSERTAR_DOCUMENTO = consulta(
    "ordenes.insertar_documento",
    """
    INSERT INTO rma.documento_cliente
        (cliente_id, tipo_documento_id, exige_unicidad, numero_ingresado,
         numero_normalizado)
    VALUES (%(cliente)s, %(tipo)s, %(exige)s, %(numero)s, %(numero)s)
    """,
    modo=ESCRITURA,
)
_EQUIPO = consulta(
    "ordenes.equipo",
    "SELECT id, imei, numero_serie, modelo_equipo_id, capacidad_texto, color "
    "FROM rma.equipo WHERE codigo = %(codigo)s FOR UPDATE",
    modo=ESCRITURA,
)
_INSERTAR_EQUIPO = consulta(
    "ordenes.insertar_equipo",
    """
    INSERT INTO rma.equipo
        (codigo, imei, numero_serie, modelo_equipo_id, capacidad_texto, color)
    VALUES (%(codigo)s, %(imei)s, %(numero_serie)s, %(modelo)s,
            %(capacidad)s, %(color)s)
    ON CONFLICT (codigo) DO NOTHING
    RETURNING id
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_EQUIPO = consulta(
    "ordenes.actualizar_equipo",
    """
    UPDATE rma.equipo SET imei = %(imei)s, numero_serie = %(numero_serie)s,
        modelo_equipo_id = %(modelo)s, capacidad_texto = %(capacidad)s,
        color = %(color)s
    WHERE id = %(id)s
    """,
    modo=ESCRITURA,
)

_COLUMNAS_RAIZ = (
    "estado_workflow",
    "posicion_proceso",
    "prioridad",
    "referencia_rt",
    "cliente_id",
    "equipo_id",
    "cliente_tipo_persona",
    "cliente_nombre",
    "cliente_documento_tipo",
    "cliente_documento_numero",
    "cliente_telefono",
    "cliente_email",
    "equipo_modelo_equipo_id",
    "equipo_marca",
    "equipo_modelo",
    "equipo_variante",
    "equipo_capacidad_texto",
    "equipo_color",
    "equipo_imei",
    "equipo_numero_serie",
    "equipo_tipo_producto_id",
    "falla_reportada",
    "comprobante_recepcion_generado_en",
    "comprobante_final_generado_en",
    "garantia_generada_en",
    "actualizado_en",
)
_INSERTAR_ORDEN = consulta(
    "ordenes.insertar",
    """
    INSERT INTO rma.orden
        (codigo, origen, orden_origen_id, creada_en, estado_workflow,
         posicion_proceso, prioridad, referencia_rt, cliente_id, equipo_id,
         cliente_tipo_persona, cliente_nombre, cliente_documento_tipo,
         cliente_documento_numero, cliente_telefono, cliente_email,
         equipo_modelo_equipo_id, equipo_marca, equipo_modelo,
         equipo_variante, equipo_capacidad_texto, equipo_color, equipo_imei,
         equipo_numero_serie, equipo_tipo_producto_id, falla_reportada,
         comprobante_recepcion_generado_en, comprobante_final_generado_en,
         garantia_generada_en, actualizado_en)
    VALUES
        (%(codigo)s, %(origen)s, %(orden_origen_id)s, %(creada_en)s,
         %(estado_workflow)s, %(posicion_proceso)s, %(prioridad)s,
         %(referencia_rt)s, %(cliente_id)s, %(equipo_id)s,
         %(cliente_tipo_persona)s, %(cliente_nombre)s,
         %(cliente_documento_tipo)s, %(cliente_documento_numero)s,
         %(cliente_telefono)s, %(cliente_email)s,
         %(equipo_modelo_equipo_id)s, %(equipo_marca)s, %(equipo_modelo)s,
         %(equipo_variante)s, %(equipo_capacidad_texto)s, %(equipo_color)s,
         %(equipo_imei)s, %(equipo_numero_serie)s,
         %(equipo_tipo_producto_id)s, %(falla_reportada)s,
         %(comprobante_recepcion_generado_en)s,
         %(comprobante_final_generado_en)s, %(garantia_generada_en)s,
         %(actualizado_en)s)
    RETURNING id, version
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_ORDEN = consulta(
    "ordenes.actualizar",
    """
    UPDATE rma.orden SET
        estado_workflow = %(estado_workflow)s,
        posicion_proceso = %(posicion_proceso)s,
        prioridad = %(prioridad)s, referencia_rt = %(referencia_rt)s,
        cliente_id = %(cliente_id)s, equipo_id = %(equipo_id)s,
        cliente_tipo_persona = %(cliente_tipo_persona)s,
        cliente_nombre = %(cliente_nombre)s,
        cliente_documento_tipo = %(cliente_documento_tipo)s,
        cliente_documento_numero = %(cliente_documento_numero)s,
        cliente_telefono = %(cliente_telefono)s,
        cliente_email = %(cliente_email)s,
        equipo_modelo_equipo_id = %(equipo_modelo_equipo_id)s,
        equipo_marca = %(equipo_marca)s, equipo_modelo = %(equipo_modelo)s,
        equipo_variante = %(equipo_variante)s,
        equipo_capacidad_texto = %(equipo_capacidad_texto)s,
        equipo_color = %(equipo_color)s, equipo_imei = %(equipo_imei)s,
        equipo_numero_serie = %(equipo_numero_serie)s,
        equipo_tipo_producto_id = %(equipo_tipo_producto_id)s,
        falla_reportada = %(falla_reportada)s,
        comprobante_recepcion_generado_en =
            %(comprobante_recepcion_generado_en)s,
        comprobante_final_generado_en = %(comprobante_final_generado_en)s,
        garantia_generada_en = %(garantia_generada_en)s,
        actualizado_en = %(actualizado_en)s,
        cerrada_en = %(cerrada_en)s,
        version = version + 1
    WHERE id = %(id)s AND version = %(version)s
    RETURNING version
    """,
    modo=ESCRITURA,
)
_INSERTAR_DETALLE_ORIGEN = consulta(
    "ordenes.insertar_detalle_origen",
    """
    INSERT INTO rma.orden_detalle_origen
        (orden_id, orden_origen_id, detalle_id, posicion)
    VALUES (%(orden)s, %(origen)s, %(detalle)s, %(posicion)s)
    """,
    modo=ESCRITURA,
)
_INSERTAR_RECEPCION = consulta(
    "ordenes.insertar_recepcion",
    """
    INSERT INTO rma.recepcion
        (orden_id, registro, estado_fisico, accesorios, observaciones,
         notas_internas, checkin_ingreso, registrado_por, registrado_en,
         confirmada_por, confirmada_en, confirmacion_observaciones,
         no_recibido_por, no_recibido_en, no_recibido_motivo)
    VALUES
        (%(orden)s, %(registro)s, %(estado_fisico)s, %(accesorios)s,
         %(observaciones)s, %(notas_internas)s, %(checkin)s,
         %(registrado_por)s, %(registrado_en)s, %(confirmada_por)s,
         %(confirmada_en)s, %(confirmacion_observaciones)s,
         %(no_recibido_por)s, %(no_recibido_en)s, %(no_recibido_motivo)s)
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_RECEPCION = consulta(
    "ordenes.actualizar_recepcion",
    """
    UPDATE rma.recepcion SET
        registro = %(registro)s, estado_fisico = %(estado_fisico)s,
        accesorios = %(accesorios)s, observaciones = %(observaciones)s,
        notas_internas = %(notas_internas)s, checkin_ingreso = %(checkin)s,
        registrado_por = %(registrado_por)s,
        registrado_en = %(registrado_en)s,
        confirmada_por = %(confirmada_por)s,
        confirmada_en = %(confirmada_en)s,
        confirmacion_observaciones = %(confirmacion_observaciones)s,
        no_recibido_por = %(no_recibido_por)s,
        no_recibido_en = %(no_recibido_en)s,
        no_recibido_motivo = %(no_recibido_motivo)s
    WHERE orden_id = %(orden)s
    """,
    modo=ESCRITURA,
)
_INSERTAR_DETALLE = consulta(
    "ordenes.insertar_detalle",
    """
    INSERT INTO rma.detalle
        (orden_id, codigo, estado, condicion, control_estado,
         control_usuario_id, control_en, control_observaciones,
         garantia_dias, garantia_dias_sugerida, detalle_origen_id,
         observaciones, cancelacion_origen, cancelacion_motivo,
         cancelado_por, cancelado_en)
    VALUES
        (%(orden)s, %(codigo)s, %(estado)s, %(condicion)s,
         %(control_estado)s, %(control_usuario_id)s, %(control_en)s,
         %(control_observaciones)s, %(garantia_dias)s,
         %(garantia_dias_sugerida)s, %(detalle_origen_id)s,
         %(observaciones)s, %(cancelacion_origen)s, %(cancelacion_motivo)s,
         %(cancelado_por)s, %(cancelado_en)s)
    RETURNING id
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_DETALLE = consulta(
    "ordenes.actualizar_detalle",
    """
    UPDATE rma.detalle SET
        estado = %(estado)s, condicion = %(condicion)s,
        control_estado = %(control_estado)s,
        control_usuario_id = %(control_usuario_id)s,
        control_en = %(control_en)s,
        control_observaciones = %(control_observaciones)s,
        garantia_dias = %(garantia_dias)s,
        garantia_dias_sugerida = %(garantia_dias_sugerida)s,
        detalle_origen_id = %(detalle_origen_id)s,
        observaciones = %(observaciones)s,
        cancelacion_origen = %(cancelacion_origen)s,
        cancelacion_motivo = %(cancelacion_motivo)s,
        cancelado_por = %(cancelado_por)s, cancelado_en = %(cancelado_en)s
    WHERE id = %(id)s
    """,
    modo=ESCRITURA,
)
_INSERTAR_VERSION = consulta(
    "ordenes.insertar_version",
    """
    INSERT INTO rma.detalle_version
        (detalle_id, numero, tipo_reparacion_id, descripcion, precio,
         puntaje, garantia_dias, definida_por, definida_en,
         garantia_dias_reemplazada, reemplaza_a)
    VALUES
        (%(detalle)s, %(numero)s, %(tipo)s, %(descripcion)s, %(precio)s,
         %(puntaje)s, %(garantia_dias)s, %(definida_por)s, %(definida_en)s,
         %(garantia_dias_reemplazada)s, %(reemplaza_a)s)
    RETURNING id
    """,
    modo=ESCRITURA,
)
_INSERTAR_DECISION = consulta(
    "ordenes.insertar_decision",
    """
    INSERT INTO rma.decision_cliente
        (detalle_version_id, resultado, canal, usuario_id, registrada_en,
         observaciones, posicion)
    VALUES (%(version)s, %(resultado)s, %(canal)s, %(usuario)s,
            %(fecha)s, %(observaciones)s, %(posicion)s)
    """,
    modo=ESCRITURA,
)
_INSERTAR_AJUSTE = consulta(
    "ordenes.insertar_ajuste",
    """
    INSERT INTO rma.ajuste_garantia
        (detalle_id, dias_anteriores, dias_nuevos, motivo, usuario_id,
         registrado_en, posicion)
    VALUES (%(detalle)s, %(dias_anteriores)s, %(dias_nuevos)s, %(motivo)s,
            %(usuario)s, %(fecha)s, %(posicion)s)
    """,
    modo=ESCRITURA,
)
_INSERTAR_CONTROL = consulta(
    "ordenes.insertar_control",
    """
    INSERT INTO rma.control_tecnico
        (detalle_id, ejecucion_id, resultado, usuario_id, registrado_en,
         observaciones, posicion)
    VALUES (%(detalle)s, %(ejecucion)s, %(resultado)s, %(usuario)s,
            %(fecha)s, %(observaciones)s, %(posicion)s)
    """,
    modo=ESCRITURA,
)
_INSERTAR_TOMA = consulta(
    "ordenes.insertar_toma",
    """
    INSERT INTO rma.toma
        (codigo, orden_id, usuario_id, mesa_trabajo_id, estado, inicio, fin,
         liberada_por, motivo_liberacion, posicion)
    VALUES (%(codigo)s, %(orden)s, %(usuario)s, %(mesa)s, %(estado)s,
            %(inicio)s, %(fin)s, %(liberada_por)s, %(motivo)s, %(posicion)s)
    RETURNING id
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_TOMA = consulta(
    "ordenes.actualizar_toma",
    """
    UPDATE rma.toma SET estado = %(estado)s, fin = %(fin)s,
        liberada_por = %(liberada_por)s, motivo_liberacion = %(motivo)s
    WHERE id = %(id)s
    """,
    modo=ESCRITURA,
)
_INSERTAR_EJECUCION = consulta(
    "ordenes.insertar_ejecucion",
    """
    INSERT INTO rma.ejecucion
        (codigo, orden_id, detalle_id, detalle_version_id, toma_id,
         usuario_id, estado, inicio, fin, observaciones, motivo_interrupcion,
         motivo_redefinicion, posicion)
    VALUES (%(codigo)s, %(orden)s, %(detalle)s, %(version)s, %(toma)s,
            %(usuario)s, %(estado)s, %(inicio)s, %(fin)s, %(observaciones)s,
            %(motivo_interrupcion)s, %(motivo_redefinicion)s, %(posicion)s)
    RETURNING id
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_EJECUCION = consulta(
    "ordenes.actualizar_ejecucion",
    """
    UPDATE rma.ejecucion SET estado = %(estado)s, fin = %(fin)s,
        observaciones = %(observaciones)s,
        motivo_interrupcion = %(motivo_interrupcion)s,
        motivo_redefinicion = %(motivo_redefinicion)s
    WHERE id = %(id)s
    """,
    modo=ESCRITURA,
)
_INSERTAR_INSUMO_UTILIZADO = consulta(
    "ordenes.insertar_insumo_utilizado",
    """
    INSERT INTO rma.ejecucion_insumo
        (ejecucion_id, insumo_id, cantidad_utilizada, posicion)
    VALUES (%(ejecucion)s, %(insumo)s, %(cantidad)s, %(posicion)s)
    """,
    modo=ESCRITURA,
)
_INSERTAR_EVENTO = consulta(
    "ordenes.insertar_evento",
    """
    INSERT INTO rma.evento_negocio
        (orden_id, tipo_evento_id, accion_id, ocurrido_en, responsable_tipo,
         usuario_id, detalle_id, ejecucion_id, pago_id, observacion,
         historial_tipo_referencia, historial_referencia_id, historial_accion)
    VALUES (%(orden)s, %(tipo_evento)s, %(accion)s, %(fecha)s,
            %(responsable)s, %(usuario)s, %(detalle)s, %(ejecucion)s,
            %(pago)s, %(observacion)s, %(tipo_referencia)s,
            %(referencia_id)s, %(accion_historial)s)
    """,
    modo=ESCRITURA,
)


# --- Repository -----------------------------------------------------------


class PostgresOrdenReparacionRepository:
    """Implementa ``OrdenReparacionRepository`` sobre la base (A1 y A2)."""

    def __init__(self, unidad: UnidadDeTrabajoPostgres) -> None:
        self._unidad = unidad

    def obtener(self, orden_id: str) -> OrdenReparacion:
        cargadas = self._leer(
            FILTRO_UNA, {"codigo": orden_id}, lambda o: o.id == orden_id
        )
        if not cargadas:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe la Orden {orden_id}"
            )
        return cargadas[0]

    def listar(self) -> list[OrdenReparacion]:
        return self._leer(FILTRO_TODAS, {}, lambda o: True)

    def obtener_para_modificar(self, orden_id: str) -> OrdenReparacion:
        self._exigir_transaccion("Leer una Orden para modificarla")
        ejecutor = self._unidad.ejecutor()
        if ejecutor.fila(_BLOQUEAR, {"codigo": orden_id}) is None:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe la Orden {orden_id}"
            )
        instantanea = cargar_ordenes(ejecutor, [orden_id])[0]
        instantaneas = self._instantaneas()
        # Pedirla otra vez en el comando conserva la marca: lo que ya se
        # cargo sigue siendo la Orden de esta transaccion.
        anterior = instantaneas.get(orden_id)
        instantanea.marca = anterior.marca if anterior else uuid4().hex
        instantaneas[orden_id] = instantanea
        entregada = instantanea.orden.model_copy(deep=True)
        _marcar(entregada, instantanea.marca)
        return entregada

    def reservar_codigo(self) -> str:
        self._exigir_transaccion("Reservar un numero de Orden")
        ejecutor = self._unidad.ejecutor()
        # La secuencia nunca repite, pero una Orden pudo guardarse con un
        # numero explicito (importada o de prueba): ese no se devuelve.
        while True:
            codigo = ejecutor.fila(_SIGUIENTE_NUMERO).codigo
            if ejecutor.fila(_EXISTE, {"codigo": codigo}) is None:
                return codigo

    def guardar(self, orden: OrdenReparacion) -> None:
        with self._unidad.transaccion():
            ejecutor = self._unidad.ejecutor()
            instantaneas = self._instantaneas()
            previa = instantaneas.get(orden.id)
            if previa is None:
                _exigir_orden_nueva(ejecutor, orden)
            else:
                _exigir_procedencia(orden, previa)
            _exigir_partes_soportadas(orden)
            if previa is not None:
                if orden == previa.orden:
                    return  # idempotente: nada cambio
                if previa.orden.esta_cerrada:
                    raise ConflictoDeEscrituraError(
                        f"La Orden {orden.id} ya esta cerrada: no se modifica."
                    )
            guardado = _Guardado(self._unidad, ejecutor, orden, previa)
            instantaneas[orden.id] = guardado.escribir()

    # --- Consultas dedicadas de E2 (slice A5) -------------------------------

    def listar_abiertas(self) -> list[OrdenReparacion]:
        return self._leer(FILTRO_ABIERTAS, {}, lambda o: not o.esta_cerrada)

    def listar_por_dni_cliente(self, dni: str) -> list[OrdenReparacion]:
        # Con None coincidirian los clientes sin DNI en JSON (en SQL,
        # ninguno): se rechaza en las dos.
        if dni is None:
            raise ValueError("El DNI a buscar no puede ser None.")
        return self._leer(
            FILTRO_DNI,
            {"dni": dni},
            lambda o: o.cliente is not None and o.cliente.dni == dni,
        )

    def listar_con_reservas(
        self, insumo_ids: Collection[str] | None = None
    ) -> list[OrdenReparacion]:
        if isinstance(insumo_ids, str):
            # Un str tambien es Collection[str]: se tomaria letra por letra.
            raise ValueError(
                "insumo_ids es una coleccion de IDs, no un str: "
                f"usar [{insumo_ids!r}]."
            )
        buscados = None if insumo_ids is None else sorted(set(insumo_ids))
        if buscados == []:
            return []

        def con_reserva(orden: OrdenReparacion) -> bool:
            return any(
                m.tipo is TipoMovimientoInsumo.RESERVA
                and (buscados is None or m.insumo_id in buscados)
                for m in orden.movimientos_insumo
            )

        return self._leer(FILTRO_RESERVAS, {"claves": buscados}, con_reserva)

    def listar_con_movimientos(
        self, insumo_id: str | None = None
    ) -> list[OrdenReparacion]:
        return self._leer(
            FILTRO_MOVIMIENTOS,
            {"clave": insumo_id},
            lambda o: any(
                insumo_id is None or m.insumo_id == insumo_id
                for m in o.movimientos_insumo
            ),
        )

    def claves_de_fotos(self) -> frozenset[str]:
        # Una sola consulta: un solo instante. Las fotos solo crecen.
        with self._unidad.lectura() as lector:
            return claves_de_fotos(lector)

    # --- Lectura consistente (A5, QA-A2-M2) ---------------------------------

    def _leer(
        self,
        consulta_: Consulta,
        parametros: dict[str, Any],
        incluye: Callable[[OrdenReparacion], bool],
    ) -> list[OrdenReparacion]:
        """Las Ordenes que cumplen ``incluye``, por numero ascendente.

        ``consulta_`` (un filtro registrado) trae las candidatas de la
        base con su version; el resultado lo decide ``incluye``, como en
        JSON.
        """
        with self._unidad.lectura() as lector:
            if self._unidad.lectura_de_un_instante():
                codigos = [
                    f.codigo for f in lector.filas(consulta_, parametros)
                ]
                ordenes = [i.orden for i in cargar_ordenes(lector, codigos)]
                return [o for o in ordenes if incluye(o)]
            cargadas = self._cargar_sin_mezclar(lector, consulta_, parametros)
        return self._en_la_vista_del_comando(cargadas, incluye)

    def _cargar_sin_mezclar(
        self, lector, consulta_: Consulta, parametros: dict[str, Any]
    ) -> list[Instantanea]:
        """Una carga que no mezcla dos instantes de una Orden: la version
        de cada candidata es la misma al filtrar, al cargar y al terminar."""
        for _ in range(_INTENTOS_DE_LECTURA):
            versiones = {
                f.codigo: f.version
                for f in lector.filas(consulta_, parametros)
            }
            if not versiones:
                return []
            cargadas = cargar_ordenes(lector, sorted(versiones))
            finales = versiones_de(lector, sorted(versiones))
            if finales == versiones and all(
                i.version == versiones[i.orden.id] for i in cargadas
            ):
                return cargadas
        error = ConflictoDeEscrituraError(
            "Las Ordenes cambiaron mientras se leian: reintenta."
        )
        error.reintentable = True
        raise error

    def _en_la_vista_del_comando(
        self,
        cargadas: list[Instantanea],
        incluye: Callable[[OrdenReparacion], bool],
    ) -> list[OrdenReparacion]:
        """Cada Orden en una sola version por comando (QA-E2-1).

        Las que el comando bloqueo o escribio, como estan. Las demas, la
        primera version que leyo: tambien las que ya no pasan el filtro
        SQL, porque se evaluan sobre esa version.
        """
        propias = self._instantaneas()
        leidas: dict[str, OrdenReparacion] = (
            self._unidad.datos_de_transaccion().setdefault(_LEIDAS, {})
        )
        vista: dict[str, OrdenReparacion] = {}
        for instantanea in cargadas:
            orden = instantanea.orden
            if orden.id not in propias:
                orden = leidas.setdefault(orden.id, orden)
            vista[orden.id] = orden
        for codigo, orden in leidas.items():
            if codigo not in propias:
                vista.setdefault(codigo, orden)
        return [
            vista[codigo].model_copy(deep=True)
            for codigo in sorted(vista)
            if incluye(vista[codigo])
        ]

    # --- Interno -----------------------------------------------------------

    def _exigir_transaccion(self, operacion: str) -> None:
        if not self._unidad.en_curso():
            raise PersistenciaError(
                f"{operacion} exige una transaccion en curso: el caso de "
                "uso debe abrirla con contexto.transaccion()."
            )

    def _instantaneas(self) -> dict[str, Instantanea]:
        return self._unidad.datos_de_transaccion().setdefault(
            _INSTANTANEAS, {}
        )


def _marcar(orden: OrdenReparacion, marca: str) -> None:
    """Fuera de los campos: no cambia la igualdad ni lo que se serializa,
    y ``model_copy`` la conserva."""
    orden.__dict__[_MARCA] = marca


def _marca_de(orden: OrdenReparacion) -> str | None:
    return orden.__dict__.get(_MARCA)


def _sin_instantanea(orden: OrdenReparacion) -> PersistenciaError:
    return PersistenciaError(
        f"La Orden {orden.id} no es nueva y no viene de "
        "obtener_para_modificar en esta transaccion: no se guarda. El caso "
        "de uso debe modificarla con orden_para_modificar()."
    )


def _exigir_orden_nueva(ejecutor: EjecutorSql, orden: OrdenReparacion) -> None:
    """Sin instantanea solo se inserta. Una Orden con marca salio de otra:
    con otro codigo no pasa a ser un alta. Un alta simultanea del mismo
    codigo, que aca no se ve, la frena la unicidad al insertar."""
    if (
        _marca_de(orden) is not None
        or ejecutor.fila(_EXISTE, {"codigo": orden.id}) is not None
    ):
        raise _sin_instantanea(orden)


def _exigir_procedencia(orden: OrdenReparacion, previa: Instantanea) -> None:
    """Lo que llega salio de la instantanea de esa Orden. Una instantanea
    sin marca es de un alta de esta transaccion: esa fila no la pudo
    escribir nadie mas."""
    if previa.marca is not None and _marca_de(orden) != previa.marca:
        raise _sin_instantanea(orden)


def _exigir_partes_soportadas(orden: OrdenReparacion) -> None:
    """Lo que todavia no se guarda se rechaza; nunca se pierde."""
    sin_operacion = sorted(
        {
            m.tipo.value
            for m in orden.movimientos_insumo
            if m.tipo not in _TIPOS_DE_MOVIMIENTO
        }
    )
    if sin_operacion:
        raise PersistenciaError(
            f"La Orden {orden.id} tiene movimientos sin operacion habilitada "
            f"en el libro (DI-5): {', '.join(sin_operacion)}."
        )
    for nombre in ("comprobante_recepcion", "comprobante_final"):
        documento = getattr(orden.documentos, nombre)
        if documento.generado != (documento.fecha_generacion is not None):
            raise PersistenciaError(
                f"La marca {nombre} de la Orden {orden.id} no tiene fecha."
            )
    garantia = orden.documentos.garantia_reparacion
    if garantia.generado != (garantia.fecha_generacion is not None):
        raise PersistenciaError(
            f"La marca garantia_reparacion de la Orden {orden.id} no tiene "
            "fecha."
        )
    _exigir_representable(orden)


def _exigir_representable(orden: OrdenReparacion) -> None:
    """Lo que el esquema no puede reconstruir igual se rechaza: se perderia
    en silencio al releer."""
    recepcion = orden.recepcion
    if (
        recepcion
        and recepcion.registros_checkin
        and recepcion.datos.checkin
        is not recepcion.registros_checkin[-1].realizado
    ):
        raise PersistenciaError(
            f"La Orden {orden.id}: el check-in vigente no es el del ultimo "
            "registro."
        )
    entregada = orden.estado_workflow is EstadoWorkflow.ENTREGADA
    if (orden.entrega is not None and not entregada) or (
        orden.devolucion is not None and entregada
    ):
        raise PersistenciaError(
            f"La Orden {orden.id}: la salida del equipo no corresponde al "
            f"estado {orden.estado_workflow.value}."
        )
    for documento in orden.documentos.emitidos:
        if documento.orden_id != orden.id:
            raise PersistenciaError(
                f"El documento {documento.id} es de la Orden "
                f"{documento.orden_id}, no de {orden.id}."
            )


# --- Guardado ---------------------------------------------------------------


class _Guardado:
    """Un ``guardar``: compara ``orden`` con ``previa`` y escribe."""

    def __init__(
        self,
        unidad: UnidadDeTrabajoPostgres,
        ejecutor: EjecutorSql,
        orden: OrdenReparacion,
        previa: Instantanea | None,
    ) -> None:
        self._unidad = unidad
        self._ej = ejecutor
        self._orden = orden
        self._previa = previa
        self._ids: dict[str, dict[str, UUID]] = {}
        self._detalles = dict(previa.detalles) if previa else {}
        self._versiones = (
            {k: list(v) for k, v in previa.versiones.items()} if previa else {}
        )
        self._tomas = dict(previa.tomas) if previa else {}
        self._ejecuciones = dict(previa.ejecuciones) if previa else {}
        self._documentos = dict(previa.documentos) if previa else {}
        self._pagos = dict(previa.pagos) if previa else {}
        self._movimientos = dict(previa.movimientos) if previa else {}
        self._checkin_ingreso = previa.checkin_ingreso if previa else None

    # --- Flujo ---------------------------------------------------------------

    def escribir(self) -> Instantanea:
        orden, previa = self._orden, self._previa
        self._resolver_referencias()
        cliente_id = self._cliente()
        equipo_id = self._equipo()
        raiz = self._raiz(cliente_id, equipo_id)
        if previa is None:
            fila = self._ej.fila(
                _INSERTAR_ORDEN,
                {
                    **raiz,
                    "codigo": orden.id,
                    "origen": orden.origen.value,
                    "orden_origen_id": self._id_orden_origen(),
                    "creada_en": orden.created_at,
                },
            )
            orden_id, version = fila.id, fila.version
            self._detalles_origen(orden_id)
        else:
            orden_id, version = previa.id, previa.version
            if orden.origen != previa.orden.origen or (
                orden.orden_origen_id != previa.orden.orden_origen_id
            ):
                self._inmutable("el origen de la Orden")
            if orden.detalles_origen_ids != previa.orden.detalles_origen_ids:
                self._inmutable("los Detalles de origen")
            if orden.created_at != previa.orden.created_at:
                self._inmutable("la fecha de alta")
        self._recepcion(orden_id)
        self._todos_los_detalles(orden_id)
        self._todas_las_tomas(orden_id)
        self._todas_las_ejecuciones(orden_id)
        self._todos_los_controles()
        self._movimientos_de(orden_id)
        verificar_stock_esperado(self._unidad, self._ej)
        self._fotos(orden_id)
        self._documentos_emitidos(orden_id)
        self._salida(orden_id)
        self._pagos_de(orden_id)
        self._devoluciones(orden_id)
        self._descuentos(orden_id)
        self._historial(orden_id)
        # La raiz va al final: si este guardar cierra la Orden, nada se
        # inserta despues del cierre (diseno fisico, regla 9).
        cerrada_en = orden.updated_at if orden.esta_cerrada else None
        if previa is None:
            if cerrada_en is not None:
                version = self._actualizar_raiz(
                    orden_id, version, raiz, cerrada_en
                )
        else:
            version = self._actualizar_raiz(
                orden_id, version, raiz, cerrada_en
            )
        return Instantanea(
            orden=orden.model_copy(deep=True),
            id=orden_id,
            version=version,
            cliente=cliente_id,
            equipo=equipo_id,
            detalles=self._detalles,
            versiones=self._versiones,
            tomas=self._tomas,
            ejecuciones=self._ejecuciones,
            tiene_recepcion=orden.recepcion is not None,
            checkin_ingreso=self._checkin_ingreso,
            documentos=self._documentos,
            pagos=self._pagos,
            movimientos=self._movimientos,
            marca=previa.marca if previa else None,
        )

    def _actualizar_raiz(
        self,
        orden_id: UUID,
        version: int,
        raiz: dict[str, Any],
        cerrada_en: datetime | None,
    ) -> int:
        fila = self._ej.fila(
            _ACTUALIZAR_ORDEN,
            {
                **raiz,
                "id": orden_id,
                "version": version,
                "cerrada_en": cerrada_en,
            },
        )
        if fila is None:
            raise ConflictoDeEscrituraError(
                f"La Orden {self._orden.id} cambio mientras se modificaba "
                f"(se leyo la version {version})."
            )
        return fila.version

    # --- Errores -------------------------------------------------------------

    def _inmutable(self, que: str) -> None:
        """Cambio algo que ya estaba guardado y no cambia (DA-1)."""
        raise PersistenciaError(
            f"La Orden {self._orden.id}: cambio {que}, que ya estaba "
            "guardado y es inmutable."
        )

    def _exigir_prefijo(self, que: str, previas: list, nuevas: list) -> list:
        """Las entradas nuevas de una lista que solo crece."""
        if nuevas[: len(previas)] != previas:
            self._inmutable(que)
        return nuevas[len(previas) :]

    def _con_posicion(
        self, que: str, previas: list, nuevas: list
    ) -> Iterator[tuple[int, Any]]:
        """Las entradas nuevas de una lista, con su lugar en ella."""
        agregadas = self._exigir_prefijo(que, previas, nuevas)
        return enumerate(agregadas, len(previas) + 1)

    # --- Referencias ---------------------------------------------------------

    def _resolver_referencias(self) -> None:
        orden = self._orden
        usuarios: set[str] = set()
        tipos: set[str] = set()
        insumos: set[str] = set()
        recepcion = orden.recepcion
        if recepcion:
            usuarios.add(recepcion.registrado_por)
            if recepcion.confirmacion:
                usuarios.add(recepcion.confirmacion.usuario_id)
            if recepcion.no_recibido:
                usuarios.add(recepcion.no_recibido.usuario_id)
            for version in recepcion.versiones_anteriores:
                usuarios.update(
                    (version.registrado_por, version.reemplazado_por)
                )
            usuarios.update(n.usuario_id for n in recepcion.notas)
            usuarios.update(c.usuario_id for c in recepcion.registros_checkin)
        usuarios.update(f.usuario_id for f in orden.fotos)
        usuarios.update(
            d.usuario_id for d in orden.documentos.emitidos if d.usuario_id
        )
        salida = orden.entrega or orden.devolucion
        if salida:
            usuarios.add(salida.entregado_por)
        for detalle in orden.reparaciones_detail:
            tipos.add(detalle.tipo_reparacion_id)
            for anterior in detalle.definiciones_anteriores:
                tipos.add(anterior.tipo_reparacion_id)
                usuarios.add(anterior.usuario_id)
            if detalle.control_usuario_id:
                usuarios.add(detalle.control_usuario_id)
            if detalle.cancelacion:
                usuarios.add(detalle.cancelacion.usuario_id)
            usuarios.update(a.usuario_id for a in detalle.autorizaciones)
            usuarios.update(a.usuario_id for a in detalle.ajustes_garantia)
            usuarios.update(c.usuario_id for c in detalle.controles)
        for toma in orden.tomas:
            usuarios.add(toma.usuario_id)
            if toma.liberada_por:
                usuarios.add(toma.liberada_por)
        for ejecucion in orden.ejecuciones:
            usuarios.add(ejecucion.usuario_id)
            insumos.update(i.insumo_id for i in ejecucion.insumos_utilizados)
        for movimiento in orden.movimientos_insumo:
            insumos.add(movimiento.insumo_id)
            if movimiento.usuario_id:
                usuarios.add(movimiento.usuario_id)
        usuarios.update(p.usuario_id for p in orden.historial if p.usuario_id)
        resumen = orden.resumen_pago
        medios = {p.metodo for p in resumen.pagos}
        medios.update(d.medio for d in resumen.devoluciones)
        for pago in resumen.pagos:
            usuarios.add(pago.usuario_id)
            if pago.anulacion:
                usuarios.add(pago.anulacion.usuario_id)
        usuarios.update(d.usuario_id for d in resumen.devoluciones)
        usuarios.update(d.usuario_id for d in orden.descuentos)
        pedidos = {
            "usuario": usuarios,
            "tipo_reparacion": tipos,
            "mesa_trabajo": {toma.estacion_id for toma in orden.tomas},
            "insumo": insumos,
            "modelo_equipo": {orden.equipo.modelo_tecnico_id} - {None},
            "orden": {orden.orden_origen_id} - {None},
            "medio_pago": medios,
        }
        for tabla, codigos in pedidos.items():
            encontrados = {
                fila.codigo: fila.id
                for fila in (
                    self._ej.filas(_IDS[tabla], {"codigos": sorted(codigos)})
                    if codigos
                    else []
                )
            }
            faltan = sorted(set(codigos) - set(encontrados))
            if faltan:
                raise PersistenciaError(
                    f"La Orden {orden.id} referencia en {tabla} codigos que "
                    f"no existen en la base: {', '.join(faltan)}."
                )
            self._ids[tabla] = encontrados

    def _id(self, tabla: str, codigo: str | None) -> UUID | None:
        return None if codigo is None else self._ids[tabla][codigo]

    def _id_orden_origen(self) -> UUID | None:
        return self._id("orden", self._orden.orden_origen_id)

    # --- Cliente y equipo ----------------------------------------------------

    def _cliente(self) -> UUID | None:
        cliente = self._orden.cliente
        previa = self._previa
        if cliente is None:
            return None
        if previa is not None and previa.orden.cliente == cliente:
            return previa.cliente
        # Cliente compartido (DA-8): se mantiene con los datos de la copia
        # mas reciente; la Orden conserva su propia copia.
        fila = self._ej.fila(_CLIENTE, {"codigo": cliente.id})
        datos = {
            "nombre": cliente.nombre_apellido,
            "telefono": cliente.telefono,
            "email": cliente.email,
        }
        if fila is None:
            # A3-3: otra alta simultanea pudo crear el mismo cliente nuevo.
            # El INSERT espera a que confirme y no hace nada; se relee
            # bloqueado y sigue como un cliente existente.
            nuevo = self._ej.fila(
                _INSERTAR_CLIENTE, {"codigo": cliente.id, **datos}
            )
            if nuevo is None:
                fila = self._ej.fila(_CLIENTE, {"codigo": cliente.id})
        if fila is None:
            cliente_id = nuevo.id
        else:
            cliente_id = fila.id
            if (fila.nombre, fila.telefono, fila.email) != tuple(
                datos.values()
            ):
                self._ej.ejecutar(
                    _ACTUALIZAR_CLIENTE, {"id": cliente_id, **datos}
                )
        self._documento(cliente_id, cliente.dni)
        return cliente_id

    def _documento(self, cliente_id: UUID, dni: str | None) -> None:
        tipo = self._ej.fila(_TIPO_DNI)
        vigente = self._ej.fila(
            _DOCUMENTO_VIGENTE, {"cliente": cliente_id, "tipo": tipo.id}
        )
        if vigente is not None and vigente.numero_normalizado == dni:
            return
        if vigente is not None:
            self._ej.ejecutar(_CERRAR_DOCUMENTO, {"id": vigente.id})
        if dni:
            self._ej.ejecutar(
                _INSERTAR_DOCUMENTO,
                {
                    "cliente": cliente_id,
                    "tipo": tipo.id,
                    "exige": tipo.exige_unicidad,
                    "numero": dni,
                },
            )

    def _equipo(self) -> UUID:
        equipo = self._orden.equipo
        previa = self._previa
        if previa is not None and previa.orden.equipo == equipo:
            return previa.equipo
        datos = {
            "imei": equipo.imei,
            "numero_serie": equipo.numero_serie,
            "modelo": self._id("modelo_equipo", equipo.modelo_tecnico_id),
            "capacidad": equipo.capacidad,
            "color": equipo.color,
        }
        fila = self._ej.fila(_EQUIPO, {"codigo": equipo.id})
        if fila is None:
            # A3-3, como el cliente: el de otra alta simultanea se relee.
            nuevo = self._ej.fila(
                _INSERTAR_EQUIPO, {"codigo": equipo.id, **datos}
            )
            if nuevo is not None:
                return nuevo.id
            fila = self._ej.fila(_EQUIPO, {"codigo": equipo.id})
        actuales = (
            fila.imei,
            fila.numero_serie,
            fila.modelo_equipo_id,
            fila.capacidad_texto,
            fila.color,
        )
        if actuales != tuple(datos.values()):
            self._ej.ejecutar(_ACTUALIZAR_EQUIPO, {"id": fila.id, **datos})
        return fila.id

    # --- Raiz ----------------------------------------------------------------

    def _raiz(
        self, cliente_id: UUID | None, equipo_id: UUID
    ) -> dict[str, Any]:
        orden = self._orden
        cliente, equipo, documentos = (
            orden.cliente,
            orden.equipo,
            orden.documentos,
        )
        return {
            "estado_workflow": orden.estado_workflow.value,
            "posicion_proceso": orden.current_process,
            "prioridad": orden.prioridad,
            "referencia_rt": orden.referencia_rt,
            "cliente_id": cliente_id,
            "equipo_id": equipo_id,
            "cliente_tipo_persona": "FISICA" if cliente else None,
            "cliente_nombre": cliente.nombre_apellido if cliente else None,
            "cliente_documento_tipo": (
                "DNI" if cliente and cliente.dni else None
            ),
            "cliente_documento_numero": cliente.dni if cliente else None,
            "cliente_telefono": cliente.telefono if cliente else None,
            "cliente_email": cliente.email if cliente else None,
            "equipo_modelo_equipo_id": self._id(
                "modelo_equipo", equipo.modelo_tecnico_id
            ),
            "equipo_marca": equipo.marca,
            "equipo_modelo": equipo.modelo,
            "equipo_variante": equipo.variante,
            "equipo_capacidad_texto": equipo.capacidad,
            "equipo_color": equipo.color,
            "equipo_imei": equipo.imei,
            "equipo_numero_serie": equipo.numero_serie,
            "equipo_tipo_producto_id": equipo.tipo_producto_id,
            "falla_reportada": equipo.falla_reportada,
            "comprobante_recepcion_generado_en": (
                documentos.comprobante_recepcion.fecha_generacion
            ),
            "comprobante_final_generado_en": (
                documentos.comprobante_final.fecha_generacion
            ),
            "garantia_generada_en": (
                documentos.garantia_reparacion.fecha_generacion
            ),
            "actualizado_en": orden.updated_at,
        }

    def _detalles_origen(self, orden_id: UUID) -> None:
        orden = self._orden
        if not orden.detalles_origen_ids:
            return
        origen = self._id_orden_origen()
        if origen is None:
            raise PersistenciaError(
                f"La Orden {orden.id} tiene Detalles de origen sin Orden de "
                "origen."
            )
        for posicion, codigo in enumerate(orden.detalles_origen_ids, 1):
            self._ej.ejecutar(
                _INSERTAR_DETALLE_ORIGEN,
                {
                    "orden": orden_id,
                    "origen": origen,
                    "detalle": self._detalle_de_origen(codigo),
                    "posicion": posicion,
                },
            )

    def _detalle_de_origen(self, codigo: str | None) -> UUID | None:
        if codigo is None:
            return None
        origen = self._id_orden_origen()
        fila = (
            self._ej.fila(
                _DETALLE_DE_ORDEN, {"orden": origen, "codigo": codigo}
            )
            if origen
            else None
        )
        if fila is None:
            raise PersistenciaError(
                f"La Orden {self._orden.id} referencia el Detalle de origen "
                f"{codigo}, que no existe."
            )
        return fila.id

    # --- Recepcion -----------------------------------------------------------

    def _recepcion(self, orden_id: UUID) -> None:
        recepcion = self._orden.recepcion
        previa = self._previa.orden.recepcion if self._previa else None
        if recepcion is None:
            if previa is not None:
                self._inmutable("la recepcion (no se borra)")
            return
        guardado = self._checkin_ingreso
        # Con registros, el check-in vigente va a rma.checkin: el del ingreso
        # queda como estaba. Sin registros, es el de los datos.
        if not recepcion.registros_checkin:
            self._checkin_ingreso = recepcion.datos.checkin
        fila = _fila_recepcion(recepcion, self._checkin_ingreso)
        cambio = previa is None or fila != _fila_recepcion(previa, guardado)
        if cambio and previa is not None and previa.decidida:
            self._inmutable("la recepcion ya decidida")
        if cambio:
            self._ej.ejecutar(
                _ACTUALIZAR_RECEPCION if previa else _INSERTAR_RECEPCION,
                {
                    **fila,
                    "orden": orden_id,
                    **{
                        columna: self._id("usuario", fila[columna])
                        for columna in (
                            "registrado_por",
                            "confirmada_por",
                            "no_recibido_por",
                        )
                    },
                },
            )
        self._historia_de_recepcion(orden_id, recepcion, previa)

    def _historia_de_recepcion(
        self,
        orden_id: UUID,
        recepcion: RecepcionEquipo,
        previa: RecepcionEquipo | None,
    ) -> None:
        for posicion, version in self._con_posicion(
            "las versiones de la recepcion",
            previa.versiones_anteriores if previa else [],
            recepcion.versiones_anteriores,
        ):
            self._ej.ejecutar(
                _INSERTAR_VERSION_RECEPCION,
                {
                    "orden": orden_id,
                    "datos": _json(
                        {
                            "equipo": _dominio_json(version.equipo),
                            "datos": _dominio_json(version.datos),
                        }
                    ),
                    "registrado_por": self._id(
                        "usuario", version.registrado_por
                    ),
                    "registrado_en": version.registrado_en,
                    "reemplazado_por": self._id(
                        "usuario", version.reemplazado_por
                    ),
                    "reemplazado_en": version.reemplazado_en,
                    "posicion": posicion,
                },
            )
        for posicion, nota in self._con_posicion(
            "las notas de la recepcion",
            previa.notas if previa else [],
            recepcion.notas,
        ):
            self._ej.ejecutar(
                _INSERTAR_NOTA_RECEPCION,
                {
                    "orden": orden_id,
                    "texto": nota.texto,
                    "interna": nota.interna,
                    "usuario": self._id("usuario", nota.usuario_id),
                    "fecha": nota.fecha,
                    "posicion": posicion,
                },
            )
        for posicion, registro in self._con_posicion(
            "los registros de check-in",
            previa.registros_checkin if previa else [],
            recepcion.registros_checkin,
        ):
            self._ej.ejecutar(
                _INSERTAR_CHECKIN,
                {
                    "orden": orden_id,
                    "realizado": registro.realizado,
                    "usuario": self._id("usuario", registro.usuario_id),
                    "fecha": registro.fecha,
                    "posicion": posicion,
                },
            )

    # --- Fotos, documentos y salida ------------------------------------------

    def _fotos(self, orden_id: UUID) -> None:
        for posicion, foto in self._con_posicion(
            "las fotos",
            self._previa.orden.fotos if self._previa else [],
            self._orden.fotos,
        ):
            self._ej.ejecutar(
                _INSERTAR_FOTO,
                {
                    "codigo": foto.id,
                    "orden": orden_id,
                    "objeto": foto.objeto,
                    "tipo": foto.tipo_contenido,
                    "tamano": foto.tamano_bytes,
                    "nombre": foto.nombre_original,
                    "usuario": self._id("usuario", foto.usuario_id),
                    "fecha": foto.fecha,
                    "posicion": posicion,
                },
            )

    def _documentos_emitidos(self, orden_id: UUID) -> None:
        for posicion, documento in self._con_posicion(
            "los documentos emitidos",
            self._previa.orden.documentos.emitidos if self._previa else [],
            self._orden.documentos.emitidos,
        ):
            reemplaza = documento.reemplaza_a
            if reemplaza is not None and reemplaza not in self._documentos:
                raise PersistenciaError(
                    f"El documento {documento.id} reemplaza a {reemplaza}, "
                    f"que la Orden {self._orden.id} no tiene."
                )
            self._documentos[documento.id] = self._ej.fila(
                _INSERTAR_DOCUMENTO_EMITIDO,
                {
                    "codigo": documento.id,
                    "orden": orden_id,
                    "tipo": documento.tipo.value,
                    "version": documento.version,
                    "fecha": documento.fecha_emision,
                    "usuario": self._id("usuario", documento.usuario_id),
                    "motivo": documento.motivo,
                    "reemplaza": self._documentos.get(reemplaza),
                    "contenido": _json(_dominio_json(documento.contenido)),
                    "posicion": posicion,
                },
            ).id

    def _salida(self, orden_id: UUID) -> None:
        salida = self._orden.entrega or self._orden.devolucion
        previa = (
            self._previa.orden.entrega or self._previa.orden.devolucion
            if self._previa
            else None
        )
        if salida == previa:
            return
        if previa is not None:
            self._inmutable("la salida del equipo")
        self._ej.ejecutar(
            _INSERTAR_SALIDA,
            {
                "orden": orden_id,
                "tipo": salida.tipo.value,
                "entregado_por": self._id("usuario", salida.entregado_por),
                "recibido_por": salida.recibido_por,
                "identificacion": salida.identificacion_receptor,
                "fecha": salida.fecha,
                "observaciones": salida.observaciones,
            },
        )

    # --- Movimientos de insumo (A6) -----------------------------------------

    def _movimientos_de(self, orden_id: UUID) -> None:
        """Solo crecen. Sus insumos se bloquean antes, por ``clave`` (DI-2);
        el trigger del libro aplica el stock y rechaza un disponible
        negativo."""
        nuevos = list(
            self._con_posicion(
                "los movimientos de insumo",
                self._previa.orden.movimientos_insumo if self._previa else [],
                self._orden.movimientos_insumo,
            )
        )
        if not nuevos:
            return
        bloquear_insumos(self._ej, {m.insumo_id for _, m in nuevos})
        accion = self._accion(orden_id)
        for posicion, movimiento in nuevos:
            detalle = movimiento.reparacion_detail_id
            if detalle not in self._detalles:
                raise PersistenciaError(
                    f"El movimiento {movimiento.id} es de un Detalle que la "
                    f"Orden {self._orden.id} no tiene: {detalle}."
                )
            origen = movimiento.movimiento_origen_id
            if origen is not None and origen not in self._movimientos:
                raise PersistenciaError(
                    f"El movimiento {movimiento.id} referencia {origen}, que "
                    f"la Orden {self._orden.id} no tiene."
                )
            self._movimientos[movimiento.id] = self._ej.fila(
                _INSERTAR_MOVIMIENTO,
                {
                    "codigo": movimiento.id,
                    "tipo": movimiento.tipo.value,
                    "insumo": self._id("insumo", movimiento.insumo_id),
                    "cantidad": _escala(
                        movimiento.cantidad, _TRES_DECIMALES, "cantidad"
                    ),
                    "orden": orden_id,
                    "detalle": self._detalles[detalle],
                    "ejecucion": self._ejecucion_de(movimiento.ejecucion_id),
                    "origen": self._movimientos.get(origen),
                    "observacion": movimiento.observacion,
                    "usuario": self._id("usuario", movimiento.usuario_id),
                    "accion": accion,
                    "fecha": movimiento.fecha,
                    "posicion": posicion,
                },
            ).id

    def _accion(self, orden_id: UUID) -> UUID:
        """La accion del comando (DA-3): la del primer paso nuevo del
        historial o, sin pasos, un proceso del sistema."""
        previos = self._previa.orden.historial if self._previa else []
        nuevos = self._orden.historial[len(previos) :]
        primero = nuevos[0] if nuevos else None
        return accion_del_comando(
            self._unidad,
            self._ej,
            operacion=primero.referencia_id if primero else "INVENTARIO",
            usuario=self._id("usuario", primero.usuario_id)
            if primero
            else None,
            orden=orden_id,
        )

    # --- Finanzas (A3) -------------------------------------------------------

    def _pagos_de(self, orden_id: UUID) -> None:
        """Los Pagos solo crecen; de uno guardado solo cambia su anulacion,
        una vez (``pago_validar``)."""
        previos = self._previa.orden.resumen_pago.pagos if self._previa else []
        pagos = self._orden.resumen_pago.pagos
        self._exigir_prefijo(
            "los pagos", [p.id for p in previos], [p.id for p in pagos]
        )
        for anterior, pago in zip(previos, pagos):
            if pago == anterior:
                continue
            if (
                anterior.anulacion is not None
                or pago.model_copy(update={"anulacion": None}) != anterior
            ):
                self._inmutable(f"el pago {pago.id}")
            self._ej.ejecutar(
                _ANULAR_PAGO,
                {**self._anulacion(pago), "id": self._pagos[pago.id]},
            )
        for posicion, pago in enumerate(
            pagos[len(previos) :], len(previos) + 1
        ):
            self._pagos[pago.id] = self._ej.fila(
                _INSERTAR_PAGO,
                {
                    **self._anulacion(pago),
                    "codigo": pago.id,
                    "orden": orden_id,
                    "monto": _escala(pago.monto, _DOS_DECIMALES, "importe"),
                    "tipo": pago.tipo_pago.value,
                    "medio": self._id("medio_pago", pago.metodo),
                    "referencia": pago.referencia,
                    "usuario": self._id("usuario", pago.usuario_id),
                    "fecha": pago.fecha,
                    "operacion": pago.operacion_id,
                    "posicion": posicion,
                },
            ).id

    def _anulacion(self, pago: Pago) -> dict[str, Any]:
        anulacion = pago.anulacion
        return {
            "anulado_por": self._id(
                "usuario", anulacion.usuario_id if anulacion else None
            ),
            "anulado_en": anulacion.fecha if anulacion else None,
            "anulacion_motivo": anulacion.motivo if anulacion else None,
        }

    def _pago_de(self, codigo: str | None) -> UUID | None:
        if codigo is None:
            return None
        if codigo not in self._pagos:
            raise PersistenciaError(
                f"La Orden {self._orden.id} referencia el pago {codigo}, que "
                "no tiene."
            )
        return self._pagos[codigo]

    def _devoluciones(self, orden_id: UUID) -> None:
        for posicion, devolucion in self._con_posicion(
            "las devoluciones de dinero",
            self._previa.orden.resumen_pago.devoluciones
            if self._previa
            else [],
            self._orden.resumen_pago.devoluciones,
        ):
            self._ej.ejecutar(
                _INSERTAR_DEVOLUCION_DINERO,
                {
                    "codigo": devolucion.id,
                    "orden": orden_id,
                    "pago": self._pago_de(devolucion.pago_id),
                    "monto": _escala(
                        devolucion.monto, _DOS_DECIMALES, "importe"
                    ),
                    "medio": self._id("medio_pago", devolucion.medio),
                    "motivo": devolucion.motivo,
                    "referencia": devolucion.referencia,
                    "usuario": self._id("usuario", devolucion.usuario_id),
                    "fecha": devolucion.fecha,
                    "operacion": devolucion.operacion_id,
                    "posicion": posicion,
                },
            )

    def _descuentos(self, orden_id: UUID) -> None:
        for posicion, registro in self._con_posicion(
            "los descuentos",
            self._previa.orden.descuentos if self._previa else [],
            self._orden.descuentos,
        ):
            self._ej.ejecutar(
                _INSERTAR_DESCUENTO,
                {
                    "orden": orden_id,
                    "tipo": registro.tipo.value if registro.tipo else None,
                    "valor": (
                        None
                        if registro.valor is None
                        else _escala(
                            registro.valor, _DOS_DECIMALES, "descuento"
                        )
                    ),
                    "motivo": registro.motivo,
                    "usuario": self._id("usuario", registro.usuario_id),
                    "fecha": registro.fecha,
                    "posicion": posicion,
                },
            )

    # --- Detalles ------------------------------------------------------------

    def _todos_los_detalles(self, orden_id: UUID) -> None:
        previos = (
            {d.id: d for d in self._previa.orden.reparaciones_detail}
            if self._previa
            else {}
        )
        codigos = [d.id for d in self._orden.reparaciones_detail]
        self._exigir_prefijo("los Detalles", list(previos), codigos)
        for detalle in self._orden.reparaciones_detail:
            anterior = previos.get(detalle.id)
            if anterior is None:
                self._detalles[detalle.id] = self._ej.fila(
                    _INSERTAR_DETALLE, self._fila_detalle(detalle, orden_id)
                ).id
                self._versiones[detalle.id] = []
            elif self._columnas_detalle(detalle) != self._columnas_detalle(
                anterior
            ):
                self._ej.ejecutar(
                    _ACTUALIZAR_DETALLE,
                    {
                        **self._fila_detalle(detalle, orden_id),
                        "id": self._detalles[detalle.id],
                    },
                )
            self._versiones_de(detalle, anterior)
            self._decisiones(detalle, anterior)
            self._ajustes(detalle, anterior)

    @staticmethod
    def _columnas_detalle(detalle: ReparacionDetail) -> tuple:
        return (
            detalle.estado,
            detalle.condicion,
            detalle.control_estado,
            detalle.control_usuario_id,
            detalle.control_fecha,
            detalle.control_observaciones,
            detalle.garantia_dias,
            detalle.garantia_dias_sugerida,
            detalle.detalle_origen_id,
            detalle.observaciones,
            detalle.cancelacion,
        )

    def _fila_detalle(
        self, detalle: ReparacionDetail, orden_id: UUID
    ) -> dict[str, Any]:
        cancelacion = detalle.cancelacion
        return {
            "orden": orden_id,
            "codigo": detalle.id,
            "estado": detalle.estado.value,
            "condicion": detalle.condicion.value,
            "control_estado": detalle.control_estado.value,
            "control_usuario_id": self._id(
                "usuario", detalle.control_usuario_id
            ),
            "control_en": detalle.control_fecha,
            "control_observaciones": detalle.control_observaciones,
            "garantia_dias": detalle.garantia_dias,
            "garantia_dias_sugerida": detalle.garantia_dias_sugerida,
            "detalle_origen_id": self._detalle_de_origen(
                detalle.detalle_origen_id
            ),
            "observaciones": detalle.observaciones,
            "cancelacion_origen": (
                cancelacion.origen.value if cancelacion else None
            ),
            "cancelacion_motivo": cancelacion.motivo if cancelacion else None,
            "cancelado_por": self._id(
                "usuario", cancelacion.usuario_id if cancelacion else None
            ),
            "cancelado_en": cancelacion.fecha if cancelacion else None,
        }

    def _versiones_de(
        self, detalle: ReparacionDetail, anterior: ReparacionDetail | None
    ) -> None:
        """La version k es la definicion k; quien y cuando la reemplazo, y
        con que garantia quedo, se guardan en la k+1 (inmutables)."""
        anteriores = detalle.definiciones_anteriores
        guardadas = len(self._versiones[detalle.id])
        if anterior is not None:
            previas = anterior.definiciones_anteriores
            self._exigir_prefijo(
                f"las definiciones anteriores de {detalle.id}",
                previas,
                anteriores,
            )
            if len(anteriores) == len(previas):
                if _definicion(detalle) != _definicion(anterior):
                    self._inmutable(
                        f"la definicion vigente de {detalle.id} sin una "
                        "version nueva"
                    )
                return
            # La vigente guardada paso a ser la anterior agregada.
            reemplazada = anteriores[len(previas)]
            if (
                reemplazada.tipo_reparacion_id,
                reemplazada.precio,
                reemplazada.puntaje,
            ) != _definicion(anterior)[:3]:
                self._inmutable(
                    f"la definicion reemplazada de {detalle.id} no es la que "
                    "estaba vigente"
                )
        for numero in range(guardadas + 1, len(anteriores) + 2):
            if numero <= len(anteriores):
                definicion = anteriores[numero - 1]
                tipo = definicion.tipo_reparacion_id
                valores = (None, definicion.precio, definicion.puntaje)
                garantia = definicion.garantia_dias
            else:
                tipo = detalle.tipo_reparacion_id
                valores = (
                    detalle.descripcion,
                    detalle.precio,
                    detalle.puntaje,
                )
                garantia = detalle.garantia_dias
            reemplazo = anteriores[numero - 2] if numero >= 2 else None
            ids = self._versiones[detalle.id]
            ids.append(
                self._ej.fila(
                    _INSERTAR_VERSION,
                    {
                        "detalle": self._detalles[detalle.id],
                        "numero": numero,
                        "tipo": self._id("tipo_reparacion", tipo),
                        "descripcion": valores[0],
                        "precio": _escala(
                            valores[1], _DOS_DECIMALES, "precio"
                        ),
                        "puntaje": valores[2],
                        "garantia_dias": garantia,
                        "definida_por": self._id(
                            "usuario",
                            reemplazo.usuario_id if reemplazo else None,
                        ),
                        "definida_en": (
                            reemplazo.reemplazada_en
                            if reemplazo
                            else self._orden.created_at
                        ),
                        "garantia_dias_reemplazada": (
                            reemplazo.garantia_dias if reemplazo else None
                        ),
                        "reemplaza_a": ids[-1] if ids else None,
                    },
                ).id
            )

    def _decisiones(
        self, detalle: ReparacionDetail, anterior: ReparacionDetail | None
    ) -> None:
        previas = anterior.autorizaciones if anterior else []
        nuevas = self._exigir_prefijo(
            f"las decisiones del cliente de {detalle.id}",
            previas,
            detalle.autorizaciones,
        )
        versiones = self._versiones[detalle.id]
        for posicion, decision in enumerate(nuevas, len(previas) + 1):
            if not 1 <= decision.version_definicion <= len(versiones):
                raise PersistenciaError(
                    f"La decision del cliente de {detalle.id} es de la "
                    f"version {decision.version_definicion}, que no existe."
                )
            self._ej.ejecutar(
                _INSERTAR_DECISION,
                {
                    "version": versiones[decision.version_definicion - 1],
                    "resultado": decision.resultado.value,
                    "canal": decision.canal.value,
                    "usuario": self._id("usuario", decision.usuario_id),
                    "fecha": decision.fecha,
                    "observaciones": decision.observaciones,
                    "posicion": posicion,
                },
            )

    def _ajustes(
        self, detalle: ReparacionDetail, anterior: ReparacionDetail | None
    ) -> None:
        previos = anterior.ajustes_garantia if anterior else []
        nuevos = self._exigir_prefijo(
            f"los ajustes de garantia de {detalle.id}",
            previos,
            detalle.ajustes_garantia,
        )
        for posicion, ajuste in enumerate(nuevos, len(previos) + 1):
            self._ej.ejecutar(
                _INSERTAR_AJUSTE,
                {
                    "detalle": self._detalles[detalle.id],
                    "dias_anteriores": ajuste.dias_anteriores,
                    "dias_nuevos": ajuste.dias_nuevos,
                    "motivo": ajuste.motivo,
                    "usuario": self._id("usuario", ajuste.usuario_id),
                    "fecha": ajuste.fecha,
                    "posicion": posicion,
                },
            )

    def _todos_los_controles(self) -> None:
        previos = (
            {d.id: d.controles for d in self._previa.orden.reparaciones_detail}
            if self._previa
            else {}
        )
        for detalle in self._orden.reparaciones_detail:
            anteriores = previos.get(detalle.id, [])
            nuevos = self._exigir_prefijo(
                f"los controles de {detalle.id}", anteriores, detalle.controles
            )
            for posicion, control in enumerate(nuevos, len(anteriores) + 1):
                self._ej.ejecutar(
                    _INSERTAR_CONTROL,
                    {
                        "detalle": self._detalles[detalle.id],
                        "ejecucion": self._ejecucion_de(control.ejecucion_id),
                        "resultado": control.resultado.value,
                        "usuario": self._id("usuario", control.usuario_id),
                        "fecha": control.fecha,
                        "observaciones": control.observaciones,
                        "posicion": posicion,
                    },
                )

    # --- Tomas y ejecuciones -------------------------------------------------

    def _todas_las_tomas(self, orden_id: UUID) -> None:
        previas = (
            {t.id: t for t in self._previa.orden.tomas} if self._previa else {}
        )
        self._exigir_prefijo(
            "las tomas", list(previas), [t.id for t in self._orden.tomas]
        )
        for posicion, toma in enumerate(self._orden.tomas, 1):
            anterior = previas.get(toma.id)
            valores = {
                "estado": toma.estado.value,
                "fin": toma.fin,
                "liberada_por": self._id("usuario", toma.liberada_por),
                "motivo": toma.motivo_liberacion,
            }
            if anterior is None:
                self._tomas[toma.id] = self._ej.fila(
                    _INSERTAR_TOMA,
                    {
                        **valores,
                        "codigo": toma.id,
                        "orden": orden_id,
                        "usuario": self._id("usuario", toma.usuario_id),
                        "mesa": self._id("mesa_trabajo", toma.estacion_id),
                        "inicio": toma.inicio,
                        "posicion": posicion,
                    },
                ).id
            elif toma != anterior:
                if (toma.usuario_id, toma.estacion_id, toma.inicio) != (
                    anterior.usuario_id,
                    anterior.estacion_id,
                    anterior.inicio,
                ):
                    self._inmutable(f"el inicio de la toma {toma.id}")
                self._ej.ejecutar(
                    _ACTUALIZAR_TOMA, {**valores, "id": self._tomas[toma.id]}
                )

    def _todas_las_ejecuciones(self, orden_id: UUID) -> None:
        previas = (
            {e.id: e for e in self._previa.orden.ejecuciones}
            if self._previa
            else {}
        )
        self._exigir_prefijo(
            "las ejecuciones",
            list(previas),
            [e.id for e in self._orden.ejecuciones],
        )
        for posicion, ejecucion in enumerate(self._orden.ejecuciones, 1):
            anterior = previas.get(ejecucion.id)
            valores = {
                "estado": ejecucion.estado.value,
                "fin": ejecucion.fin,
                "observaciones": ejecucion.observaciones,
                "motivo_interrupcion": ejecucion.motivo_interrupcion,
                "motivo_redefinicion": ejecucion.motivo_redefinicion,
            }
            if anterior is None:
                detalle = ejecucion.reparacion_detail_id
                if detalle not in self._detalles:
                    raise PersistenciaError(
                        f"La Ejecucion {ejecucion.id} es de un Detalle que la "
                        f"Orden {self._orden.id} no tiene: {detalle}."
                    )
                self._ejecuciones[ejecucion.id] = self._ej.fila(
                    _INSERTAR_EJECUCION,
                    {
                        **valores,
                        "codigo": ejecucion.id,
                        "orden": orden_id,
                        "detalle": self._detalles[detalle],
                        "version": self._versiones[detalle][-1],
                        "toma": self._toma_de(ejecucion.toma_orden_id),
                        "usuario": self._id("usuario", ejecucion.usuario_id),
                        "inicio": ejecucion.inicio,
                        "posicion": posicion,
                    },
                ).id
            else:
                fijos = ("reparacion_detail_id", "toma_orden_id", "usuario_id")
                if any(
                    getattr(ejecucion, campo) != getattr(anterior, campo)
                    for campo in (*fijos, "inicio")
                ):
                    self._inmutable(
                        f"el inicio de la Ejecucion {ejecucion.id}"
                    )
                cambio = valores != {
                    "estado": anterior.estado.value,
                    "fin": anterior.fin,
                    "observaciones": anterior.observaciones,
                    "motivo_interrupcion": anterior.motivo_interrupcion,
                    "motivo_redefinicion": anterior.motivo_redefinicion,
                }
                if cambio:
                    if anterior.estado.value != "EN_PROGRESO":
                        self._inmutable(
                            f"la Ejecucion terminada {ejecucion.id}"
                        )
                    self._ej.ejecutar(
                        _ACTUALIZAR_EJECUCION,
                        {**valores, "id": self._ejecuciones[ejecucion.id]},
                    )
            previos = anterior.insumos_utilizados if anterior else []
            nuevos = self._exigir_prefijo(
                f"los insumos utilizados de {ejecucion.id}",
                previos,
                ejecucion.insumos_utilizados,
            )
            for orden_insumo, insumo in enumerate(nuevos, len(previos) + 1):
                self._ej.ejecutar(
                    _INSERTAR_INSUMO_UTILIZADO,
                    {
                        "ejecucion": self._ejecuciones[ejecucion.id],
                        "insumo": self._id("insumo", insumo.insumo_id),
                        "cantidad": _escala(
                            insumo.cantidad, _TRES_DECIMALES, "cantidad"
                        ),
                        "posicion": orden_insumo,
                    },
                )

    def _toma_de(self, codigo: str) -> UUID:
        if codigo not in self._tomas:
            raise PersistenciaError(
                f"La Orden {self._orden.id} referencia la toma {codigo}, que "
                "no tiene."
            )
        return self._tomas[codigo]

    def _ejecucion_de(self, codigo: str | None) -> UUID | None:
        if codigo is None:
            return None
        if codigo not in self._ejecuciones:
            raise PersistenciaError(
                f"La Orden {self._orden.id} referencia la Ejecucion {codigo}, "
                "que no tiene."
            )
        return self._ejecuciones[codigo]

    # --- Historial -----------------------------------------------------------

    def _historial(self, orden_id: UUID) -> None:
        previos = self._previa.orden.historial if self._previa else []
        nuevos = self._exigir_prefijo(
            "el historial", previos, self._orden.historial
        )
        if not nuevos:
            return
        equivalencias = self._equivalencias({p.referencia_id for p in nuevos})
        accion = self._accion(orden_id)
        for paso in nuevos:
            tipo_referencia = paso.tipo_referencia.value
            tipo_evento = equivalencias.get(
                (tipo_referencia, paso.referencia_id, paso.accion)
            ) or equivalencias.get((tipo_referencia, paso.referencia_id, None))
            if tipo_evento is None:
                raise PersistenciaError(
                    f"El paso {paso.referencia_id} ({paso.accion}) del "
                    f"historial de {self._orden.id} no tiene equivalencia "
                    "en rma.equivalencia_historial."
                )
            detalle = paso.reparacion_detail_id
            if detalle is not None and detalle not in self._detalles:
                raise PersistenciaError(
                    f"El historial de {self._orden.id} referencia el Detalle "
                    f"{detalle}, que la Orden no tiene."
                )
            self._ej.ejecutar(
                _INSERTAR_EVENTO,
                {
                    "orden": orden_id,
                    "tipo_evento": tipo_evento,
                    "accion": accion,
                    "fecha": paso.fecha,
                    "responsable": "USUARIO" if paso.usuario_id else "SISTEMA",
                    "usuario": self._id("usuario", paso.usuario_id),
                    "detalle": self._detalles.get(detalle)
                    if detalle
                    else None,
                    "ejecucion": self._ejecucion_de(paso.ejecucion_id),
                    "pago": self._pago_de(paso.pago_id),
                    "observacion": paso.observacion,
                    "tipo_referencia": tipo_referencia,
                    "referencia_id": paso.referencia_id,
                    "accion_historial": paso.accion,
                },
            )

    def _equivalencias(
        self, referencias: set[str]
    ) -> dict[tuple[str, str, str | None], UUID]:
        filas = self._ej.filas(
            _EQUIVALENCIAS, {"referencias": sorted(referencias)}
        )
        return {
            (f.tipo_referencia, f.referencia_id, f.accion): f.tipo_evento_id
            for f in filas
        }


def _fila_recepcion(
    recepcion: RecepcionEquipo, checkin_ingreso: bool | None
) -> dict[str, Any]:
    """Las columnas de ``rma.recepcion``, con los usuarios por codigo."""
    confirmacion = recepcion.confirmacion
    no_recibido = recepcion.no_recibido
    datos = recepcion.datos
    return {
        "registro": recepcion.registro.value,
        "estado_fisico": datos.estado_fisico,
        "accesorios": list(datos.accesorios),
        "observaciones": datos.observaciones,
        "notas_internas": datos.notas_internas,
        "checkin": checkin_ingreso,
        "registrado_por": recepcion.registrado_por,
        "registrado_en": recepcion.registrado_en,
        "confirmada_por": confirmacion.usuario_id if confirmacion else None,
        "confirmada_en": confirmacion.fecha if confirmacion else None,
        "confirmacion_observaciones": (
            confirmacion.observaciones if confirmacion else None
        ),
        "no_recibido_por": no_recibido.usuario_id if no_recibido else None,
        "no_recibido_en": no_recibido.fecha if no_recibido else None,
        "no_recibido_motivo": no_recibido.motivo if no_recibido else None,
    }


def _dominio_json(modelo: BaseModel) -> dict[str, Any]:
    """Como en JSON: los importes salen como texto, sin pasar por float."""
    return modelo.model_dump(mode="json", exclude_computed_fields=True)


def _json(valor: dict[str, Any]) -> str:
    return json.dumps(valor, ensure_ascii=False)


def _definicion(detalle: ReparacionDetail) -> tuple:
    return (
        detalle.tipo_reparacion_id,
        detalle.precio,
        detalle.puntaje,
        detalle.descripcion,
    )


def _escala(valor: Decimal, escala: Decimal, que: str) -> Decimal:
    """El valor tal cual, si la columna lo guarda sin redondear."""
    if valor.quantize(escala) != valor:
        raise PersistenciaError(
            f"El {que} {valor} tiene mas decimales de los que guarda la base."
        )
    return valor
