# Guía de instalación — Fiserv ITD en Odoo 19

**Para quién es:** quien monta el entorno. Asume Odoo 19 andando y acceso al servidor.

## 1 · Qué se instala

| módulo | qué trae |
|---|---|
| `odoo_pos_fiserv_core` | proveedor, terminal (PosID), transacción, bucle de consultas ITD, voucher |
| `odoo_pos_fiserv_backend` | el flujo contable: cobrar y devolver desde **Contabilidad > Pagos** |
| `odoo_pos_getnet_fiserv_flags` | **se instala solo** si también está `odoo_pos_getnet_backend`: convivencia de los dos en el form del pago |

Instalar el backend alcanza (el core viene por `depends`). Requiere **LocalizacionUy**
(`l10n_uy_einvoice_uruware`, que trae `l10n_uy_einvoice_base`).

```bash
odoo-bin -c <conf> -d <base> -i odoo_pos_fiserv_backend --stop-after-init
# actualizar
odoo-bin -c <conf> -d <base> -u odoo_pos_fiserv_core,odoo_pos_fiserv_backend --stop-after-init
```

Reiniciar el servidor después de cada `-u`.

🔴 **Nunca operar Fiserv en un servidor levantado con `--test-enable`**: ahí el módulo no
commitea, y la transacción que se registra antes de hablar con ITD se pierde al primer
rollback. El servidor lo avisa en el log al arrancar.

## 2 · Qué crea el `-i` (verificado en base limpia, 30/09/2026)

| qué | estado al instalar |
|---|---|
| Proveedor **Fiserv ITD** (`odoo_pos_fiserv_core.payment_provider_fiserv`) | **deshabilitado**, URL / SystemId / Branch **vacíos**, sin tokenización, sin métodos web |
| `payment.method` Fiserv ITD + 26 marcas (Anexo 4 POSLink) | inactivo: no se ofrece en ningún checkout |
| `account.payment.method` Fiserv ITD, cobro y devolución | creados |
| Parámetros `fiserv.default_url` / `default_timeout` / `retry_attempts` | creados |
| Menús *Configuración > Terminales Fiserv* (admin. contable) y *Clientes > Transacciones Fiserv* (contabilidad) | creados |
| Diario, líneas de método, terminales | **nada**: aparecen al configurar (paso 3) |

Diferencia con 17.0: allá un `post_init_hook` creaba el proveedor en `test`, un diario `FSVR`
en cada compañía y tocaba `account_account` con `ALTER TABLE`. Eso ya no existe.

**Multi-compañía:** el proveedor se crea en la compañía activa al instalar. Las compañías
**nuevas** reciben su copia apagada automáticamente; las que **ya existían** no — ahí se
duplica a mano desde el proveedor (Acción > Duplicar, cambiar compañía).

## 3 · Qué se configura (una vez, como administrador)

1. **Diario** (recomendado): uno bancario propio, p.ej. *Fiserv ITD* / código `FSVR`.
2. **Contabilidad > Configuración > Proveedores de pago > Fiserv ITD**:
   - URL ITD (testing: `https://testitd.firstdata.com/v2/ITDService`; la de producción la da Fiserv),
   - SystemId (sólo lo ve Ajustes; no sale en logs ni en las transacciones),
   - Branch y ClientAppId si Fiserv los asignó,
   - Estado: **Habilitado** (o *Test*),
   - Diario: el del paso 1. Al guardarlo se crean **dos** líneas de método (cobro y
     devolución) con su cuenta de cobros pendientes.
3. **Terminales**: en la pestaña *Terminales Fiserv (PosID)* del proveedor, una por pinpad.
   Con más de una, marcar *Fiserv: múltiples POS*.

Con el proveedor habilitado, el botón **Pagar** de las facturas abre el pago con la factura
cargada (donde está *Crear transacción*). Con el proveedor apagado la factura queda como la
deja Odoo.

## 4 · Cómo se opera (resumen)

Factura > **Pagar** > diario Fiserv > **Crear transacción** > el pinpad cobra > el form se
refresca solo > **Confirmar**. Devolución: pago *Enviar dinero* con la transacción original
(anulación si el lote sigue abierto, refund si cerró).

Si ITD **no contesta** (timeout, 5xx): la operación queda **pendiente de verificar** y el pago
no deja volver a cobrar. Se resuelve con **Reconsultar en ITD** (si hubo TransactionId) o,
verificado el pinpad, con **Verificada: sin cobro**, que libera el pago.

## 5 · PENDIENTE explícito

- **Smoke contra ITD real: NO corrido.** No hay credenciales ni ambiente de testing ITD en este
  entorno. Todo lo validado fue contra un ITD **simulado** local (forma de las respuestas de la
  spec v3.5 que ya consumía 17.0). Antes del primer cliente: posteo → consulta → confirmar, y
  una devolución, contra `testitd` con un pinpad.
- Recuperación automática (cron) de transacciones en vuelo: no existe; es manual con
  *Reconsultar en ITD*. Ver `README_FISERV_V19.md`.
