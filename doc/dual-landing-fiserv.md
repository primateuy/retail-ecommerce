# Doble aterrizaje Fiserv — arreglos que valen para 17.0 y para 19.0

Mismo formato que `dual-landing.md` (Getnet): qué se rompe, el arreglo, y el estado en cada
rama. Nada se cierra por «ya está en 19»: la línea de 17.0 tiene que decir *commiteado* con su
hash. La rama 17.0 de referencia es `17.0_getnet` (`2371fb1`), donde viven los módulos Fiserv.

## Estado global

| | qué | 19.0 (`19.0_fiserv`) | 17.0 |
|---|---|---|---|
| DLF-1 | proveedor creado por hook, en `test`, con tokenización | arreglado | **pendiente en 17.0** |
| DLF-2 | sin respuesta de ITD se persiste como rechazo | arreglado | **pendiente en 17.0** |
| DLF-3 | la transacción recién existe al final del polling | arreglado | **pendiente en 17.0** |
| DLF-4 | capa ITD y persistencia alcanzables por RPC | arreglado | **pendiente en 17.0** |
| DLF-5 | `write()` / `action_post` en sudo saltean reglas por registro | arreglado | **pendiente en 17.0** (al descongelar) |
| DLF-6 | el contador no puede abrir el form del pago | arreglado | **pendiente en 17.0** |
| DLF-7 | el voucher revienta sin el módulo POS | arreglado | **pendiente en 17.0** |
| DLF-8 | el bloqueo de «Restablecer a borrador» lo pisa einvoice | arreglado | **pendiente en 17.0** |
| DLF-9 | el check «Cobrar en terminal» queda pegado al cambiar de método | arreglado | **pendiente en 17.0** (mitigado por el puente) |
| DLF-10 | el wizard «Registrar pago» confirma un cobro Fiserv sin pinpad | arreglado | **pendiente en 17.0** |
| DLF-11 | «Registrar pago» de la factura reemplazado aunque Fiserv no se use | arreglado | **pendiente en 17.0** (al descongelar) |
| DLF-12 | el contador no llega por menú a «Transacciones Fiserv» | arreglado | **pendiente en 17.0** |
| DLF-13 | con una sola terminal, la pestaña de terminales del proveedor no aparece | arreglado | **pendiente en 17.0** |
| DLF-14 | la devolución precargada se guarda en $0 (campos readonly sin `force_save`) | arreglado | **pendiente en 17.0** |

«Pendiente en 17.0»: **v17 está congelado por decisión de Daryl** (30/09/2026). Todos los DLF
aterrizan como commits locales en `17.0_getnet` cuando se descongele; hasta entonces la fila dice
pendiente.

---

## DLF-1 · El proveedor lo crea un hook, en `test` y con tokenización

Es el DL-8 de Getnet, un poco peor. `post_init_hook` crea el proveedor sólo en `env.company`,
en estado `test` (activo, sin credenciales: parece disponible y no cobra) y con
`allow_tokenization=True`. Además crea un diario `FSVR` en cada compañía y hace
`ALTER TABLE account_account` si `create_asset` no tiene default.
**Arreglo 19.0:** `data/payment_provider_data.xml` con el patrón `payment_*` (`noupdate`,
`module_id`, `disabled`, credenciales vacías); sin hook. Tests: existe por `env.ref`, nace
apagado, compañía nueva recibe copia apagada.

## DLF-2 · Sin respuesta de ITD se persiste como rechazo

Tres lugares: (a) un 5xx del POST inicial se guarda como transacción `error` y se muestra «ITD
rechazó el inicio»; (b) un timeout o error de conexión no se captura y sale como traceback;
(c) **un solo 502 o timeout durante el polling corta el bucle con 999 y la transacción queda en
`error`**, aunque el pinpad apruebe después.
**Arreglo 19.0:** `fiserv_itd_http_post` nunca levanta por transporte y devuelve el código
sintético `TRANSPORTE` (timeout, conexión, 5xx, 408/429, 2xx no JSON); un 4xx sigue siendo
rechazo. El bucle reintenta ante transporte (también en el confirm) y el tope deja `pending`.
`TRANSPORTE` → `pending` + marca de verificación, y el pago no deja volver a cobrar.

## DLF-3 · La transacción recién existe al final del polling

`create_fiserv_transaction_with_complete_data` corre después del bucle. Si Odoo se reinicia a
mitad (deploy, caída), el cobro en vuelo no deja **ningún** registro y el pago queda con
`fiserv_async_terminal_pending=True` para siempre.
**Arreglo 19.0:** la transacción se crea y se consolida antes del POST, con el TransactionId
apenas llega; *Reconsultar en ITD* resuelve una que quedó sin resultado.

## DLF-4 · Capa ITD y persistencia alcanzables por RPC

`processFinancialPurchaseQuery`, `fiserv_process_financial_purchase_contable`,
`update_fiserv_transaction`, `fiserv_persist_after_query_generic` (este en sudo) eran públicos:
cualquier usuario interno podía disparar un POST a ITD o escribir un resultado «aprobado».
**Arreglo 19.0:** todo privado (`_fiserv_*`); guards de grupo en los botones
(`action_fiserv_create_transaction`, `action_fiserv_requery`: facturación;
`fiserv_action_conciliada`: contabilidad). ACL de lectura de `payment.transaction` para
`account.group_account_user`; terminales de sólo lectura para usuarios internos.

## DLF-5 · `write()` y `action_post` en sudo

`write()` elevaba a sudo cualquier borrador si el usuario tenía ACL de escritura: saltea
reglas por registro, **incluidas las multicompañía** (test: un contador de una compañía editaba
borradores de otra). `action_post` también corría en sudo.
**Arreglo 19.0:** sin elevación. **17.0: pendiente, al descongelar.** Ojo al aterrizarlo: el
docstring dice que se agregó por reglas por diario de algún cliente; sacarlo allá puede devolverle
un «Access Denied». Revisar esas reglas en el mismo paso.

## DLF-6 · El contador no puede abrir el form del pago

Los computes leen `payment_method_line_id.payment_provider_id.code` sin sudo;
`payment.provider` es de `base.group_system`. Es el DL-1 de Getnet.
**Arreglo 19.0:** sudo acotado a leer `code`; el dominio de la transacción original ya no
atraviesa el proveedor. Tests como contador sin Ajustes.

## DLF-7 · El voucher revienta sin el módulo POS

`tx.pos_order_id` sólo existe con `odoo_pos_fiserv_pos`: imprimir el voucher desde el flujo
contable fallaba. **Arreglo 19.0:** se lee sólo si el campo existe; test que renderiza.

## DLF-8 · El bloqueo de «Restablecer a borrador» lo pisa einvoice

La vista Fiserv (priority 15) reemplaza el `invisible` entero; `l10n_uy_einvoice_base`
(priority 16) lo reemplaza después y el término Fiserv se pierde.
**Arreglo 19.0:** todos los bloqueos en modo aditivo (`separator=" or " add=`), priority por
defecto; test sobre el arch servido. En 19.0 además el lado einvoice necesitó `effbe0c`
(LocalizacionUy, DL-4 de Getnet).

## DLF-9 · El check queda pegado

El onchange marca «Cobrar en terminal Fiserv» al elegir un diario Fiserv y no lo desmarca al
salir. **Arreglo 19.0:** lo desmarca; y el bloqueo de Confirmar lo decide la línea del pago.

## DLF-10 · El wizard confirma un cobro Fiserv sin pinpad

El wizard ofrecía «Cobrar en terminal» y el pago terminaba rechazado por el guard con un mensaje
que no explicaba el camino. **Arreglo 19.0:** el wizard avisa y no deja seguir.

## DLF-11 · «Registrar pago» reemplazado aunque Fiserv no se use

Instalar el backend reemplaza el botón de todas las facturas. **Arreglo 19.0:** sólo si hay un
proveedor Fiserv habilitado en la compañía. **17.0: pendiente, al descongelar** (cambio visible
para usuarios que hoy lo usan así: avisar al aterrizarlo).

## DLF-12 · El contador no llega por menú a «Transacciones Fiserv»

El menú colgaba de *Configuración > Pagos en línea*, que es sólo del administrador contable: la
lista que el contador tiene que revisar existía y no tenía cómo llegar. **Arreglo 19.0:** en
*Clientes*, junto a Pagos; test que recorre la cadena de menús como contador.

## DLF-13 · La pestaña de terminales sólo con «múltiples POS»

La pestaña *Terminales Fiserv (PosID)* del proveedor estaba oculta salvo con *múltiples POS*, pero
una sola terminal también hay que cargarla: en la configuración más común el administrador no la
encontraba. **Arreglo 19.0:** visible siempre para Fiserv.

## DLF-14 · La devolución precargada se guarda en $0

Con la transacción original elegida, importe / cliente / moneda quedan readonly, y el cliente web
no guarda un campo readonly: lo que precargaba el onchange se perdía al guardar (importe $0,
«Cobrar en terminal» desmarcado, botones de uruware visibles). El importe correcto se fijaba recién
al pulsar «Crear transacción». **Arreglo 19.0:** `force_save`; test sobre el arch servido.
Además «Reconsultar en ITD» se ofrece sólo si hay TransactionId (sin él, el botón sólo daba error).

---

## Sólo 19.0 (no aplica a 17.0)

- `account.payment` sin estado `posted`: la conciliación con las facturas origen filtraba
  `state == 'posted'` y no corría nunca. Ahora `('in_process', 'paid')` y no aborta la
  confirmación si no se puede conciliar.
- `is_internal_transfer` y `show_reset_to_draft_button` ya no existen.
- `action_reject`: puerta nueva para revertir sin anulación; bloqueada con transacción aprobada.
- Al habilitar un proveedor Odoo le asigna el primer diario bancario: el bloqueo por «diario
  integrado» de 17.0 dejaba sin confirmar todos los pagos manuales del banco principal.
- Líneas de método con cuenta de cobros pendientes (sin ella el pago confirma sin asiento).
- Refresco del form: `props.resId` es `false` en un pago recién guardado.
- `odoo.registry` no existe: el hilo usa `odoo.modules.registry.Registry` (test de la plomería).
