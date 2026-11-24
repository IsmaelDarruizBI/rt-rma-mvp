"""``ConfiguracionRepository`` sobre PostgreSQL (DC23, DC23AUD).

El catalogo y su auditoria (``rma.cambio_configuracion``) se escriben en la
transaccion del comando: un cambio sin auditoria no queda.
"""

from collections.abc import Collection, Sequence
from datetime import timezone

from app.domain.models import (
    CambioConfiguracion,
    EntidadConfiguracion,
    ImportacionPrecios,
    ModeloEquipo,
    PrecioTipoModelo,
    RolUsuario,
    TipoReparacion,
    TipoReparacionInsumos,
    TipoReparacionRequisito,
)
from app.repositories.exceptions import (
    CodigoExistenteError,
    EntidadPersistidaNoEncontradaError,
    PersistenciaError,
)

from .codigos import reservar_codigo
from .consultas import ESCRITURA, LECTURA, consulta
from .transaccion import UnidadDeTrabajoPostgres

_INSERTAR_TIPO = consulta(
    "configuracion.insertar_tipo",
    """
    INSERT INTO rma.tipo_reparacion
        (codigo, nombre, precio, puntaje, garantia_dias, activo,
         garantia_con_checkin, garantia_sin_checkin, politica_garantia_rma,
         precio_por_modelo)
    VALUES (%(codigo)s, %(nombre)s, %(precio)s, %(puntaje)s,
            %(garantia_dias)s, %(activo)s, %(con_checkin)s,
            %(sin_checkin)s, %(politica_rma)s, %(precio_por_modelo)s)
    ON CONFLICT DO NOTHING
    RETURNING id
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_TIPO = consulta(
    "configuracion.actualizar_tipo",
    """
    UPDATE rma.tipo_reparacion
       SET nombre = %(nombre)s, precio = %(precio)s, puntaje = %(puntaje)s,
           garantia_dias = %(garantia_dias)s, activo = %(activo)s,
           garantia_con_checkin = %(con_checkin)s,
           garantia_sin_checkin = %(sin_checkin)s,
           politica_garantia_rma = %(politica_rma)s,
           precio_por_modelo = %(precio_por_modelo)s
     WHERE codigo = %(codigo)s
    """,
    modo=ESCRITURA,
)
# DEC-AJ-12 (D-12.5): alta y edicion de modelos; el codigo no cambia.
_INSERTAR_MODELO = consulta(
    "configuracion.insertar_modelo",
    """
    INSERT INTO rma.modelo_equipo
        (codigo, marca, modelo, variante, numeros_modelo, activo)
    VALUES (%(codigo)s, %(marca)s, %(modelo)s, %(variante)s,
            %(numeros)s, %(activo)s)
    ON CONFLICT DO NOTHING
    RETURNING id
    """,
    modo=ESCRITURA,
)
_ACTUALIZAR_MODELO = consulta(
    "configuracion.actualizar_modelo",
    """
    UPDATE rma.modelo_equipo
       SET marca = %(marca)s, modelo = %(modelo)s, variante = %(variante)s,
           numeros_modelo = %(numeros)s, activo = %(activo)s
     WHERE codigo = %(codigo)s
    """,
    modo=ESCRITURA,
)
# DEC-AJ-12 (D-12.1): precios por modelo en bloque (una o cientos de
# combinaciones en la misma sentencia y la misma transaccion). Fijar crea o
# reactiva la fila; retirar la deja inactiva, nunca la borra.
_FIJAR_PRECIOS_MODELO = consulta(
    "configuracion.fijar_precios_modelo",
    """
    INSERT INTO rma.precio_tipo_modelo
        (tipo_reparacion_id, modelo_equipo_id, precio, activo)
    SELECT t.id, m.id, x.precio, true
      FROM unnest(%(tipos)s::text[], %(modelos)s::text[],
                  %(precios)s::numeric[]) AS x (tipo, modelo, precio)
      JOIN rma.tipo_reparacion t ON t.codigo = x.tipo
      JOIN rma.modelo_equipo m ON m.codigo = x.modelo
    ON CONFLICT (tipo_reparacion_id, modelo_equipo_id) DO UPDATE
       SET precio = EXCLUDED.precio, activo = true
    """,
    modo=ESCRITURA,
)
_RETIRAR_PRECIOS_MODELO = consulta(
    "configuracion.retirar_precios_modelo",
    """
    UPDATE rma.precio_tipo_modelo p
       SET activo = false
      FROM unnest(%(tipos)s::text[], %(modelos)s::text[]) AS x (tipo, modelo)
      JOIN rma.tipo_reparacion t ON t.codigo = x.tipo
      JOIN rma.modelo_equipo m ON m.codigo = x.modelo
     WHERE p.tipo_reparacion_id = t.id AND p.modelo_equipo_id = m.id
       AND p.activo
    """,
    modo=ESCRITURA,
)
_MESA = consulta(
    "configuracion.mesa",
    "SELECT id FROM rma.mesa_trabajo WHERE codigo = %(codigo)s FOR UPDATE",
    modo=ESCRITURA,
)
# DEC-AJ-14: insumos necesarios de un Tipo. Los previstos concretos son un
# conjunto (se quitan los que no siguen); los requisitos no se borran.
_TIPO_ID = consulta(
    "configuracion.tipo_id",
    "SELECT id FROM rma.tipo_reparacion WHERE codigo = %(tipo)s FOR UPDATE",
    modo=ESCRITURA,
)
_QUITAR_PREVISTOS = consulta(
    "configuracion.quitar_previstos",
    """
    DELETE FROM rma.tipo_reparacion_insumo ti
     USING rma.insumo i
     WHERE ti.tipo_reparacion_id = %(tipo)s
       AND i.id = ti.insumo_id
       AND NOT (i.clave = ANY(%(insumos)s))
    """,
    modo=ESCRITURA,
)
_FIJAR_PREVISTOS = consulta(
    "configuracion.fijar_previstos",
    """
    INSERT INTO rma.tipo_reparacion_insumo
        (tipo_reparacion_id, insumo_id, cantidad)
    SELECT %(tipo)s, i.id, x.cantidad
      FROM unnest(%(insumos)s::text[], %(cantidades)s::numeric[])
           AS x (insumo, cantidad)
      JOIN rma.insumo i ON i.clave = x.insumo
    ON CONFLICT (tipo_reparacion_id, insumo_id) DO UPDATE
       SET cantidad = EXCLUDED.cantidad
     WHERE rma.tipo_reparacion_insumo.cantidad IS DISTINCT FROM
           EXCLUDED.cantidad
    """,
    modo=ESCRITURA,
)
_CONTAR_PREVISTOS = consulta(
    "configuracion.contar_previstos",
    "SELECT count(*) AS cantidad FROM rma.tipo_reparacion_insumo "
    "WHERE tipo_reparacion_id = %(tipo)s",
    modo=ESCRITURA,
)
_FIJAR_REQUISITOS = consulta(
    "configuracion.fijar_requisitos",
    """
    INSERT INTO rma.tipo_reparacion_requisito
        (id, tipo_reparacion_id, categoria_id, cantidad, posicion, activo)
    SELECT x.id, %(tipo)s, c.id, x.cantidad, x.posicion, x.activo
      FROM unnest(%(ids)s::uuid[], %(categorias)s::text[],
                  %(cantidades)s::numeric[], %(posiciones)s::int[],
                  %(activos)s::boolean[])
           AS x (id, categoria, cantidad, posicion, activo)
      JOIN rma.categoria_insumo c ON c.codigo = x.categoria
    ON CONFLICT (id) DO UPDATE
       SET cantidad = EXCLUDED.cantidad, posicion = EXCLUDED.posicion,
           activo = EXCLUDED.activo
     WHERE rma.tipo_reparacion_requisito.tipo_reparacion_id
           = EXCLUDED.tipo_reparacion_id
       AND rma.tipo_reparacion_requisito.categoria_id = EXCLUDED.categoria_id
    RETURNING id
    """,
    modo=ESCRITURA,
)
_QUITAR_TIPOS_DE_MESA = consulta(
    "configuracion.quitar_tipos_de_mesa",
    """
    DELETE FROM rma.mesa_tipo_reparacion mt
     USING rma.tipo_reparacion t
     WHERE mt.mesa_trabajo_id = %(mesa)s
       AND t.id = mt.tipo_reparacion_id
       AND NOT (t.codigo = ANY(%(tipos)s))
    """,
    modo=ESCRITURA,
)
_AGREGAR_TIPOS_A_MESA = consulta(
    "configuracion.agregar_tipos_a_mesa",
    """
    INSERT INTO rma.mesa_tipo_reparacion (mesa_trabajo_id, tipo_reparacion_id)
    SELECT %(mesa)s, t.id FROM rma.tipo_reparacion t
     WHERE t.codigo = ANY(%(tipos)s)
    ON CONFLICT DO NOTHING
    """,
    modo=ESCRITURA,
)
_INSERTAR_CAMBIO = consulta(
    "configuracion.insertar_cambio",
    """
    INSERT INTO rma.cambio_configuracion
        (entidad, clave, campo, valor_anterior, valor_nuevo, usuario_id,
         registrado_en, importacion_id)
    SELECT %(entidad)s, %(clave)s, %(campo)s, %(anterior)s, %(nuevo)s, u.id,
           %(fecha)s, %(importacion)s::uuid
      FROM rma.usuario u WHERE u.codigo = %(usuario)s
    """,
    modo=ESCRITURA,
)
# DEC-AJ-13: la importacion masiva de precios, antes que sus cambios.
_REGISTRAR_IMPORTACION = consulta(
    "configuracion.registrar_importacion_precios",
    """
    INSERT INTO rma.importacion_precio
        (id, usuario_id, registrado_en, formato, nombre_archivo,
         precios_nuevos, precios_actualizados, precios_sin_cambio)
    SELECT %(id)s::uuid, u.id, %(fecha)s, %(formato)s, %(nombre)s,
           %(nuevos)s, %(actualizados)s, %(sin_cambio)s
      FROM rma.usuario u WHERE u.codigo = %(usuario)s
    """,
    modo=ESCRITURA,
)
_QUITAR_ROLES = consulta(
    "configuracion.quitar_roles",
    """
    DELETE FROM rma.usuario_rol ur
     USING rma.usuario u, rma.rol r
     WHERE ur.usuario_id = u.id AND ur.rol_id = r.id
       AND u.codigo = %(usuario)s AND NOT (r.codigo = ANY(%(roles)s))
    """,
    modo=ESCRITURA,
)
_AGREGAR_ROLES = consulta(
    "configuracion.agregar_roles",
    """
    INSERT INTO rma.usuario_rol (usuario_id, rol_id, otorgado_en, otorgado_por)
    SELECT u.id, r.id, %(fecha)s, a.id
      FROM rma.usuario u
      JOIN rma.rol r ON r.codigo = ANY(%(roles)s)
      LEFT JOIN rma.usuario a ON a.codigo = %(actor)s
     WHERE u.codigo = %(usuario)s
    ON CONFLICT (usuario_id, rol_id) DO NOTHING
    """,
    modo=ESCRITURA,
)
_EXISTE_USUARIO = consulta(
    "configuracion.existe_usuario",
    "SELECT id FROM rma.usuario WHERE codigo = %(usuario)s",
    modo=LECTURA,
)
_GUARDAR_PERMISO = consulta(
    "configuracion.guardar_permiso",
    """
    INSERT INTO rma.permiso (codigo, roles, modificado_en)
    VALUES (%(codigo)s, %(roles)s, %(fecha)s)
    ON CONFLICT (codigo) DO UPDATE
       SET roles = EXCLUDED.roles, modificado_en = EXCLUDED.modificado_en
    """,
    modo=ESCRITURA,
)
_PERMISOS = consulta(
    "configuracion.permisos",
    "SELECT codigo, roles FROM rma.permiso ORDER BY codigo",
    modo=LECTURA,
)
_CAMBIOS = consulta(
    "configuracion.cambios",
    """
    SELECT c.entidad, c.clave, c.campo, c.valor_anterior, c.valor_nuevo,
           u.codigo AS usuario, c.registrado_en,
           c.importacion_id::text AS importacion_id
      FROM rma.cambio_configuracion c
      JOIN rma.usuario u ON u.id = c.usuario_id
     WHERE (%(entidad)s::text IS NULL OR c.entidad = %(entidad)s)
       AND (%(clave)s::text IS NULL OR c.clave = %(clave)s)
     ORDER BY c.secuencia
    """,
    modo=LECTURA,
)


class PostgresConfiguracionRepository:
    def __init__(self, unidad: UnidadDeTrabajoPostgres) -> None:
        self._unidad = unidad

    def reservar_codigo(self, prefijo: str) -> str:
        """CFG-01: el codigo siguiente libre del prefijo, generado por la
        base dentro de la transaccion del alta."""
        self._exigir_transaccion()
        return reservar_codigo(self._unidad, prefijo)

    def guardar_tipo_reparacion(
        self,
        tipo: TipoReparacion,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None:
        self._exigir_transaccion()
        ejecutor = self._unidad.ejecutor()
        parametros = {
            "codigo": tipo.id,
            "nombre": tipo.nombre,
            "precio": tipo.precio,
            "puntaje": tipo.puntaje,
            "garantia_dias": tipo.garantia_dias,
            "con_checkin": tipo.garantia_con_checkin,
            "sin_checkin": tipo.garantia_sin_checkin,
            "politica_rma": (
                tipo.politica_garantia_rma.value
                if tipo.politica_garantia_rma
                else None
            ),
            "activo": tipo.activo,
            "precio_por_modelo": tipo.precio_por_modelo,
        }
        if nuevo:
            if ejecutor.fila(_INSERTAR_TIPO, parametros) is None:
                raise CodigoExistenteError(
                    f"Ya existe un Tipo de Reparacion {tipo.id}."
                )
        elif ejecutor.ejecutar(_ACTUALIZAR_TIPO, parametros) != 1:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe el Tipo de Reparacion {tipo.id}"
            )
        self._auditar(ejecutor, cambios)

    def guardar_modelo_equipo(
        self,
        modelo: ModeloEquipo,
        *,
        nuevo: bool,
        cambios: Sequence[CambioConfiguracion],
    ) -> None:
        """Alta o edicion de un modelo de equipo, con su auditoria. La
        unicidad (marca, modelo, variante) la garantiza la base."""
        self._exigir_transaccion()
        ejecutor = self._unidad.ejecutor()
        parametros = {
            "codigo": modelo.id,
            "marca": modelo.marca,
            "modelo": modelo.modelo,
            "variante": modelo.variante,
            "numeros": list(modelo.numeros_modelo),
            "activo": modelo.activo,
        }
        if nuevo:
            if ejecutor.fila(_INSERTAR_MODELO, parametros) is None:
                raise CodigoExistenteError(
                    f"Ya existe el modelo {modelo.id} o uno con la misma "
                    "marca, modelo y variante."
                )
        elif ejecutor.ejecutar(_ACTUALIZAR_MODELO, parametros) != 1:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe el modelo de equipo {modelo.id}"
            )
        self._auditar(ejecutor, cambios)

    def guardar_precios_modelo(
        self,
        precios: Sequence[PrecioTipoModelo],
        cambios: Sequence[CambioConfiguracion],
    ) -> None:
        """Fija o retira (``precio`` None) los precios por modelo, todos en
        la transaccion en curso y con su auditoria: todo o nada. Cada
        combinacion tiene que existir (Tipo y modelo)."""
        self._exigir_transaccion()
        ejecutor = self._unidad.ejecutor()
        fijar = [p for p in precios if p.precio is not None]
        retirar = [p for p in precios if p.precio is None]
        if fijar:
            escritas = ejecutor.ejecutar(
                _FIJAR_PRECIOS_MODELO,
                {
                    "tipos": [p.tipo_reparacion_id for p in fijar],
                    "modelos": [p.modelo_equipo_id for p in fijar],
                    "precios": [p.precio for p in fijar],
                },
            )
            if escritas != len(fijar):
                raise EntidadPersistidaNoEncontradaError(
                    "Algun Tipo de Reparacion o modelo de equipo no existe."
                )
        if retirar:
            ejecutor.ejecutar(
                _RETIRAR_PRECIOS_MODELO,
                {
                    "tipos": [p.tipo_reparacion_id for p in retirar],
                    "modelos": [p.modelo_equipo_id for p in retirar],
                },
            )
        self._auditar(ejecutor, cambios)

    def registrar_importacion_precios(
        self, importacion: ImportacionPrecios
    ) -> None:
        """DEC-AJ-13: la importacion, en la transaccion de sus cambios."""
        self._exigir_transaccion()
        insertadas = self._unidad.ejecutor().ejecutar(
            _REGISTRAR_IMPORTACION,
            {
                "id": importacion.id,
                "usuario": importacion.usuario_id,
                "fecha": importacion.fecha,
                "formato": importacion.formato.value,
                "nombre": importacion.nombre_archivo,
                "nuevos": importacion.nuevos,
                "actualizados": importacion.actualizados,
                "sin_cambio": importacion.sin_cambio,
            },
        )
        if insertadas != 1:
            raise PersistenciaError(
                f"El usuario {importacion.usuario_id} no existe en la base."
            )

    def guardar_insumos_necesarios(
        self,
        tipo_reparacion_id: str,
        previstos: Sequence[TipoReparacionInsumos],
        requisitos: Sequence[TipoReparacionRequisito],
        cambios: Sequence[CambioConfiguracion],
    ) -> None:
        self._exigir_transaccion()
        ejecutor = self._unidad.ejecutor()
        tipo = ejecutor.fila(_TIPO_ID, {"tipo": tipo_reparacion_id})
        if tipo is None:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe el Tipo de Reparacion {tipo_reparacion_id}"
            )
        claves = [p.insumo_id for p in previstos]
        ejecutor.ejecutar(
            _QUITAR_PREVISTOS, {"tipo": tipo.id, "insumos": claves}
        )
        if previstos:
            ejecutor.ejecutar(
                _FIJAR_PREVISTOS,
                {
                    "tipo": tipo.id,
                    "insumos": claves,
                    "cantidades": [p.cantidad for p in previstos],
                },
            )
        quedaron = ejecutor.fila(_CONTAR_PREVISTOS, {"tipo": tipo.id})
        if quedaron.cantidad != len(previstos):
            raise EntidadPersistidaNoEncontradaError(
                "Algun insumo previsto no existe en la base."
            )
        if requisitos:
            escritos = ejecutor.filas(
                _FIJAR_REQUISITOS,
                {
                    "tipo": tipo.id,
                    "ids": [r.id for r in requisitos],
                    "categorias": [r.categoria_id for r in requisitos],
                    "cantidades": [r.cantidad for r in requisitos],
                    "posiciones": [r.posicion for r in requisitos],
                    "activos": [r.activo for r in requisitos],
                },
            )
            if len(escritos) != len(requisitos):
                raise PersistenciaError(
                    "Algun requisito no se pudo guardar: la categoria no "
                    "existe o el requisito es de otro Tipo o categoria."
                )
        self._auditar(ejecutor, cambios)

    def guardar_tipos_de_mesa(
        self,
        estacion_id: str,
        tipo_ids: Collection[str],
        cambio: CambioConfiguracion,
    ) -> None:
        self._exigir_transaccion()
        ejecutor = self._unidad.ejecutor()
        mesa = ejecutor.fila(_MESA, {"codigo": estacion_id})
        if mesa is None:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe la Mesa de trabajo {estacion_id}"
            )
        tipos = sorted(tipo_ids)
        ejecutor.ejecutar(
            _QUITAR_TIPOS_DE_MESA, {"mesa": mesa.id, "tipos": tipos}
        )
        ejecutor.ejecutar(
            _AGREGAR_TIPOS_A_MESA, {"mesa": mesa.id, "tipos": tipos}
        )
        self._auditar(ejecutor, [cambio])

    def guardar_roles_de_usuario(
        self,
        usuario_id: str,
        roles: Sequence[RolUsuario],
        cambio: CambioConfiguracion,
    ) -> None:
        self._exigir_transaccion()
        ejecutor = self._unidad.ejecutor()
        if ejecutor.fila(_EXISTE_USUARIO, {"usuario": usuario_id}) is None:
            raise EntidadPersistidaNoEncontradaError(
                f"No existe el usuario {usuario_id}"
            )
        codigos = [rol.value for rol in roles]
        parametros = {
            "usuario": usuario_id,
            "roles": codigos,
            "fecha": cambio.fecha,
            "actor": cambio.usuario_id,
        }
        ejecutor.ejecutar(_QUITAR_ROLES, parametros)
        ejecutor.ejecutar(_AGREGAR_ROLES, parametros)
        self._auditar(ejecutor, [cambio])

    def guardar_permiso(
        self,
        codigo: str,
        roles: Sequence[RolUsuario],
        cambio: CambioConfiguracion,
    ) -> None:
        self._exigir_transaccion()
        ejecutor = self._unidad.ejecutor()
        ejecutor.ejecutar(
            _GUARDAR_PERMISO,
            {
                "codigo": codigo,
                "roles": [rol.value for rol in roles],
                "fecha": cambio.fecha,
            },
        )
        self._auditar(ejecutor, [cambio])

    def leer_permisos(self) -> dict[str, tuple[RolUsuario, ...]]:
        with self._unidad.lectura() as lector:
            filas = lector.filas(_PERMISOS)
        return {
            f.codigo: tuple(RolUsuario(rol) for rol in f.roles) for f in filas
        }

    def listar_cambios(
        self,
        *,
        entidad: EntidadConfiguracion | None = None,
        clave: str | None = None,
    ) -> list[CambioConfiguracion]:
        with self._unidad.lectura() as lector:
            filas = lector.filas(
                _CAMBIOS,
                {
                    "entidad": entidad.value if entidad else None,
                    "clave": clave,
                },
            )
        return [
            CambioConfiguracion(
                entidad=f.entidad,
                clave=f.clave,
                campo=f.campo,
                valor_anterior=f.valor_anterior,
                valor_nuevo=f.valor_nuevo,
                usuario_id=f.usuario,
                fecha=f.registrado_en.astimezone(timezone.utc),
                importacion_id=f.importacion_id,
            )
            for f in filas
        ]

    def _auditar(
        self, ejecutor, cambios: Sequence[CambioConfiguracion]
    ) -> None:
        def parametros(cambio: CambioConfiguracion) -> dict:
            return {
                "entidad": cambio.entidad.value,
                "clave": cambio.clave,
                "campo": cambio.campo,
                "anterior": cambio.valor_anterior,
                "nuevo": cambio.valor_nuevo,
                "usuario": cambio.usuario_id,
                "fecha": cambio.fecha,
                "importacion": cambio.importacion_id,
            }

        if len(cambios) <= 1:
            for cambio in cambios:
                if (
                    ejecutor.ejecutar(_INSERTAR_CAMBIO, parametros(cambio))
                    != 1
                ):
                    raise PersistenciaError(
                        f"El usuario {cambio.usuario_id} no existe en la base."
                    )
            return
        # Muchos cambios (una importacion de cientos de precios, DEC-AJ-13):
        # en lote, despues de comprobar que existe cada usuario.
        for usuario in {cambio.usuario_id for cambio in cambios}:
            if ejecutor.fila(_EXISTE_USUARIO, {"usuario": usuario}) is None:
                raise PersistenciaError(
                    f"El usuario {usuario} no existe en la base."
                )
        ejecutor.ejecutar_lote(
            _INSERTAR_CAMBIO, [parametros(c) for c in cambios]
        )

    def _exigir_transaccion(self) -> None:
        if not self._unidad.en_curso():
            raise PersistenciaError(
                "Administrar un catalogo exige una transaccion en curso."
            )
