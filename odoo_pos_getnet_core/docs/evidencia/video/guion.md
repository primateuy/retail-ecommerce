# Guion del video — Getnet v19 en Campera, Parte A

| | |
|---|---|
| Archivo | `2026-09-27_getnet_v19_campera_parteA.mp4` (1,4 MB, **2:09**, 1440×900). **No está en el repo**: la rama publicada no lleva evidencia binaria. Queda en *Desarrollos Documentos/Getnet Campera/evidencia/* |
| Grabado | 27-09-2026, con Playwright `record_video` sobre Chromium headless |
| Base | `o19_campera_staging`, servidor local en `:8079` |
| Árbol | checkout local en `1184177` (el `[FIX]` **sin pushear**), no `origin` |
| Semáforo del concentrador | **HTTP 502/504 — caído** durante toda la grabación |

Esta es la **segunda toma**. La primera se cortó porque la base estaba vencida (ver abajo) y la
acción de cobro no llegaba al concentrador. Esa toma se reemplazó; el relato quedó en un archivo.

## El vencimiento de la base, extendido

`o19_campera_staging` estaba **vencida**, y Odoo bloquea las escrituras de los usuarios no
administradores en una base vencida.

| | |
|---|---|
| `database.expiration_date` **antes** | `2026-08-30 18:07:36` |
| `database.expiration_date` **ahora** | `2027-03-31 00:00:00` |
| `database.expiration_reason` | `trial` — vencimiento de prueba de una base **local** de staging |
| Autorizado por | Daryl, 27-09-2026 |

Se extendió **sólo ese parámetro**; nada más de la configuración de la base se tocó. Verificado
después: `contador.getnet` —sin Ajustes, no admin— **vuelve a poder escribir**.

## Ninguna credencial aparece en ningún cuadro

El `EmpHash` es `password="True"` **y** `groups="base.group_system"`: sale como puntos para quien
tiene Ajustes y no existe para el contador. Además se carga por shell, fuera de cámara: no se
teclea en pantalla en ningún momento. Las contraseñas de login se escriben con `fill()`, que no las
dibuja.

## Timestamps

| tiempo | qué se ve |
|---|---|
| **00:08** | Sesión con Ajustes, sólo para verificar lo que dejó la instalación |
| **00:19** | **Proveedores de pago: «Getnet (TransAct)» está en la lista.** Nadie lo creó a mano — lo creó el `-i` |
| **00:32** | **La ficha como la dejó la instalación: «Deshabilitado», URL / EmpCod / EmpHash vacíos** |
| **00:39** | Se cargan las credenciales de testing por configuración, **fuera de cámara** |
| **00:49** | La misma ficha en **«Modo de prueba»**, con el **EmpHash enmascarado** |
| **01:03** | La terminal **T00001**, el pinpad de integración |
| **01:17** | Se cierra sesión y entra el **contador** — sin Ajustes, no es admin |
| **01:30** | **El form del pago ABRE para el contador** —era el defecto de v19 que lo impedía— con «Cobrar en terminal Getnet», «Facturas origen (Getnet)», diario *Tarjetas a cobrar Getnet* y el botón **«Crear transacción Getnet»**. Y **no hay «Confirmar»**: la terminal no aprobó nada |
| **01:38** | Se pulsa «Crear transacción Getnet» — **ahora sí sale a buscar al concentrador** |
| **01:55** | **El resultado en el form: «Transacción Getnet: GETNET-77220-…» y «Estado transacción Getnet: Pendiente»**, con el pago todavía en **Borrador** |
| **02:02** | Fin |

## El mensaje que devolvió el concentrador

El diálogo de error se capturó **textual** durante la grabación:

> **Operación no válida** — No se pudo confirmar si el cobro llegó a la terminal Getnet (999):
> HTTP 504 del concentrador. NO vuelvas a cobrar sin verificar: la transacción quedó registrada
> como sin confirmar.

⚠️ **Ese diálogo NO quedó en ningún cuadro del video**: se cierra antes de que el video lo capture.
Lo que sí queda en pantalla —y es mejor evidencia, porque es lo que ve quien entra después— es el
form con la transacción en **Pendiente**.

**Es exactamente el arreglo del `[FIX]` funcionando en una base real:** un fallo de transporte
(`rc 999`) deja la transacción **`pending`**, no `error`. Antes se cerraba como rechazo definitivo
y un cobro que quizá pasó por el pinpad quedaba dado por no ocurrido.

Verificado también fuera del video, en la misma base y con el mismo usuario:

```
tardó: 10,7 s
UserError: No se pudo confirmar si el cobro llegó a la terminal Getnet (999): HTTP 504 …
transacción: GETNET-77220-20260927181446 · estado pending · token ''
terminal: LIBRE · pago: draft, 2500,00
```

**Dato para la sesión con pinpad:** los 10,7 s **no** los arregla el connect-timeout de 4 s que
trae el `[FIX]`. La conexión TCP **sí** se establece —el gateway del concentrador está en pie— y lo
que tarda es la respuesta 504. El connect corto sirve cuando el host no responde; acá responde
mal. Medirlo con la terminal viva es uno de los puntos del checklist.

## Parte B — pendiente

Cobro real de punta a punta. Arranca **al primer verde del semáforo**
(`../../smoke_v19.md`). Escenarios en
`odoo_pos_getnet_pos_backend/docs/checklist_pinpad_p3.md`.

## Baja de los artefactos de prueba — al cerrar la Parte B

Se quedan hasta entonces: son las fixtures del tramo pendiente. Cuando la Parte B esté grabada:

```python
# odoo-bin shell -c <conf> -d o19_campera_staging --no-http
env['res.users'].search([('login', 'in', ['contador.getnet', 'demo.getnet.video'])]).unlink()
env['account.payment'].search([('getnet_charge_on_pos', '=', True)]).unlink()
env['payment.transaction'].search([('provider_id.code', '=', 'getnet')]).unlink()
env['getnet.pos.terminal'].search([('term_cod', '=', 'T00001')]).unlink()
env['account.payment.method.line'].search(
    [('journal_id.code', '=', 'GETNT')]).unlink()
env['account.journal'].search([('code', '=', 'GETNT')]).unlink()
env['account.account'].search([('code', '=', 'GETNPEND')]).unlink()
env['res.partner'].search([('name', '=', 'Cliente Demo Getnet')]).unlink()
# El proveedor NO se borra: lo creó la instalación. Se deja como nació:
prov = env.ref('odoo_pos_getnet_core.payment_provider_getnet')
prov.write({'state': 'disabled', 'getnet_url_webservice': False,
            'getnet_emp_cod': False, 'getnet_emp_hash': False})
env.cr.commit()
```

**El vencimiento de la base NO se revierte**: extenderlo fue una decisión, no un efecto colateral
de la prueba.
