# Doble aterrizaje Getnet — arreglos que valen para 17.0 y para 19.0

El port a 19.0 no sólo traduce API: al correr el flujo con usuarios y datos
reales aparecen defectos que **también existen en la rama 17.0**. Este archivo
los registra para que el arreglo aterrice en las dos ramas y no quede uno
bueno y otro viejo.

Formato de cada entrada: qué se rompe, cómo se ve, el arreglo, y el estado en
cada rama. Nada se cierra acá por "ya está en 19" — la línea de 17.0 tiene que
decir *commiteado* con su hash.

## Estado global

| | rama | estado |
|---|---|---|
| DL-1 | `19.0_getnet` | commiteado en `c719fc5` |
| DL-1 | `17.0_getnet` | **pendiente en 17.0** — programado para la próxima ventana de trabajo sobre v17 |
| DL-2 | `19.0_getnet` | commiteado en `c719fc5` |
| DL-2 | `17.0_getnet` | **pendiente en 17.0** — programado para la próxima ventana de trabajo sobre v17 |
| DL-3 | `19.0_getnet` | commiteado en `c719fc5` |
| DL-3 | `17.0_getnet` | **pendiente en 17.0** — programado para la próxima ventana de trabajo sobre v17 |
| DL-5 | `19.0_getnet` | commiteado (ver la entrada) |
| DL-5 | `17.0_getnet` | **pendiente en 17.0** — programado para la próxima ventana de trabajo sobre v17 |

«Pendiente en 17.0» es un estado con dueño y fecha, no una duda: los cuatro
aterrizan como commits locales en `17.0_getnet` en la próxima sesión que toque
v17 —puede ser la reanudación de la sección 6— y hasta entonces esta tabla dice
pendiente. Cuando aterricen, la fila lleva el hash y deja de decir pendiente.

---

## DL-1 · El form del pago no abre para un contador (AccessError en `payment.provider`)

**Qué se rompe.** `_compute_getnet_is_getnet_payment_line`,
`_compute_getnet_is_integrated_journal` y `_getnet_provider()` leen
`payment_method_line_id.payment_provider_id.code`. `payment.provider` tiene ACL
de lectura **sólo** para `base.group_system`
(`addons/payment/security/ir.model.access.csv`, idéntico en 17.0 y en 19.0).
Los tres son computes del form, así que se evalúan al cargar la pantalla.

**Cómo se ve.** Un usuario de contabilidad sin Ajustes —el que cobra— no puede
**abrir** un `account.payment`: sale `AccessError` sobre `payment.provider`
antes de mostrar nada. Con admin no se ve nunca, y admin es con quien se
probó. En el log:

    Access Denied by ACLs for operation: read, uid: N, model: payment.provider

**Arreglo.** `.sudo()` sobre el proveedor en los dos computes y en
`_getnet_provider()`. Se lee sólo `code` / `getnet_terminal_ids`; las
credenciales TransAct no llegan a la vista. La alternativa —dar lectura de
`payment.provider` a `account.group_account_user` desde el core— se descartó:
expondría `getnet_emp_hash` por ORM a todos los contadores.

**Regresión que lo fija.** `test_el_form_del_pago_abre_para_el_contador` y
`test_el_contador_no_puede_leer_payment_provider` (el segundo avisa si algún
día se ampliara la ACL y los `sudo()` pudieran revisarse).

- **19.0** — commiteado en `c719fc5` (`odoo_pos_getnet_backend`, rama
  `19.0_getnet`).
- **17.0** — **pendiente en 17.0**, programado para la próxima ventana de
  trabajo sobre v17. Mismo código y mismas ACLs: se rompe igual, y hoy un
  contador de Forum no puede abrir un pago Getnet.

---

## DL-2 · `numero_cfe()` no es el de `l10n_uy_einvoice_base` en una BD de cliente

**Qué se rompe.** `_getnet_factura_vals_from_move` hace `move.numero_cfe()` y
después pregunta `if not numero`. Eso asume la implementación de
`l10n_uy_einvoice_base`, que saca los dígitos del nombre del asiento y
devuelve `''`. Pero `l10n_uy_einvoice_uruware` **sobrescribe** el método y
levanta `ValidationError('No se ha emitido el cfe...')` cuando la factura no
tiene el CFE firmado. En un cliente el que corre es el de uruware.

**Cómo se ve.** Al crear la transacción con una factura origen todavía sin
firmar, el contador recibe «No se ha emitido el cfe, por lo tanto no hay
número de cfe»: no dice qué factura, ni que lo que se cayó fue el cobro
Getnet. No hay riesgo de plata —revienta antes del posteo al concentrador—,
pero el mensaje manda a buscar en el lugar equivocado.

**Arreglo.** Envolver la llamada y volver a levantar el `UserError` propio, que
nombra la factura y dice que es el cobro Getnet.

**Regresión que lo fija.**
`test_factura_sin_cfe_firmado_da_error_que_nombra_la_factura`. Y el fixture de
tests (`_sellar_cfe`) ahora deja la factura como si Uruware la hubiera
firmado: probar contra el `numero_cfe()` de base daba verde sobre un camino
que en el cliente no se ejecuta nunca.

- **19.0** — commiteado en `c719fc5` (`odoo_pos_getnet_backend`, rama
  `19.0_getnet`).
- **17.0** — **pendiente en 17.0**, programado para la próxima ventana de
  trabajo sobre v17. Mismo código; se dispara en cuanto uruware está
  instalado, que es siempre en producción.

---

## DL-3 · `domain` de `getnet_source_invoice_ids` partido en cinco líneas

**Qué se rompe.** El `domain` del campo estaba escrito en cinco líneas dentro
del atributo XML. Es Python válido y el servidor lo guarda sin mirarlo; el
evaluador del navegador es el que puede no aceptarlo. La regla de la casa es
explícita: un `domain` o `context` partido en dos líneas no se escribe.

**Arreglo.** Colapsado a una línea. No cambia el filtro.

- **19.0** — commiteado en `c719fc5`.
- **17.0** — **pendiente en 17.0**, programado para la próxima ventana de
  trabajo sobre v17 (mismo archivo, mismo campo).

---

---

## DL-4 · `l10n_uy_einvoice_base` pisaba el botón «Restablecer a borrador» con estados de 17.0

**Qué se rompe.** `l10n_uy_einvoice_base/views/account_payment_view.xml`
reemplaza el atributo entero:

    <attribute name="invisible">state not in ('posted', 'cancel') or es_resguardo or cfe_emitido</attribute>

En 19.0 `account.payment.state` ya no tiene `posted` ni `cancel` (es
`draft / in_process / paid / canceled / rejected`), así que la condición es
verdadera siempre y el botón **queda invisible para todos los pagos**. No falla
al instalar: la vista valida, el botón simplemente no aparece.

**Cómo se ve.** Medido sobre el arch servido:

    antes:    invisible=(state not in ('posted', 'cancel') or es_resguardo or cfe_emitido) or (getnet_draft_blocked)
    después:  invisible=(state == 'draft' or es_resguardo or cfe_emitido) or (getnet_draft_blocked)

**Arreglo.** Seguir la condición del core —`state in ('draft')`— y sumarle las
dos restricciones de la localización, en vez de volver a enumerar estados.
Enumerarlos es justamente lo que se rompió.

**Regresión que lo fija.** `l10n_uy_einvoice_base/tests/test_boton_borrador_pago.py`,
sobre el arch servido y no sobre el archivo, evaluando en falso los términos que
aportan otros módulos.

- **19.0** — commiteado en `effbe0c`, worktree
  `shared/primateuy/LocalizacionUy-19.0`, rama `19.0_staging`, **sin push**: el
  canal de publicación de ese repo lo maneja Daryl. Suite de
  `l10n_uy_einvoice_base` 12/12 en verde.
- **17.0** — no aplica: en 17.0 esos estados existen y la condición es correcta.

⚠️ La copia de `LocalizacionUy` que carga el `addons_path` de campera es un
**submódulo distinto y divergente** de este worktree (HEAD `0948338` contra
`e009509`, ninguno ancestro del otro). El arreglo está en el worktree; la copia
de campera lo recibe cuando Daryl publique. Para verificarlo se usó una base
aparte, `o19_locuy_boton_test`, copia de `o19_getnet_test`, para no contaminar
la de Getnet con el WIP sin commitear que tiene el worktree en
`models/account_invoice.py`, `models/stock_picking.py`,
`views/account_invoice_view.xml` y `l10n_uy_einvoice_uruware/models/account_move.py`
(ajeno, intacto, no commiteado).

---

---

## DL-5 · `commit_por_consulta` en el motor de polling del núcleo

**Qué es.** `payment.transaction.getnet_run_query_loop` gana un parámetro
opcional, `commit_por_consulta`, que consolida al final de cada vuelta y arranca
a contar el tiempo DESPUÉS de la primera espera. Existe para la «ventana de
gracia» de `terminal_authorize` en el POS Backend: esperar un rato corto por el
pinpad **sin retener nada**.

**Por qué hacía falta tocar el núcleo.** Sin esto, el loop duerme con la
transacción abierta y con el row lock del `getnet_touch` tomado. Una ventana de
unos segundos dentro de un hook que corre en la transacción del POS dejaría un
`idle in transaction` sobre `getnet_pos_terminal` en cada cobro con tarjeta. La
alternativa era escribir una consulta suelta en el módulo del POS Backend, y eso
duplica el motor: dos implementaciones de la misma cosa, una que se arregla y
otra que no.

**Es OPT-IN con default `False`, y hay un test que lo fija**
(`test_el_loop_por_defecto_no_commitea_nada`). El flujo contable, el TPV y el
cron de recuperación no cambian de comportamiento sin pedirlo: un commit
inesperado ahí publicaría media transacción del llamador.

**El piso de espera.** La primera espera es la que pide el concentrador
(`TokenSegundosConsultar` / `Resp_TokenSegundosReConsultar`) y **no se le
descuenta a la ventana**: descontarla sería consultar más seguido de lo que el
concentrador dijo, que el manual pide respetar. Con el default de 5 s, una
ventana de 2-5 s se habría consumido íntegra en ese primer sleep sin llegar a
una sola consulta.

**Los cinco invariantes de la ventana quedan escritos como comentario junto al
parámetro**, en `getnet_run_query_loop`, para que quien la toque sepa contra qué
no puede chocar.

- **19.0** — commiteado en `odoo_pos_getnet_core` (rama `19.0_getnet`). Suites:
  núcleo 58/58, contable 37/37, 95/95 corriendo las dos juntas (la línea de base
  era 91/91: nada cayó).
- **17.0** — **pendiente en 17.0**, programado para la próxima ventana de trabajo
  sobre v17. El motor es el mismo archivo en las dos ramas; mientras no aterrice,
  la rama 17 no tiene la ventana (y tampoco tiene POS Backend, así que no la
  necesita todavía) — pero el parámetro conviene que viaje junto para que los dos
  motores no divergan.

---

## Decidido y escrito: el TPV estándar queda fuera

> **Paridad del TPV estándar de Odoo (`odoo_pos_getnet_pos`) pendiente deliberadamente; retomar si
> un cliente lo requiere.**

Decisión de Daryl, 26-09-2026: no se va a usar en los destinos actuales, así que sale del criterio
de cierre del port. No es un pendiente que se arrastra ni un olvido — **es una decisión escrita**, y
por eso está acá y en el README de la rama y no sólo en un chat.

Consecuencia para este documento: los arreglos que aparezcan en el TPV de v17 **no** generan
entrada de doble aterrizaje hacia v19 mientras el módulo no se porte. Si algún día se retoma, el
punto de partida es la sección 6.6 del `staging_checklist.md` de v17.

---

## Reportado, NO se toca desde acá

Por ahora, nada.
