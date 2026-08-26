# Checklist de verificación en staging — integración Getnet/TransAct

Deuda de runtime acumulada en las fases 1-4: nada de esto está cubierto por
la suite de tests (que corre con SOAP mockeado y sin navegador). Ejecutar
en orden apenas haya entorno de staging con los módulos instalados.

## 0. Escenario de referencia: Getnet STANDALONE

El escenario principal es una instalación **sin ningún módulo Fiserv**:

    l10n_uy + l10n_uy_einvoice_base/uruware
    + odoo_pos_getnet_core, odoo_pos_getnet_backend, odoo_pos_getnet_pos

Los tres módulos Getnet no dependen de Fiserv ni directa ni transitivamente,
y la suite (56 tests) corre en `test_getnet_backend`, una BD donde los
módulos `odoo_pos_fiserv_*` y `odoo_pos_oca_*` están **uninstalled**. Todo
lo que sigue —salvo la sección 5— se verifica en ese escenario.

- [ ] Instalación limpia de los tres módulos sobre una BD con l10n_uy y
      Uruware, sin Fiserv. **Criterio**: instala sin errores y el form de
      account.payment abre con el grupo «Cobrar en terminal Getnet».
- [ ] Guards de UI propios (no dependen de Fiserv): pago Getnet en
      borrador sin transacción aprobada → botón **Confirmar** oculto;
      con cobro aprobado → **Cancelar** y **Restablecer a borrador**
      ocultos. Los aporta `getnet_post_blocked` / `getnet_cancel_blocked` /
      `getnet_draft_blocked` (odoo_pos_getnet_backend), agregados en modo
      aditivo (`separator=" or " add=...`) para no pisar el `invisible`
      que ya ponen otros módulos sobre esos botones.
      **Criterio**: el arch combinado del form muestra
      `... or getnet_post_blocked` y equivalentes.
- [ ] Los mismos bloqueos por RPC (el ocultar es cosmético): llamar
      `action_post` / `action_cancel` / `action_draft` en cada caso
      levanta `UserError`. Cubierto por tests, reconfirmar en staging.

## 1. Validación de WSDL reales — CERRADA (17/8/2026)

Contratos bajados de testing (`?wsdl` + `?xsd=xsd0..3` de ambos servicios)
y smoke test real con las credenciales de integración de New Age Data:
PostearTransaccion → ConsultarTransaccion → CancelarTransaccion →
ConsultarTransaccion, más PostearConsultaUltimoCierre → ConsultarCierre.

- [x] Namespace y SOAPAction: `http://tempuri.org/` y
      `http://tempuri.org/I<Servicio>/<Método>`. **Confirmado.**
- [x] Namespace de los campos: los hijos de los tipos complejos van en
      `schemas.datacontract.org/2004/07/TransActV4ConcentradorWS.TransActV4Concentrador`,
      no en tempuri. **Corregido** (era un bug: el concentrador habría
      recibido EmpCod/EmpHASH nulos).
- [x] Orden de los elementos: DataContractSerializer exige el orden del
      `xs:sequence` (alfabético) y saltea en silencio lo desordenado.
      **Corregido**: el builder emite por `GETNET_COMPLEX_TYPES`.
- [x] Flag de finalización: `Resp_TransaccionFinalizada` (transacción) y
      `Resp_CierreFinalizado` (cierre). `Resp_Finalizado` no existe.
- [x] `Resp_EstadoAvance` es una enumeración de **strings**
      (`ESTADOAVANCE_ENPROCESO`, ...), no un int. **Corregido** — con el
      parser viejo nunca se detectaba una cancelación.
- [x] Código del autorizador: `CodRespAdq` (no `CodRespuesta`, que solo
      existe en el cierre). **Corregido.**
- [x] Voucher es `ArrayOfstring` (renglones en `<string>` del namespace de
      Arrays). **Corregido** — antes quedaba vacío.
- [x] Numéricos: `Monto`/`FacturaNro`/`Ticket`/`Lote` son `xs:double`;
      `TicketOriginal` es `xs:int`. **Corregido** con normalización.
- [x] `TarjetasCierre_400`: `DatosCierre` es un ARRAY de `IDatosCierre`
      (uno por procesador) con los totales en `Extendida`, y los mismos
      nombres se repiten en `Productos>Monedas>Planes>...`. **Corregido**:
      se lee del árbol, nunca del aplanado.

Verificado en vivo contra `testing-concentrador`: posteo RC 0 +
`TokenNro`, consulta con `ESTADOAVANCE_PENDIENTE_PROCESO`, cancelación
RC 0 y consulta final con `ESTADOAVANCE_CANCELADA` /
`Resp_TransaccionFinalizada=true` / `MsgRespuesta=CANCELADA(DESDE EL ERP)`.

Dos reglas permanentes del módulo salieron de acá:
- **Fallo fuerte en el builder**: un campo ajeno al contrato levanta
  ValueError en vez de viajar nulo (WCF lo descartaría en silencio).
- **Finalizado ≠ exitoso**: `Resp_*Finalizado=true` solo dice que el
  concentrador terminó. `ESTADOAVANCE_FINALIZADA_ERROR` y `_CANCELADA`
  son finales de fracaso; una respuesta que se contradice (Aprobada=true
  con estado final de error) NO se resuelve en ningún sentido: queda
  `pending` para conciliación manual, como un timeout.
- Corolario visto en testing: `Lote='0'` significa "sin lote", no lote
  cero; como texto es truthy y creaba un `getnet.lote.cierre` fantasma.
- **El circuito automático tiene salida**: `pending` es un estado de
  espera, no un depósito. Todo lo que el cron no puede resolver
  re-consultando (respuesta final contradictoria, o sin respuesta final
  tras `GETNET_RECOVERY_MAX_INTENTOS` pasadas) se marca
  `getnet_requiere_conciliacion`, sale del cron y aparece en el menú
  «Getnet: requieren conciliación». Sin eso, esas transacciones se
  re-consultaban cada 5 minutos para siempre, tomando el lock de la
  terminal en cada pasada.

### FacturaNro: el XSD miente (verificado 17/8/2026)

`FacturaNro` está declarado `minOccurs="0"` pero el concentrador lo exige
a nivel funcional. Probado contra el ambiente de integración:

| payload | respuesta |
|---|---|
| sin ningún `Factura*` | `rc=2 CAMPO REQUERIDO / VERIFIQUE / FACTURA` |
| solo `FacturaNro=1` | `rc=0 POSTEADA OK!` |
| solo `FacturaNro=0` | `rc=0 POSTEADA OK!` |
| `FacturaNro=0` + montos en 0 | `rc=0 POSTEADA OK!` |
| completo (Nro + montos + ConsFinal) | `rc=0 POSTEADA OK!` |

De ahí el criterio implementado: con UNA factura origen van todos los
`Factura*`; sin factura o con varias va `FacturaNro=0` y se omiten
`FacturaMonto`/`Gravado`/`IVA`/`ConsumidorFinal`, que sí son opcionales
de verdad. Lo mismo en el TPV, donde se cobra antes de emitir el CFE.
Falta ver con pinpad real qué imprime o pregunta con `FacturaNro=0`.

### Permisos (verificado 17/8/2026)

El core solo da ACL de `payment.transaction` a `base.group_system`: sin
esto, ni un contador ni un cajero podían operar el flujo. Se resolvió con
`sudo()` en la máquina (creación de la transacción, hilos de polling,
marca de conciliación) + un ACL de **solo lectura** para
`account.group_account_user` para que la lista, el form del pago y el
menú de conciliación funcionen. El botón «Marcar como conciliada» escribe
en sudo, así que su permiso real es la guarda del método (grupo de
contabilidad), no el ACL ni la vista.

Queda pendiente de POS físico (no se puede cerrar sin terminal):
- [ ] Cierre de lote con `DatosCierre` poblado: sin un POS que levante la
      transacción, el cierre termina en `EXPIRADA(POS NO BUSCO
      TRANSACCION)` con `DatosCierre` vacío. **Criterio**: los totales de
      `DatosCierre[*].Extendida` se persisten en getnet.lote.cierre.
- [ ] Transacción aprobada real: confirmar que `Monto` va en centavos
      (×100, criterio del manual) comparando el `Monto` que devuelve
      `DatosTransaccion` con el importe cobrado, y que
      `Ticket`/`Lote`/`NroAutorizacion`/`Voucher` llegan poblados.
- [ ] Texto exacto del mensaje de "no hay cierres pendientes" que dispara
      el fallback a `PostearConsultaUltimoCierre` (hoy se busca la
      subcadena `NO HAY CIERRES`).

## 2. JS del POS (odoo_pos_getnet_pos) — sin cobertura de tests
- [ ] Registro del método: abrir POS con método Getnet → la línea de pago
      muestra "Enviar" (payment_terminal activo). **Criterio**:
      `register_payment_method('getnet')` cargó (sin errores de import en
      consola; verificar bundle `point_of_sale._assets_pos`).
- [ ] Flujo de cobro: posteo → waitingCard → aprobación por bus resuelve
      la línea. **Criterio**: cobro en ModoEmulacion termina la orden.
- [ ] Cancelación desde el TPV (botón rojo de la línea) → CancelarTransaccion.
- [ ] Bus filtrado por config: dos cajas abiertas, el mensaje de una no
      resuelve la línea de la otra.
- [ ] Devolución POS: reembolso de una orden cobrada con Getnet → DEV con
      TicketOriginal correcto.
- [ ] Ideal: tour de point_of_sale que cubra el camino feliz.

## 3. Backlog menor UI
- [ ] Botón de reimpresión del voucher en la pantalla de recibo del POS
      (RPC `pos.order.get_getnet_voucher` ya disponible). **Criterio**:
      reimprimir el voucher de una orden cobrada.
- [ ] JS de refresh del backend: escuchar
      `getnet_account_payment_<id>` / `getnet_account.payment_refresh`
      y hacer doAction al mismo res_id (patrón del refresh service de
      Fiserv; NUNCA soft_reload). **Criterio**: el form del pago se
      refresca solo al aprobar el pinpad.

## 4. Flujos de resiliencia con hardware real
- [ ] Carrera timeout→cancelar→aprobada contra POS físico.
- [ ] Kill de Odoo a mitad de un cobro → el cron de recuperación resuelve
      la transacción y libera la terminal (heartbeat).
- [ ] Cierre de lote con transacción en vuelo → bloqueo; forzar deja
      warning en log con usuario.

## 6. Sesión con POS físico — guion ordenado

**El ambiente de integración es SIMULADO: no autoriza cargos reales**
(New Age Data, 17/8/2026). No hay que cuidar importes ni saldos, así que
se puede probar con los montos que convengan. La devolución de 6.2 se
mantiene porque es prueba funcional del DEV + TicketOriginal, no de saldo.

Ejecutar EN ESTE ORDEN; cada paso deja su resultado escrito acá abajo.
**Si el contrato real vuelve a sorprender, cortar y reportar antes de
seguir** (el pasaje anterior por los WSDL encontró 9 desvíos: la
probabilidad de que aparezca otro no es baja).

### 6.0 Multi-terminal: cómo se elige el pinpad — VERIFICADO (22/8/2026)

Verificado en `o17_agrosiembra_staging_new` creando una segunda terminal
dummy (`T00099`, que NO existe en TransAct) y activando
**Múltiples terminales** (`getnet_is_multiple`) en el proveedor.

**Flujo contable (account.payment y wizard Registrar Pago)**

El selector «Terminal Getnet» aparece solo cuando hay algo que elegir:

    getnet_need_terminal_choice = provider.getnet_is_multiple AND len(terminales) > 1

- [x] Con **una** terminal el campo está oculto y se preselecciona sola
      (onchange del diario). Es la razón por la que el selector no se ve
      en la configuración actual: no falta nada, no hay qué elegir.
- [x] Con **dos** terminales el campo se muestra, NO se preselecciona
      ninguna y es **obligatorio**: el arch combinado del form trae
      `invisible="not getnet_is_getnet_payment_line or not
      getnet_need_terminal_choice"` y
      `required="getnet_charge_on_pos and getnet_need_terminal_choice"`.
      Guardar sin elegir falla en la vista, y por RPC
      `_getnet_terminal()` levanta UserError: nunca hay terminal "por
      defecto".
- [x] El payload sigue a la terminal **elegida**, no a la primera:
      `TermCod='T00001'` y `TermCod='T00099'` según la selección
      (`_getnet_prepare_transaccion_vals`).
- [x] El wizard Registrar Pago tiene el mismo selector y pasa la elegida
      al pago (`_getnet_payment_vals`).
- [x] `getnet_is_multiple` es un interruptor, no un dato de TransAct: si
      se cargan dos terminales y el flag queda apagado, el selector no
      aparece y el cobro muere con UserError al pedir la terminal.
      **Regla de configuración: alta de la segunda terminal ⇒ prender el
      flag en el mismo paso.**

Cubierto ahora por tests (`odoo_pos_getnet_backend`): terminal única,
dos terminales, TermCod del payload y wizard.

**TPV: una caja = un pinpad**

La terminal se ata en **`pos.payment.method`** (`getnet_terminal_id`), no
en `pos.config`. Con varias cajas, cada una necesita:

1. una `getnet.pos.terminal` por pinpad (TermCod real de New Age Data);
2. un `pos.payment.method` por pinpad, con `use_payment_terminal='getnet'`,
   su `getnet_provider_id` y su `getnet_terminal_id`;
3. ese método asignado a los `payment_method_ids` de **su** `pos.config`.

Es configuración: no hace falta UI nueva. Verificado que cada método
resuelve su propio TermCod, que un método sin terminal fijada y con más
de una en el proveedor exige configurarla (UserError), y que el JS no
necesita saber la terminal (el `getnet_enviar_pago` la resuelve
server-side desde el `pos.payment.method` de la línea). El lock es por
terminal, así que dos cajas con pinpads distintos no se bloquean entre
sí, y el bus ya filtra por `id_config`.

- [ ] **Pendiente de hardware**: dos cajas abiertas cobrando a la vez,
      cada una contra su pinpad.

**Defecto encontrado y corregido en esta verificación**:
`pos.session._getnet_terminales()` devolvía la unión de la terminal del
método **y todas las del proveedor**. Con dos cajas, cerrar la caja 1
(a) se bloqueaba por las transacciones en vuelo del pinpad de la caja 2 y
(b) le **cerraba el lote a mitad del turno**. Ahora devuelve solo las
terminales de los métodos de pago de esa caja (con el mismo atajo de
proveedor-con-una-sola-terminal que usa `_getnet_terminal()`, y un
warning en el log si un método quedó sin terminal). Con una sola terminal
el comportamiento no cambia. Cubierto por test.

**Ojo con la terminal dummy**: mientras exista `T00099` el selector es
obligatorio en todo cobro Getnet del backend. Antes de 6.1a hay que
borrarla y apagar `getnet_is_multiple`, o asegurarse de elegir `T00001`
en cada posteo (`T00099` no existe en TransAct).

### 6.1 Venta aprobada de punta a punta (backend)
- [ ] Pago contable con factura origen → «Crear transacción Getnet» →
      pasar tarjeta real → aprobación.
- [ ] Persistencia completa en payment.transaction: `getnet_ticket`,
      `getnet_lote`, `getnet_nro_autorizacion`, `getnet_tarjeta_id/tipo`,
      `getnet_transaccion_id` y `getnet_voucher` con los renglones
      (ArrayOfstring) separados por salto de línea.
- [ ] Lote: se crea un `getnet.lote.cierre` en Abierto con ese lote (y
      NO con lote '0').
- [ ] **Pendiente empírico de centavos**: comparar el `Monto` enviado
      (importe ×100, `getnet_centavos`) contra el `Monto` que devuelve
      `DatosTransaccion` en la consulta. **Criterio**: si el concentrador
      devuelve el mismo número que enviamos, ×100 es correcto; si
      devuelve el importe en unidades, hay que sacar el ×100 de
      `getnet_centavos` y de `getnet_montos_factura` (afecta también
      FacturaMonto/Gravado/IVA).
- [ ] Confirmar el pago y verificar la conciliación con la factura origen.
- [ ] Cobro sin factura origen y con varias facturas: van con
      `FacturaNro=0`. **Criterio**: el pinpad no se traba ni pide datos de
      factura, y el voucher sale usable (es el único punto del criterio
      nuevo que no se puede validar sin hardware).
- [ ] Hacerlo con un usuario de Contabilidad SIN el grupo Ajustes: el
      flujo completo (crear transacción, ver el form, conciliar) tiene que
      funcionar. El core solo da ACL de payment.transaction a
      base.group_system; si algo revienta con AccessError, falta un sudo.

  - **Resultado (17/8/2026, staging con Fiserv, pago 2214, $1288)**:
    cobro **APROBADO** con tarjeta real. Ticket 2, lote 1, autorización
    E02001, TarjetaTipo DEB, voucher con 62 renglones legibles. La
    transacción resolvió en menos de 1 segundo desde el posteo.
    - **Centavos: CONFIRMADO.** Enviado `Monto=128800` para $1288,00 y el
      concentrador devuelve `Monto=128800`. El ×100 de `getnet_centavos`
      queda como está (y con él `getnet_montos_factura`).
    - **`FacturaNro=0`: aceptado.** Se devuelve `FacturaNro=0` en la
      respuesta y el pinpad no pidió nada extra ni se trabó. Riesgo
      residual cerrado.
    - Reintentos sobre el mismo pago: 3 transacciones (`error` por
      `CAMPO NO VALIDO`, `cancel` por tarjeta vencida, `done`). El flujo
      tolera reintentar sin ensuciar el pago.
    - Tarjeta vencida → `CANCELADA(LA TARJETA ESTA VENCIDA |
      VENCIMIENTO=0326 | ESPECIFIQUE EL CAMPO FALTANTE Y REINTENTE)`,
      mapeada a estado `cancel`. Correcto, aunque el mensaje que ve el
      usuario ("no fue aprobada (estado: cancel)") podría mostrar el
      texto del adquirente.
    - **Confirmar por bus/refresh: NO funciona** (backlog conocido de la
      sección 3). El pago quedó mostrando "Esperando respuesta de la
      terminal" hasta refrescar a mano, pese a que el dato estaba listo
      en <1s. Es lo que se percibe como "esperar mucho tiempo".
    - **3 defectos encontrados y corregidos** — ver más abajo.
  - Pendiente de esta sesión: repetir con usuario de Contabilidad sin
    grupo Ajustes.

### Defectos encontrados en 6.1 (17/8/2026)

**1. Faltaban los `account.payment` methods de Getnet** (detectado en la
preparación). Sin un `account.payment.method` con código `getnet`,
`account_payment._ensure_payment_method_line()` sale sin hacer nada y el
diario nunca recibe la línea: el flujo contable **no se puede ni
configurar**. Los tests no lo veían porque creaban métodos ad-hoc.
Agregados al core (inbound + outbound, este último para las devoluciones).

**2. `fiserv_charge_on_pos` pegado bloquea Confirmar** (convivencia). El
onchange de Fiserv marca su check al elegir un diario Fiserv —y el form de
pagos abre en uno por defecto— pero **no lo desmarca** al cambiar de
diario. En un pago Getnet el check queda pegado y, como la vista de Fiserv
repite sus condiciones además del flag compartido, el botón Confirmar
queda oculto **para siempre** aunque el cobro esté aprobado en el pinpad.
Corregido en el puente (no se tocó Fiserv, que es compartido): se ignoran
los términos Fiserv en pagos Getnet y se limpia el check pegado tanto por
onchange como al iniciar el cobro. **El bug de origen es de Fiserv y sigue
ahí**: cualquier pago que pase por un diario Fiserv antes de cambiar de
diario arrastra el check.

**3. Odoo auto-creaba un `account.payment` duplicado** (afecta al
escenario STANDALONE, el principal). `_reconcile_after_done()` llama a
`_create_payment()` para toda transacción `done` sin `payment_id`, y las
nuestras cumplen esa condición: en standalone, cada cobro Getnet aprobado
habría generado un pago contable extra **posteado**, duplicando el importe
en los libros. En esta staging no ocurrió solo porque el override de
Fiserv interceptaba la llamada — es decir, **el escenario con Fiserv tapa
un bug del escenario sin Fiserv**. Corregido en el core: Getnet nunca
auto-crea account.payment (el del flujo contable ya existe y lo confirma
el usuario; en el TPV el cobro es el pos.payment).

### 6.1a Usuario de Contabilidad SIN grupo Ajustes

Ensayo **en seco** hecho el 22/8/2026 en `o17_agrosiembra_staging_new`
(SOAP mockeado, `getnet_safe_commit` neutralizado, todo en rollback) con
dos usuarios reales: **Mauro Olveira** (solo *Facturación*,
`account.group_account_user`) y **Cristina Serres** (*Facturación* +
*Contable*). Ninguno tiene *Ajustes*. Sirve para descartar AccessError
antes de pararse frente al pinpad; el paso de la tarjeta sigue pendiente.

- [x] Lee proveedor y terminal; **EmpHash NO es legible** sin Ajustes
      (AccessError correcto, el campo es `groups='base.group_system'`).
- [x] Crea el `account.payment` y ve los guards: `post_blocked=True`,
      `action_post` rechazado con UserError antes del cobro.
- [x] Arma el payload leyendo el hash por sudo: `TermCod=T00001`,
      `EmpCod=PRIMA1`, `Monto=194956` (1949,56 ×100),
      `FacturaNro=79961`, `FacturaConsumidorFinal=True` (e-Ticket 101).
- [x] «Crear transacción Getnet»: toma el lock, persiste token y terminal.
- [x] Worker (polling + `bus.bus` + `message_post`) con el uid del
      operador: sin AccessError. Transacción `done` con ticket, lote,
      autorización, tipo de tarjeta y voucher; `getnet.lote.cierre`
      creado en Abierto.
- [x] Guards post-cobro: `cancel_blocked` y `draft_blocked` en True.
- [x] **Confirmar**: pago `posted` y conciliado con la factura origen
      (residual 0).
- [x] Lee `payment.transaction` (lista y form), entra al menú
      «requieren conciliación» y el botón «Marcar como conciliada» le
      responde.
- [ ] **Pendiente de hardware**: repetir pasando la tarjeta real.

**Prerrequisito de staging descubierto acá**: `aml_secondary_currency`
exige tasa de la **fecha exacta** del asiento, y las tasas USD estaban
cargadas hasta el 5/8/2026. Sin la tasa del día, **Confirmar falla en
cualquier pago** (aunque sea en UYU) con *"No se encontró tipo de cambio
para la fecha ... y moneda USD"*. Es lo que dejó el pago **2214 del 6.1
en borrador**: el cobro se aprobó pero nunca se confirmó, así que el
"Confirmar + conciliación" de 6.1 quedó sin ejecutar. Cargar la tasa del
día antes de cada sesión de pruebas (`clients/Agrosiembra/getnet_tasa_hoy.py`
copia la última conocida).

### Factura origen: cómo se carga (resuelto 22/8/2026)

`getnet_source_invoice_ids` **no estaba en ninguna pantalla**. El único
lugar que lo llenaba era el wizard «Registrar pago» de la factura, y ese
wizard no sirve para este flujo: `action_create_payments()` postea el
pago apenas lo crea y el guard de `action_post` lo rechaza con *"debe
cobrarse en la terminal Getnet antes de confirmarse"*. Verificado el
22/8/2026 con los dos usuarios contables. **`odoo_pos_fiserv_backend`
tiene el mismo agujero** (su `action_post` levanta un UserError
equivalente), así que no era una regresión nuestra. Consecuencia: hasta
hoy, desde la UI, **todo cobro Getnet salía con `FacturaNro=0`** — el
pago 2214 del 6.1 fue sin factura origen (`getnet_payment_invoice_rel`
estaba vacía) y el camino con FacturaNro real + `FacturaMonto` /
`Gravado` / `IVA` / `ConsumidorFinal` (el de la devolución de IVA de la
ley 19210) nunca se pudo ejecutar.

**Resuelto**: el campo se agregó al form del pago (`many2many_tags`,
visible en cobros Getnet entrantes, editable mientras el pago está en
borrador, con dominio de facturas del cliente publicadas e impagas).
El wizard queda como está — el camino soportado es
**Contabilidad > Pagos**, igual que en Fiserv:

1. Pago nuevo, diario Getnet → se marca «Cobrar en terminal Getnet».
2. Cargar la(s) **factura(s) origen** en el campo nuevo.
3. «Crear transacción Getnet» → pinpad → aprobación.
4. **Confirmar** → se concilia con la factura origen.

Con UNA factura viaja su FacturaNro y los montos; con ninguna o varias
va `FacturaNro=0` (criterio de New Age Data del 17/8, sin cambios).

Defecto del mismo tramo, corregido:
`_getnet_reconcile_with_source_invoices()` llamaba `.reconcile()` sin
agrupar por cuenta. Con pago y factura en cuentas de deudores distintas
(p. ej. UYU vs USD) levantaba *"Entries are not from the same account"*
**dentro de `action_post`**, abortando la confirmación de un cobro YA
APROBADO en el pinpad. Ahora solo se empareja lo que comparte cuenta, el
fallo se registra en el chatter y en el log, y el pago se confirma igual:
la plata está cobrada, emparejarla es administrativo. Cubierto por test.

Queda anotado (NO se tocó): el wizard asigna `getnet_charge_on_pos`
—campo normal— dentro de un compute, así que después de `create()` se lee
`False`. Debería ser default + onchange. Hoy no molesta porque el camino
del wizard no se usa.

### 6.2 Devolución real (DEV)
- [ ] Pago saliente apuntando a la transacción de 6.1 → DEV con
      `TicketOriginal` (ahora **xs:int**, normalizado desde el Ticket que
      llega como xs:double). **Criterio**: el concentrador acepta el
      TicketOriginal y la devolución se aprueba.
  - Resultado:

### 6.3 Denegada
- [ ] Al ser simulado, se puede probar libremente: tantear montos y
      tarjetas hasta provocar el rechazo, o dejar registrado que el
      simulador no lo emite (dato para homologación).
- [ ] **Criterio**: `Aprobada=false` + `ESTADOAVANCE_FINALIZADA_ERROR` →
      transacción en `error`, pago sigue en borrador, Confirmar bloqueado,
      SIN lote registrado. (Cubierto por tests en los tres caminos —
      worker backend, cron y línea POS — falta la confirmación real.)
  - Resultado:

### 6.4 Resiliencia con hardware
- [ ] Carrera timeout→cancel: no pasar la tarjeta hasta que venza el
      timeout general (180s). **Criterio**: se envía CancelarTransaccion y
      la consulta siguiente devuelve `ESTADOAVANCE_CANCELADA`; si la
      cancelación falla porque ya se aprobó, se sigue consultando y se
      persiste la aprobación (nunca error por timeout local).
- [ ] Kill de Odoo a mitad de un cobro → el cron
      `_getnet_cron_recover_inflight` resuelve la transacción y libera la
      terminal por heartbeat.
- [ ] RC 9 real: postear dos veces sin resolver la primera. **Criterio**:
      con token propio se consulta antes de cancelar; con token ajeno se
      cancela y se repostea una sola vez.
- [ ] Salida del circuito automático: una transacción que el cron no
      resuelve tras `GETNET_RECOVERY_MAX_INTENTOS` pasadas (3) aparece en
      «Getnet: requieren conciliación», deja de re-consultarse y no vuelve
      a tomar el lock de la terminal. **Criterio**: revisar el menú al
      final del día de pruebas — debería contener exactamente los casos
      que sabemos que quedaron sin resolver, ni uno más.
  - Resultado:

### 6.5 Cierre de lote real
- [ ] Cerrar lote con ventas del día en el lote. **Criterio**:
      `DatosCierre` poblado, estructura jerárquica como el WSDL
      (`IDatosCierre[*].Extendida` con los totales, `Productos>Monedas>
      Planes>...` con los subtotales) y los totales persistidos coinciden
      con las ventas del día.
- [ ] Capturar el **texto exacto** del mensaje de "no hay cierres
      pendientes" para afinar el fallback a `PostearConsultaUltimoCierre`
      (hoy se busca la subcadena `NO HAY CIERRES`).
- [ ] Cierre con transacción en vuelo → bloqueado; el forzado deja
      warning con usuario en el log.
  - Resultado:

### 6.6 POS de Odoo con caja real (la parte JS que nunca corrió)
- [ ] Registro del método (`register_payment_method('getnet')`) sin
      errores de import en consola.
- [ ] Cobro: posteo → waitingCard → el bus resuelve la promesa de la línea.
- [ ] Cancelación desde la caja (botón rojo de la línea).
- [ ] Devolución desde el POS sobre una orden cobrada con Getnet.
- [ ] Voucher: renglones disponibles para reimpresión
      (`pos.order.get_getnet_voucher`).
  - Resultado:

## 5. (SECUNDARIO) Convivencia con Fiserv — `odoo_pos_getnet_fiserv_flags`

**Solo se ejecuta si aparece un cliente con ambos adquirentes.** No es
requisito de la puesta en producción de Getnet: en standalone este módulo
puente no se instala (es `auto_install` y exige los dos backends, así que
no agrega dependencia ninguna al escenario de la sección 0).

Por qué existe: `odoo_pos_fiserv_backend` (priority 15) y
`odoo_pos_fiserv_backend_internal_transfer_payment_fix` (priority 99)
**reemplazan el `invisible` entero** de esos botones. Con las priorities
actuales el aditivo de Getnet (priority 16) se aplica después de
fiserv_backend y sobrevive, pero NO sobrevive a un reemplazo de priority
99. El puente cubre ese caso: mergea `getnet_*_blocked` dentro de los
flags compartidos `pos_integrated_*` que esas vistas sí incluyen, sin
duplicar la condición.

Verificado en la BD `test_getnet_fiserv` (clon de la standalone +
`-i odoo_pos_fiserv_backend`, el puente auto-instaló): sin transacción
`getnet_post_blocked` y `pos_integrated_post_blocked` valen True; con
cobro aprobado pasan a False y se activan cancel/draft. Falta la parte de
UI real:

- [ ] Con AMBOS backends instalados: pago Getnet en espera → Confirmar
      oculto; pago Fiserv → comportamiento sin cambios.
- [ ] Cobro Getnet aprobado → Cancelar y Restablecer a borrador ocultos.
- [ ] Instalar también `internal_transfer_payment_fix` (dispara el módulo
      de priority 99) y repetir: ahí el bloqueo depende solo del flag
      compartido, no del aditivo.
- [ ] Observación ajena a Getnet, para reportar al equipo Fiserv: en una
      BD con `l10n_uy_einvoice_base` su vista (priority 16) reemplaza el
      `invisible` de **Restablecer a borrador** por
      `state not in ('posted','cancel') or es_resguardo or cfe_emitido`,
      borrando `pos_integrated_draft_blocked`. El botón de Fiserv queda
      visible (el guard de Python igual lo frena). Getnet no se ve
      afectado porque su término es aditivo.
- [ ] Nota: la convivencia con `odoo_pos_oca_backend` (priority 50, también
      reemplaza el atributo) NO tiene puente equivalente. Si algún día se
      da esa combinación, hace falta un módulo espejo Getnet↔OCA.
