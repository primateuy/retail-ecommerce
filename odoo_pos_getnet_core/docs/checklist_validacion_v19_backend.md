# Checklist de validación con pinpad — backend Getnet v19

**Para qué es:** correrla frente a la terminal, en una sola sesión, cuando Daryl la agende.
**Qué NO es:** una lista de tests automáticos. Todo lo que se puede probar sin hardware ya está en
la suite (números en el README de la rama). Acá quedó **sólo lo que pide una tarjeta de verdad**.

**De dónde sale:** es la sub-lista de la sección 6 del `staging_checklist.md` de v17 que aplica al
**backend**. Lo del TPV (6.6) no está: el TPV estándar quedó aparcado por decisión de Daryl. Lo que
en v17 ya se cerró contra el concentrador —centavos ×100, `FacturaNro=0` aceptado, permisos sin
Ajustes en seco— se repite igual: es otra versión de Odoo y el criterio de la casa es que
«funcionaba en v17» no es un resultado de v19.

---

## 0 · Prerrequisitos del día (sin esto no arranca)

- [ ] **Tasa USD del día cargada.** Sin ella **Confirmar falla en CUALQUIER pago**, aunque sea en
      pesos, con *«No se encontró tipo de cambio para la fecha … y moneda USD»*. Es lo que dejó el
      pago 2214 de v17 en borrador y el «Confirmar + conciliación» sin ejecutar. Ver la guía de
      instalación, §«La tasa del día».
- [ ] Endpoints de e-factura **en modo testing** verificados (misma guía, §«Compuerta de e-factura»).
- [ ] Terminal **T00001 libre**: `lock_origin` vacío. Es una sola y la comparte la instalación v17.
      Si v17 vuelve a usarse, coordinar antes.
- [ ] Servidor reiniciado después del último `-u` (los cambios en Python no se recargan solos).
- [ ] Anotar **día y hora de inicio** de la tanda. Cada posteo real deja rastro del otro lado.
- [ ] 🔴 **La corrida verde del smoke ya ocurrió.** Ver el bloque de estado de `smoke_v19.md`:
      mientras diga PENDIENTE, esta checklist no arranca. Instalar y configurar sí puede ir antes;
      pasar una tarjeta, no.
- [ ] 🔴 **Moneda de la compañía correcta en la base del cliente.** El mapeo UYU/USD está cubierto
      por tests —`MonedaISO` sale de la moneda del pago y una moneda no soportada se rechaza con
      error claro, nunca se asume pesos—, pero **la prueba con pinpad conviene hacerla en UYU**
      (`0858`). En la base de desarrollo la compañía estaba en USD y el payload salió con `0840`:
      es válido, pero no es lo que se quiere mirar la primera vez frente al equipo.

## 1 · Venta aprobada de punta a punta, CON factura origen

El camino soportado es **Contabilidad > Pagos**. El wizard «Registrar pago» de la factura NO sirve
y no es un defecto: postea el pago al crearlo y el guard lo rechaza.

- [ ] Pago nuevo con diario Getnet → se marca «Cobrar en terminal Getnet» solo.
- [ ] Cargar **una** factura origen en «Facturas origen (Getnet)».
- [ ] «Crear transacción Getnet» → pasar tarjeta real → aprobación.
- [ ] El payload llevó `FacturaNro` real y los `FacturaMonto` / `Gravado` / `IVA` /
      `ConsumidorFinal`. **Es el camino de la devolución de IVA de la ley 19210 y en v17 NUNCA se
      pudo ejecutar** (hasta que el campo llegó a la pantalla, todo cobro salía con FacturaNro=0).
      Criterio: el pinpad no se traba y el voucher sale usable.
- [ ] Persistencia completa en `payment.transaction`: `getnet_ticket`, `getnet_lote`,
      `getnet_nro_autorizacion`, `getnet_tarjeta_id` / `tipo`, `getnet_transaccion_id` y
      `getnet_voucher` con sus renglones.
- [ ] Se creó un `getnet.lote.cierre` en **Abierto** con ese lote, y **no** con lote `0`.
- [ ] **Centavos.** Comparar el `Monto` enviado (importe ×100) contra el que devuelve
      `DatosTransaccion`. En v17 quedó confirmado que el concentrador devuelve el mismo número;
      **acá se vuelve a mirar**, porque si alguna vez difiere hay que sacar el ×100 de
      `getnet_centavos` y de `getnet_montos_factura`.
- [ ] **Confirmar** el pago → se concilia con la factura origen (residual 0).
- [ ] 🔴 **El refresco es manual.** La pantalla va a seguir diciendo «Esperando respuesta de la
      terminal» aunque el dato esté listo en menos de un segundo. Es el backlog conocido del bus,
      no un cuelgue. Anotar cuánto tardó de verdad (mirar `write_date` de la transacción) para no
      confundirlo con lentitud del concentrador.

## 2 · Cobro SIN factura origen (FacturaNro = 0)

- [ ] Pago sin cargar facturas → `FacturaNro=0`, sin los `FacturaMonto*`.
- [ ] Criterio: el pinpad **no pide datos de factura ni se traba**, y el voucher sale usable.
- [ ] Ídem con **varias** facturas cargadas: mismo comportamiento (no hay FacturaNro único).

## 3 · Todo lo anterior como usuario de Contabilidad SIN Ajustes

No es un caso borde: **es quien cobra**. Con admin no se ve nada de esto.

- [ ] Abrir el form del pago. 🔴 En v19 esto reventaba con `AccessError` sobre `payment.provider`
      —es de `base.group_system`— y está arreglado con sudo en los computes. **Verificar que abra.**
- [ ] `EmpHash` **no** es legible para ese usuario (AccessError correcto: el campo es de Ajustes).
- [ ] Crear transacción, pasar la tarjeta, Confirmar y conciliar: el flujo entero, sin AccessError.
- [ ] Entrar al menú «Getnet: requieren conciliación» y que el botón «Marcar como conciliada»
      responda.

## 4 · Devolución real (DEV)

- [ ] Pago **saliente** apuntando a la transacción aprobada del punto 1 → DEV con `TicketOriginal`
      (xs:int, normalizado desde el Ticket que llega como xs:double).
- [ ] Criterio: el concentrador acepta el TicketOriginal y la devolución se aprueba.
- [ ] La devolución **no** toca la línea de cobro original: se registra aparte.

## 5 · Denegada (best-effort)

- [ ] Tantear montos o tarjetas hasta provocar el rechazo. Si el simulador no lo emite, **dejarlo
      registrado**: es dato para homologación, no un test que falló.
- [ ] Criterio: `Aprobada=false` + `ESTADOAVANCE_FINALIZADA_ERROR` → transacción en `error`, pago
      **sigue en borrador**, Confirmar bloqueado, **sin lote registrado**.
- [ ] Tarjeta vencida: en v17 devolvió `CANCELADA(LA TARJETA ESTA VENCIDA…)` → estado `cancel`.
      Correcto. Anotar el texto exacto que sale en v19.

## 6 · Resiliencia

- [ ] **Carrera timeout → cancel:** no pasar la tarjeta hasta que venza el timeout general (180 s).
      Criterio: se envía `CancelarTransaccion` y la consulta siguiente devuelve
      `ESTADOAVANCE_CANCELADA`. Si la cancelación falla porque ya se aprobó, se sigue consultando y
      se persiste la aprobación — **nunca** error por timeout local.
- [ ] **Matar Odoo a mitad de un cobro** → el cron `_getnet_cron_recover_inflight` resuelve la
      transacción y libera la terminal por heartbeat.
- [ ] **RC 9 real:** postear dos veces sin resolver la primera. Criterio: con token propio se
      consulta antes de cancelar; con token ajeno se cancela y se repostea **una sola vez**.
- [ ] **Salida del circuito automático:** una transacción que el cron no resuelve tras 3 pasadas
      aparece en «Getnet: requieren conciliación», deja de re-consultarse y no vuelve a tomar el
      lock. Criterio: al final del día ese menú tiene **exactamente** los casos que sabemos que
      quedaron sin resolver, ni uno más.

## 7 · Cierre de lote real

- [ ] Cerrar el lote con ventas del día. Criterio: `DatosCierre` poblado con la estructura
      jerárquica del WSDL y los totales persistidos coinciden con las ventas del día.
- [ ] 🔴 **Capturar el texto EXACTO** del mensaje de «no hay cierres pendientes». Hoy el fallback a
      `PostearConsultaUltimoCierre` se dispara buscando la subcadena `NO HAY CIERRES`, que no está
      en el WSDL. Si el texto cambió, el fallback no entra.
- [ ] **Finalizado ≠ exitoso:** un cierre sin POS que lo levante termina con
      `Resp_CierreFinalizado=true` pero `ESTADOAVANCE_FINALIZADA_ERROR` y `DatosCierre` vacío.
      Criterio: en ese caso **no** se marca ningún lote como cerrado.
- [ ] Cierre con transacción en vuelo → **bloqueado**; el forzado deja warning con usuario en el log.

## 8 · Al terminar la sesión

- [ ] Terminal liberada (`lock_origin` vacío).
- [ ] Anotar **hora de fin** y la lista de transacciones que quedaron sin resolver.
- [ ] Registrar los resultados **acá mismo**, debajo de cada punto, con fecha. Un resultado que
      vive en un chat se pierde.
