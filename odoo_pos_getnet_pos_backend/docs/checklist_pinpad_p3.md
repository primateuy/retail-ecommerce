# Sesión con pinpad — terminal Getnet en el POS Backend (P3)

**Para correr frente a la terminal**, en una sola sesión, cuando se agende.
Lo que se puede probar sin hardware ya está en la suite: **32/32** en `odoo_pos_getnet_pos_backend`,
incluidos los cuatro pares demo-vs-Getnet. Acá queda **sólo lo que pide una tarjeta de verdad**.

---

## 🔴 Dependencia de despliegue — leer antes de agendar nada

> **Desplegar P3 en cualquier entorno exige que `pos_backend` tenga el hook 7** (la operación de
> cierre de lote) **y el arreglo de liberación.** Eso vive en un commit del repo de campera que
> **todavía no está publicado**:
>
> | | |
> |---|---|
> | commit | `b5cbea5` — *[IMP] pos_backend: cierre de lote de terminal y liberación con cobro en vuelo* |
> | repo | `campera/pos_backend`, rama `19.0` |
> | estado | **local, sin push — pendiente de decisión de Daryl** |
>
> **Sin ese commit publicado, P3 sólo corre donde ese commit esté local.** No es un detalle de
> instalación: sin el hook 7 el cierre de caja no le pregunta nada a la terminal, y sin el arreglo
> de liberación un pedido liberado deja su transacción huérfana. Los dos escenarios de esta
> checklist que dependen de eso están marcados con **[dep b5cbea5]**.

## Prerrequisito que manda sobre todo lo demás

> **La primera corrida verde del smoke contra el concentrador tiene que haber ocurrido.**
> Ver el bloque de estado de `odoo_pos_getnet_core/docs/smoke_v19.md`. Mientras diga PENDIENTE,
> **esta sesión no arranca**: no tiene sentido pasar una tarjeta contra un concentrador que no
> contesta.

## El entorno, ya montado (26-09-2026)

Está hecho y commiteado en `o19_getnet_pb_test`. Esto es para levantarlo el día de la sesión, no
para rehacerlo.

**Arrancar el servidor:**

```bash
cd ~/Odoo/clients/campera
~/Odoo/clients/19.0/Primate-Cloude-Manager/.venv/bin/python \
  ~/Odoo/shared/odoo/community-19.0/odoo-bin \
  -c <conf con el addons_path de campera + retail-ecommerce-19.0> \
  -d o19_getnet_pb_test --http-port=8076
```

El `conf` es el de campera con `~/Odoo/shared/primateuy/retail-ecommerce-19.0` **agregado** al
`addons_path`. Tras cualquier `-u`, **reiniciar**: los cambios en Python no se recargan solos.

**Lo que ya está configurado:**

| | |
|---|---|
| Compañía | `Raciones Campera - LENSOLE S.A`, moneda **UYU** ✓ |
| Tasa USD del día | cargada (sin ella no se confirma ningún pago, ni en pesos) |
| Módulos | `odoo_pos_getnet_core`, `odoo_pos_getnet_backend`, `odoo_pos_getnet_pos_backend`, `pos_backend`, `pos_backend_terminal_demo` — todos instalados y al día |
| Proveedor | *Getnet (TransAct) - Integracion*, estado **Test**, `PRIMA1`, URL de integración, **EmpHASH cargado** |
| Terminal | **T00001**, libre |
| Local / caja | *Local Pinpad P3* / *Caja Pinpad P3* |
| Medio integrado | *Getnet (pinpad)* → diario `GETP3` (banco, no caja) + terminal T00001 |
| Medio alternativo | *Efectivo* → diario `EFEP3`, para probar que la venta sigue viva tras un rechazo |
| Producto | *Producto Pinpad P3*, $1.500 |

**El usuario con el que se opera TODA la sesión:**

| | |
|---|---|
| login | `cajero.pinpad.p3` |
| password | `pinpadp3` |
| grupos | Usuario interno + **Cajero de pos_backend**. **Sin Ajustes, no es admin** |
| empleado | *Cajero Pinpad P3*, rol `cashier`, habilitado en `cashier_ids` del local y responsable de la caja |
| rol efectivo verificado | `cashier` |

> ⚠️ **No operar con admin.** Admin pasa cualquier ACL: el defecto de `payment.provider` que en v19
> impedía abrir el form del pago **sólo se ve con el usuario que cobra**.

Si hubiera que rehacerlo, el snippet de baja (shell de Odoo):

```python
local = env['pos_backend.local'].search([('name', '=', 'Local Pinpad P3')], limit=1)
empleado = env['hr.employee'].search([('name', '=', 'Cajero Pinpad P3')], limit=1)
empleado.pos_backend_role = 'cashier'          # el rol es del EMPLEADO, no del usuario
local.cashier_ids = [(4, empleado.id)]         # habilitado como cajero en ESE local
local.box_ids.responsible_employee_ids = [(4, empleado.id)]
env.cr.commit()
```

---

## Montaje de la base

- [ ] Base **`o19_getnet_pb_test`** (o la que se use), con `pos_backend`,
      `pos_backend_terminal_demo` y `odoo_pos_getnet_pos_backend` instalados.
- [ ] 🔴 **Moneda de la compañía en UYU.** El mapeo UYU/USD está cubierto por tests —`MonedaISO`
      sale de la moneda del pago y una moneda no soportada se rechaza con error claro, nunca se
      asume pesos— pero frente al equipo se quiere ver `0858`. En la base de desarrollo la compañía
      estaba en USD y el payload salía con `0840`: válido, y no es lo que se quiere mirar.
- [ ] Medio de pago **integrado** de la caja, con proveedor `getnet` y su **terminal asignada**
      (`TermCod` real del pinpad).
- [ ] Proveedor en estado **Test** (nace *Deshabilitado*, y así el medio no cobra) con EmpCod y
      EmpHASH del ambiente de integración.
- [ ] 🔴 **Operar con usuarios de rol de `pos_backend`, NO con admin.** Un **cajero real**, con su
      empleado habilitado en el local y la sesión de caja abierta por él. Admin pasa cualquier ACL y
      no prueba nada: el defecto de `payment.provider` que en v19 impedía abrir el form del pago
      sólo se ve con el usuario que cobra.
- [ ] Terminal libre (`lock_origin` vacío) y anotar **día y hora de inicio** de la tanda.

---

## 0 · Concentrador caído — **YA PROBADO, 26-09-2026 18:29**

Este ítem salió gratis: el concentrador de integración estaba caído, así que el camino se ejercitó
de verdad y no simulado. **No hay que repetirlo el día del pinpad.**

- [x] Con el cajero real, sesión abierta por él, pedido tomado de $1.500 en UYU.
- [x] El medio *Getnet (pinpad)* **aparece** en la pantalla de cobro, junto al de efectivo.
- [x] Al intentar cobrar, el error es **honesto y dice la causa**: `HTTP 504 del concentrador`.
      No un «error interno» ni un cuelgue.
- [x] **El pedido queda intacto**: estado `tomado`, total $1.500, y se puede **cobrar en efectivo**
      sin volver a cargar nada.
- [x] **La terminal queda LIBRE** — el lock se suelta en todos los caminos de error.
- [x] La bandeja «requieren conciliación» sigue en **0**.

**Resultado: correcto, con dos hallazgos que cambiaron el código.**

1. 🔴 **`odoo.registry` ya no existe en 19.0** y el wrapper del cursor propio lo usaba. Reventaba
   con `AttributeError` apenas se pedía un cobro. **No lo cazaba ninguna suite**: todos los tests
   sustituyen ese wrapper justamente para ver los datos del test. **El mismo defecto estaba en el
   flujo contable ya publicado** (el cuerpo del hilo del worker). Corregido en los dos, con un test
   que ejecuta la plomería de verdad.
2. 🔴 **Un fallo de transporte no es un rechazo.** El `rc 999` lo pone nuestro cliente SOAP cuando
   no hay respuesta usable (timeout, 502), y el pedido **pudo haber llegado igual**. Se contestaba
   «rechazada», que descarta una transacción que quizá existe — el error del §3.3 que cuesta plata.
   Ahora contesta «no sé»: la línea queda **pendiente y visible** hasta que alguien la concilie.

**Dato para mirar con hardware:** el intento tardó **10,6 s** en dar el error. Es el timeout del
cliente HTTP, no el pinpad. Con la terminal viva el camino es otro, pero si alguna vez el
concentrador se cae en producción, el cajero espera ese tiempo antes de enterarse. Anotar si parece
demasiado.

  - Resultado: **✓ 26-09-2026 18:29** — ver arriba.

## 1 · Cobro aprobado desde la caja

*(par del test `test_par_aprobada_el_pos_queda_igual_con_demo_y_con_getnet`, ahora con pinpad)*

- [ ] Pedido tomado en la caja → pantalla de cobro → medio Getnet → importe → **Agregar**.
- [ ] La terminal pide tarjeta y PIN. **Pasar tarjeta real.**
- [ ] Criterio: la línea de pago queda con `integration_state = **autorizado**`, con su
      **referencia** y su **identificador de transacción** (el ticket).
- [ ] En `payment.transaction`: `getnet_ticket`, `getnet_lote`, `getnet_nro_autorizacion`,
      `getnet_tarjeta_id` / `tipo` y **`getnet_voucher` con los renglones legibles**.
- [ ] Se creó un `getnet.lote.cierre` en **Abierto** con ese lote, y no con lote `0`.
- [ ] **Cuánto tardó de verdad** (mirar `write_date` de la transacción) y **cuánto tardó la
      pantalla**. La ventana de gracia son 4 s por defecto: si el pinpad contestó adentro, el cajero
      no tiene que haber visto ningún pendiente. **Ese es el número que define si la ventana sirve**,
      y no se puede saber sin hardware.
- [ ] Finalizar la venta con esa línea.

  - Resultado:

## 2 · Rechazada real

*(par de `test_par_rechazada_no_deja_linea_y_la_venta_sigue_viva`)*

- [ ] Provocar el rechazo: tarjeta sin fondos, vencida, o tanteando montos. Si el ambiente de
      integración no lo emite, **dejarlo registrado**: es dato para homologación, no un test que
      falló.
- [ ] Criterio: **NO se crea ninguna línea**, el cajero lee **el motivo que dio la terminal** (no un
      error genérico) y la venta **queda exactamente como estaba**, con todos sus medios.
- [ ] Anotar el **texto exacto** que devolvió el adquirente.

  - Resultado:

## 3 · Sin respuesta, con recuperación

*(par de `test_par_sin_respuesta_deja_la_linea_pendiente`)*

- [ ] **No pasar la tarjeta.** Dejar que la ventana de gracia venza.
- [ ] Criterio inmediato: la línea queda **pendiente** con su referencia, **no se descarta nada**, y
      la venta **no se puede finalizar** (§7.2).
- [ ] Dejar correr: el cron de recuperación del núcleo tiene que resolver la transacción sola.
      Criterio: al volver a mirar, la transacción quedó `cancel` (o `done` si alguien pasó la
      tarjeta tarde) y **nunca** en `error` por timeout local.
- [ ] Matar Odoo a mitad de un cobro y verificar que el cron lo resuelve y **libera la terminal por
      heartbeat**.

  - Resultado:

## 4 · El Consultar del cajero

*(par de `test_consultar_resuelve_la_pendiente_de_getnet`)*

- [ ] Con una línea pendiente del punto 3, **pasar la tarjeta** y después tocar **Consultar**.
- [ ] Criterio: la línea pasa a **autorizado** con su ticket y **la venta puede seguir**.
- [ ] Probar también el otro camino: Consultar sobre algo que la terminal informa **no aprobado** →
      la línea se **descarta con el motivo**, queda visible y tachada, y sale en el reporte de
      cierre.

  - Resultado:

## 5 · Liberar con un cobro aprobado → reversa real **[dep b5cbea5]**

*(par de `test_par_liberar_con_cobro_aprobado_reversa_en_ambos`)*

- [ ] Cobrar y aprobar con tarjeta. **Sin finalizar la venta**, liberar el pedido.
- [ ] Criterio: el POS **consulta primero** y recién después pide la reversa. **En TransAct una
      aprobada no se cancela: se devuelve (DEV)** — verificar que el pinpad procese la devolución y
      que la clienta vea las dos líneas en su resumen.
- [ ] La línea **no se borra**: queda `cancelado` + `reversado`, visible, y el pedido vuelve a la
      cola.
- [ ] Probar el caso feo: liberar con la transacción en **«no sé»** (sin pasar la tarjeta) →
      **el pedido NO se libera** y el cajero lee por qué.
- [ ] 🔴 **TODO-homologación abierto:** confirmar con New Age Data si una transacción aprobada y
      **no liquidada** admite una anulación más barata que el DEV. Si la admitiera, cambia el camino
      de la aprobada y el POS no se entera. **Preguntarlo en esta sesión.**

  - Resultado:

## 6 · Cierre de sesión de caja → hook 7 con lote real **[dep b5cbea5]**

- [ ] Con ventas del día en el lote, **cerrar la sesión de caja** del POS Backend.
- [ ] Criterio: el cierre le pide el lote a la terminal, `DatosCierre` viene poblado y los totales
      persistidos **coinciden con las ventas del día**.
- [ ] 🔴 Capturar el **texto exacto** del mensaje de «no hay cierres pendientes»: el fallback a
      `PostearConsultaUltimoCierre` se dispara buscando la subcadena `NO HAY CIERRES`, que **no está
      en el WSDL**. Si el texto cambió, el fallback no entra.
- [ ] **Finalizado ≠ exitoso:** un cierre sin POS que lo levante termina con
      `Resp_CierreFinalizado=true` pero `ESTADOAVANCE_FINALIZADA_ERROR` y `DatosCierre` vacío. En ese
      caso **no** se marca ningún lote como cerrado.
- [ ] Cerrar la caja **con una transacción en vuelo** → el cierre queda **bloqueado** y el mensaje
      dice cuántas hay. Forzar con un Supervisor → cierra, y el reporte de cierre muestra el
      contador de **transacciones en vuelo** aparte del de pedidos sin resolver.

  - Resultado:

## 7 · El cron de los cobros huérfanos

- [ ] Fabricar el caso: dejar una línea **descartada** con la transacción todavía sin resolver, y
      después pasar la tarjeta para que apruebe.
- [ ] Criterio: el cron la encuentra, **reversa** y deja la línea en `reversado` con el motivo. Si
      la reversa falla, la transacción aparece en **«Getnet: requieren conciliación»** y **no se
      reintenta sola**.

  - Resultado:

---

## Al terminar

- [ ] Terminal liberada (`lock_origin` vacío).
- [ ] **«Getnet: requieren conciliación» revisado**: tiene que contener **exactamente** los casos
      que sabemos que quedaron sin resolver, ni uno más.
- [ ] Hora de fin y resultados **escritos acá mismo**, debajo de cada punto, con fecha.

## La regla de siempre

**Resultado por ítem, en el momento.** Un resultado que vive en un chat se pierde.

**Y ante el primer desvío del contrato, se corta.** No se sigue la lista «a ver si lo demás anda»:
si la terminal se aparta de lo que el contrato promete, todo lo que venga después se mide contra
una base que ya no es la acordada. Se anota qué pasó, se corta, y se decide con el dato en la mano.
