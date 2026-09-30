# Guion del video — Fiserv v19 en una copia de Campera

| | |
|---|---|
| Archivo | `2026-09-30_fiserv_v19_campera_copia.mp4` (1,5 MB, **1:59**, 1440×900), en esta carpeta |
| Grabado | 30-09-2026, Playwright `record_video` sobre Chromium headless, una sola toma completa |
| Base | **`o19_campera_fiserv_video`: copia LOCAL de `o19_campera_staging`**, servidor local en `:8076` |
| Árbol | rama `19.0_fiserv`, commit `[ADD]` (árbol limpio, sólo módulos v19). Los módulos Fiserv se cargaron de ese árbol; Getnet, de la copia de Campera (`retail-ecommerce @ 3c89051`) |
| ITD | **SIMULADO** en `127.0.0.1:8099`. No hay ambiente ni credenciales de ITD-Fiserv de testing. Un rótulo rojo fijo en pantalla lo dice en todos los cuadros |

## Por qué una copia y no la base de Campera

`o19_campera_staging` estaba en preparación del go-live (corte de producción 30/09 a la noche,
go-live v19 el 01/10) y con un servidor de otra sesión conectado. Decisión de Daryl (30/09):
grabar hoy sobre una copia local. **El original no se modificó**: sólo se leyó con `pg_dump`.

## Previas, antes de instalar

| | resultado |
|---|---|
| `pg_dump` fresco del original | `~/Odoo/Desarrollos Documentos/Fiserv Campera/respaldo/o19_campera_staging_2026-09-30_pre-video-fiserv.dump` — 489 MB, formato custom, 14:24:33 → 14:25:05 |
| Copia | `createdb` + `pg_restore` → `o19_campera_fiserv_video`, más copia del filestore (108 MB) |
| SMTP | 0 servidores activos (el único, «migration - disable emails», ya estaba apagado) |
| Cola de correo | 4 `outgoing` + 144 `exception` con destinatarios reales → **148 cancelados en la copia** |
| E-factura, las dos compañías | ya en `testing`, pero con `fe_activa = true` y `url_produccion` cargada (UCFE prod / Datalogic prod) → en la copia: `fe_activa = false`, `url_produccion` vacía. Verificado con el código que decide: `get_param('einvoice_mode') = testing`, `get_cfe_base_url_parm() = url_testing` en las dos |
| Crons | servidor con `--max-cron-threads=0` (hay 4 activos; no corrieron) |
| Vencimiento de la base | `2027-03-31`, no hizo falta tocarlo |
| Cotización USD del día | faltaba (la carga el cron diario, que no corrió): se repitió en la copia el último valor, del 27/09 |

## 🔴 Hallazgo para el go-live: dos vistas viejas impiden instalar Fiserv en Campera

El primer `-i odoo_pos_fiserv_backend` **falló**, y no por Fiserv: la base tiene vistas de módulos
vaciados a stub en v19 que siguen activas y usan campos que ya no existen. Cualquier módulo que
extienda el form de factura revienta al validarlo:

| vista | campo inexistente |
|---|---|
| `sales_commission_generic.invoice_account_move_form_view` (id 2035) | `sol_id` |
| `readonly_unit_price_cybrosys.view_move_form` (id 3803) | `price_unit_boolean` |

Es el mismo problema que la KB de POS Backend ya registra para `sales_commission_generic` (bloquea
instalar Uruware; recomendación: **desactivar sus vistas, no desinstalar**). En la **copia** se
desactivaron esas dos vistas y la instalación salió limpia. **En el original siguen activas**: para
instalar Fiserv en Campera hay que resolver eso antes.

## Instalación

`odoo-bin -c <conf> -d o19_campera_fiserv_video -i odoo_pos_fiserv_backend --stop-after-init
--max-cron-threads=0` → exit 0, sin errores. Quedaron instalados `odoo_pos_fiserv_core`,
`odoo_pos_fiserv_backend` y **`odoo_pos_getnet_fiserv_flags` solo** (auto-instalable, porque Getnet
ya estaba). El proveedor *Fiserv ITD* se creó `disabled` en la compañía activa (Raciones Campera);
Campera Almacen, que ya existía, no recibió copia: comportamiento documentado en la guía.

## Ninguna credencial aparece en ningún cuadro

- La configuración del proveedor (URL, SystemId, diario, terminal) se cargó con `odoo shell` **fuera
  de cámara** (00:16–00:18, la pantalla queda en el inicio). El SystemId es un valor de prueba, no
  uno real, y sale como puntos: el campo es `password` y sólo lo ve Ajustes.
- En 00:11–00:16 la URL gris es el *placeholder* del campo, no un valor cargado.
- Las contraseñas de login se escriben con `fill()`, que no las dibuja.

## Timestamps

| tiempo | qué se ve |
|---|---|
| 00:00–00:07 | Sesión con Ajustes (`demo.fiserv.video`), sólo para mostrar lo que dejó la instalación |
| 00:07–00:11 | **Proveedores de pago: «Fiserv ITD» está en la lista** — lo creó el `-i`, nadie a mano |
| 00:11–00:16 | **La ficha como la dejó la instalación: Deshabilitado, URL y SystemId vacíos** |
| 00:16–00:18 | Configuración fuera de cámara |
| 00:18–00:25 | La misma ficha **Habilitada**, URL del ITD simulado, **SystemId enmascarado** |
| 00:25–00:28 | Pestaña Configuración: diario **Fiserv ITD** |
| 00:28–00:31 | Pestaña Terminales: **Caja 1** (PosID P0001) |
| 00:31–00:35 | Entra el **contador** (`contador.fiserv`) — sin Ajustes, no es administrador |
| 00:35–00:52 | Pago nuevo, diario y método Fiserv ITD: **«Crear transacción» y NO hay «Confirmar»** |
| 00:52–00:53 | «Crear transacción»: aviso *Procesando en la terminal Fiserv…* |
| 00:53–01:07 | **El form se refresca solo**: *Transacción Fiserv aprobada*; en el historial ticket 005001, lote 12, autorización |
| 01:07–01:13 | **«Confirmar»**: el pago pasa a **En proceso** |
| 01:13–01:29 | Segundo cobro, ahora con el ITD **sin respuesta (HTTP 502)** |
| 01:29–01:37 | **El aviso, en pantalla**: *No se pudo confirmar si la operación llegó a la terminal Fiserv (ITD respondió HTTP 502…). NO vuelva a cobrar sin verificar el pinpad* |
| 01:37–01:42 | **Pago bloqueado**: aviso rojo, sin «Crear transacción» ni «Confirmar»; transacción **Pendiente** |
| 01:42–01:49 | **«Verificada: sin cobro»** con su confirmación: la transacción se cancela y el pago vuelve a poder cobrarse |
| 01:49–01:58 | **Clientes > Transacciones Fiserv** (menú del contador): la aprobada (*Confirmado*) y la verificada (*Cancelada*) |

## Qué prueba y qué NO prueba

**Prueba**, en una copia real de Campera: que la instalación desde el árbol limpio crea todo sola y
convive con el Getnet de Campera; que un contador sin Ajustes opera el flujo completo; que el form se
refresca solo; que una falta de respuesta de ITD **no** se toma como rechazo y bloquea el recobro.

**No prueba** el contrato con ITD real: todas las respuestas vinieron del simulador (forma de la
spec ITD v3.5 que ya consumía 17.0). Sigue **PENDIENTE** el smoke contra ITD de testing con un pinpad.

## Baja de los artefactos de prueba

Todo vive en la copia; el original no tiene nada que dar de baja.

```bash
# la copia, su instantánea y sus filestores
dropdb o19_campera_fiserv_video
dropdb o19_campera_fiserv_video_snap
rm -rf "$HOME/Library/Application Support/Odoo/filestore/o19_campera_fiserv_video"
rm -rf "$HOME/Library/Application Support/Odoo/filestore/o19_campera_fiserv_video_snap"
# el dump del original: contiene datos de clientes; borrarlo cuando ya no haga falta
rm "$HOME/Odoo/Desarrollos Documentos/Fiserv Campera/respaldo/o19_campera_staging_2026-09-30_pre-video-fiserv.dump"
```

Si se decidiera conservar la copia y limpiar sólo lo de la prueba:

```python
# odoo-bin shell -c <conf> -d o19_campera_fiserv_video --no-http
assert env.cr.dbname == 'o19_campera_fiserv_video'
env['res.users'].search([('login', 'in', ['demo.fiserv.video', 'contador.fiserv'])]).unlink()
env['account.payment'].search([('fiserv_charge_on_pos', '=', True)]).unlink()   # sólo borradores/cancelables
env['payment.transaction'].search([('provider_id.code', '=', 'fiserv')]).unlink()
env['fiserv.pos.terminal'].search([('pos_id', '=', 'P0001')]).unlink()
env['account.journal'].search([('code', '=', 'FSVR')]).unlink()
env['res.partner'].search([('name', '=', 'Cliente Demo Fiserv')]).unlink()
prov = env.ref('odoo_pos_fiserv_core.payment_provider_fiserv')   # lo creó la instalación: se deja como nació
prov.write({'state': 'disabled', 'fiserv_url_webservice': False, 'fiserv_system_id': False})
env.cr.commit()
```

(El pago confirmado de 01:07 queda *En proceso* con asiento: si se conserva la copia, se revierte
desde la contabilidad antes de borrar nada.)
