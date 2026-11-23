-- Ajustes funcionales, bloque 4: comprobantes (23/11/2026, DEC-AJ-09, BF-19).
--
-- Aditiva e idempotente: se puede ejecutar otra vez. No agrega tablas: los
-- scripts de reinicio del UAT no cambian (empresa y texto_legal ya son
-- maestras).
--
-- 1. rma.empresa: dos columnas opcionales, el horario de atención y un pie
--    de comprobante libre. Administración edita los datos de la empresa
--    (permiso no configurable CONFIGURACION_ADMINISTRAR) y cada cambio queda
--    en cambio_configuracion (entidad EMPRESA). Los documentos ya emitidos
--    conservan su copia.
-- 2. cambio_configuracion.entidad admite EMPRESA y TEXTO_LEGAL (una versión
--    nueva de los Términos y Condiciones publicada desde Configuración).
-- 3. rma.texto_legal: versión 2 de los Términos y Condiciones del
--    comprobante de entrega y garantía. Es el texto vigente después del
--    bloque 2 (sin el apartado que anulaba la garantía si retiraba otra
--    persona ni la exigencia de que retire quien dejó el equipo, P-05) con
--    P-04 aplicado: el apartado 1 ya no fija 180 días, remite a la garantía
--    indicada para cada trabajo en el comprobante. La versión 1 no cambia
--    (texto_legal es inmutable). Misma copia que
--    app/backend/app/datos/terminos_condiciones_v2.json (lo verifica
--    tests/test_comprobantes.py).

alter table rma.empresa
  add column if not exists horario text,
  add column if not exists pie_comprobante text;

comment on column rma.empresa.horario is
  'Horario de atención del local, tal como sale en los comprobantes (DEC-AJ-09); vacío si no se informó.';
comment on column rma.empresa.pie_comprobante is
  'Texto libre que se imprime al pie de los comprobantes (DEC-AJ-09); vacío si no se informó.';
comment on table rma.empresa is
  'Datos de Rosario Tecno que salen en los comprobantes. Tiene una sola fila; la edita Administración con auditoría (cambio_configuracion, entidad EMPRESA). Cambiarla no altera los documentos ya emitidos, que guardan su copia.';

alter table rma.cambio_configuracion drop constraint if exists cambio_configuracion_entidad_check;
alter table rma.cambio_configuracion add constraint cambio_configuracion_entidad_check
  check (entidad in (
    'TIPO_REPARACION', 'MESA_TRABAJO', 'USUARIO', 'PERMISO', 'INSUMO',
    'MOTIVO', 'PLANTILLA', 'PARAMETRO', 'CHECKLIST', 'PROVEEDOR', 'MEDIO_PAGO',
    'EMPRESA', 'TEXTO_LEGAL'
  ));

comment on column rma.cambio_configuracion.entidad is
  'Qué se cambió: un catálogo (TIPO_REPARACION, MESA_TRABAJO, INSUMO, MOTIVO, PLANTILLA, CHECKLIST, PROVEEDOR), la asignación de roles (USUARIO), un permiso (PERMISO), un parámetro (PARAMETRO), el recargo de un medio de pago (MEDIO_PAGO), los datos de la empresa (EMPRESA) o una versión nueva de un texto legal (TEXTO_LEGAL).';

insert into rma.texto_legal (tipo, version, titulo, contenido, vigente_desde) values (
  'TERMINOS_CONDICIONES_ENTREGA', 2, 'TÉRMINOS Y CONDICIONES',
  '{"encabezado":{"marca":"ROSARIO | TECNO","titulo":"TÉRMINOS Y CONDICIONES","subtitulo":"SERVICIO TÉCNICO"},"apartados":[{"numero":1,"lineas":["La reparación cuenta con la garantía indicada para cada trabajo en este comprobante, con su plazo en días y su fecha de vencimiento, válida exclusivamente sobre el trabajo realizado y/o el repuesto colocado, contada a partir de la fecha de entrega del equipo."],"destacado":false},{"numero":2,"lineas":["La garantía NO cubre, sin excepción, daños ocasionados por golpes, caídas, presión, humedad, ingreso de líquidos, sulfatación, corrosión, polvo, calor, frío, sobrecargas eléctricas, uso indebido, uso de cargadores no originales o defectuosos, cables en mal estado, tomas eléctricas inestables, ni cualquier tipo de manipulación, apertura o reparación realizada por terceros ajenos a este servicio técnico."],"destacado":false},{"numero":3,"lineas":["En casos de cambios de tapa y cambios de vidrio de cámara la garantía cubre el repuesto si viene despegado sin ningún tipo de daño o fractura, el repuesto debe estar entero y en óptimas condiciones."],"destacado":false},{"numero":4,"lineas":["Asimismo, no se encuentran cubiertos por la garantía los fallos derivados de:","Uso incorrecto del cargador.","Ciclos de carga interrumpidos.","Ciclos de carga excesivos (múltiples cargas diarias).","Consumos elevados y continuos de aplicaciones o procesos en segundo plano.","Configuraciones del sistema o del usuario que afecten el rendimiento, autonomía o condición de la batería."],"destacado":false},{"numero":5,"lineas":["Asimismo el Servicio Técnico no realiza reacondicionamientos del equipo bajo ningún concepto."],"destacado":false},{"numero":6,"lineas":["Los equipos que ingresen apagados, bloqueados, sin clave, sin acceso al sistema operativo o sin posibilidad de realizar pruebas funcionales completas, no cuentan con garantía, dado que resulta imposible verificar su correcto funcionamiento al momento del ingreso."],"destacado":false},{"numero":7,"lineas":["El servicio técnico no se responsabiliza, en ningún caso, por la pérdida total o parcial de información, incluyendo —pero no limitado a— datos personales, fotografías, contactos, aplicaciones, configuraciones o contenido multimedia.","Es responsabilidad exclusiva del cliente realizar una copia de seguridad (backup) previa al ingreso del equipo."],"destacado":false},{"numero":8,"lineas":["En equipos con daño por líquido, humedad o sulfatación, el cliente acepta expresamente que la reparación puede ser parcial, limitada o temporal, y que pueden manifestarse fallas futuras sin que ello genere derecho a reclamo, repetición o indemnización alguna."],"destacado":false},{"numero":9,"lineas":["No se garantiza el correcto funcionamiento de Face ID, Touch ID, True Tone, sensores, cámaras u otras funciones, cuando:","No funcionaban correctamente antes del ingreso del equipo.","El equipo sufrió un golpe/caída severa.","La reparación afecte su funcionamiento por limitaciones técnicas, de diseño del fabricante o por el estado general del dispositivo."],"destacado":false},{"numero":10,"lineas":["No se garantiza el correcto funcionamiento de equipos que hayan sido previamente reparados, manipulados o intervenidos por terceros, aun cuando dichas fallas no sean visibles o detectables al momento del ingreso."],"destacado":false},{"numero":11,"lineas":["En el caso de cambio de batería, el cliente declara haber sido debidamente informado sobre la necesidad de:","Realizar copia de seguridad.","Contar con el correo electrónico y contraseña de la cuenta iCloud.","El servicio técnico no realiza intentos de inicio de sesión, desbloqueo ni recuperación de cuentas, ya que el ingreso incorrecto de credenciales puede provocar el bloqueo definitivo del equipo, siendo esta responsabilidad exclusiva del cliente."],"destacado":false},{"numero":12,"lineas":["Los diagnósticos son estimativos y podrán ser actualizados o modificados si, con posterioridad al primer diagnóstico, se detectan fallas adicionales que impidan la reparación total o alteren el alcance inicialmente informado. Dichas situaciones serán notificadas al cliente para su evaluación y aceptación."],"destacado":false},{"numero":13,"lineas":["Una vez confirmada la reparación por parte del cliente, no podrá ser revertida bajo ningún concepto, y el abono del servicio será obligatorio, independientemente del resultado final, siempre que el trabajo haya sido realizado conforme al diagnóstico aceptado."],"destacado":false},{"numero":14,"lineas":["El equipo será entregado únicamente contra el pago total de la reparación y la presentación del comprobante correspondiente."],"destacado":false},{"numero":15,"lineas":["El cliente declara haber sido previamente informado y aceptar los medios de pago habilitados por el servicio técnico, no admitiéndose ningún otro medio distinto a los informados, publicados o comunicados con anterioridad."],"destacado":false},{"numero":16,"lineas":["Los plazos de reparación son estimativos y pueden variar sin que ello genere derecho a reclamo alguno."],"destacado":true},{"numero":17,"lineas":["Transcurridos quince (15) días corridos desde la notificación de reparación finalizada sin que el equipo sea retirado, el valor del servicio podrá ser actualizado. Transcurridos noventa (90) días corridos, el equipo será considerado abandonado.","Previo a su desarme o disposición final, el cliente será notificado por última vez. De no obtener respuesta, se procederá conforme a lo dispuesto en los artículos 870 y 873 del Código Civil y Comercial de la Nación, sin derecho a reclamo posterior."],"destacado":false},{"numero":18,"lineas":["El cliente declara haber leído, comprendido y aceptado en su totalidad los presentes Términos y Condiciones, así como el presupuesto informado y los riesgos inherentes a la reparación del dispositivo."],"destacado":false}],"pie":["FIRMA DEL CLIENTE","ACLARACIÓN","FECHA"]}'::jsonb,
  '2026-11-23T00:00:00-03:00'
)
on conflict (tipo, version) do nothing;
