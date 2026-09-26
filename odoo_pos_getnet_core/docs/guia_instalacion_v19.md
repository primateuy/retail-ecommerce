# Guía de instalación y configuración — Getnet/TransAct en Odoo 19

**Para quién es:** para quien monta el entorno. Asume Odoo 19 andando y acceso al servidor.
Si lo que buscás es *cómo se usa*, la otra guía es `guia_usuario_getnet_backend.md`.

---

## 1 · Qué se instala, y en qué orden

| # | módulo | qué trae |
|---|---|---|
| 1 | `odoo_pos_getnet_core` | proveedor, terminal, transacción, motor de polling, cliente SOAP, cron de recuperación, cierre de lote |
| 2 | `odoo_pos_getnet_backend` | el flujo contable: cobrar y devolver desde **Contabilidad > Pagos** |

El orden lo resuelve Odoo por el `depends`; instalar el segundo alcanza. **No** se instala
`odoo_pos_getnet_pos` (TPV estándar): quedó aparcado por decisión de Daryl y no forma parte de esta
entrega.

### Dependencias que tienen que estar antes

- `account`, `account_payment`, `payment`, `bus` — del core de Odoo.
- **`l10n_uy_einvoice_base`** — la exige el módulo contable: de ahí salen `numero_cfe()` y
  `cfe_type` de la factura origen.
- **`l10n_uy_einvoice_uruware`** si el cliente factura con Uruware. 🔴 **Importa para Getnet**:
  uruware **sobrescribe** `numero_cfe()` y levanta error si la factura no tiene el CFE firmado. El
  módulo lo traduce a un mensaje que nombra la factura, pero hay que saber que el camino real es el
  de uruware y no el de base.

```bash
# instalar
odoo-bin -c <conf> -d <base> -i odoo_pos_getnet_backend --stop-after-init
# actualizar
odoo-bin -c <conf> -d <base> -u odoo_pos_getnet_core,odoo_pos_getnet_backend --stop-after-init
```

**Reiniciar el servidor después de cada `-u`.** Los cambios en Python no se recargan solos; los de
vistas y datos sí entran con el `-u`. Un `-u` sin reinicio deja el código viejo corriendo contra el
esquema nuevo, y eso se ve como un error que no tiene sentido.

## 2 · Compuerta de e-factura — PASO OBLIGATORIO del montaje

**Antes de que la base pueda emitir nada**, verificar que todo endpoint de e-factura apunte a
testing. En una base copiada de producción esto **no** viene así.

```sql
select id, name, einvoice_mode, fe_activa, url_produccion, url_testing
  from res_company;
```

Lo que tiene que dar en un entorno de pruebas:

- `einvoice_mode = 'testing'` — **explícito**, no vacío. El código cae a `testing` cuando está
  vacío, pero un default no es una decisión: dejarlo escrito es lo que evita que alguien lo mueva
  sin darse cuenta.
- `fe_activa = false` — con esto el posteo de facturas no firma nada.
- `url_produccion` **vacía**. Si no hay a dónde emitir, no se emite.

Y comprobarlo con el código que decide, no leyendo la ficha:

```python
m = env['account.move'].new({'move_type': 'out_invoice'})
print(m.get_param(param='einvoice_mode'), m.get_cfe_base_url_parm())
# tiene que decir: testing url_testing
```

También: los crons de e-factura (`cron_check_cfe_state`, `cron_download_received_documents`,
`service_send_invoices_email_automatically_cron`) **desactivados**, y **cero `ir_mail_server`
activos** — una base copiada arrastra la cola de correo con destinatarios reales.

## 3 · El proveedor de pago

**Contabilidad > Configuración > Proveedores de pago**, o el menú de Getnet.

| campo | qué va | de dónde sale |
|---|---|---|
| Código | `getnet` | lo pone el módulo |
| Estado | **Test** en integración, **Habilitado** en producción | 🔴 un proveedor nace *Deshabilitado* y así el medio no cobra |
| URL del webservice | la del concentrador | integración: `https://testing-concentrador.getnet.com.uy` |
| EmpCod | código de comercio | **lo da New Age Data** |
| EmpHASH | la credencial | **lo da New Age Data** |
| Modo emulación | sólo para probar sin pinpad | dejarlo en falso |

### Las credenciales NO se escriben en el código ni en un fixture

`EmpHASH` es **una password**. Reglas:

- **Distinta en integración y en producción.** No se reusa una en la otra: el mismo módulo
  apuntando a la URL equivocada con la credencial equivocada es un cobro real por error.
- Se carga **por configuración**, en la ficha del proveedor, o desde el entorno al montar. Nunca
  en un commit, nunca en un test, nunca en un log. En los tests del módulo el hash es un valor
  inventado y está comentado que lo es.
- El campo es `groups='base.group_system'`: un usuario de Contabilidad **no** lo lee, y eso es
  correcto. El módulo lo lee por sudo cuando le habla al concentrador.

## 4 · Diario y método de pago

- Un **diario de banco** propio para Getnet. 🔴 **No uno de caja**: el adquirente acredita días
  después, neto de comisión y en un depósito que junta muchas ventas. Un diario de caja hace que
  el arqueo cuente plata que no está.
- En ese diario, una **línea de método de pago entrante** con el proveedor Getnet asignado. Es lo
  que hace que el pago se reconozca como Getnet: el módulo resuelve el proveedor **sólo** desde la
  línea de método de pago.
- Para devoluciones, la línea **saliente** equivalente.
- 🔴 `payment.provider.journal_id` es compute+inverse y necesita un `account.payment.method` con el
  mismo `code`. Si falta, el write parece exitoso y no queda nada.

## 5 · La terminal

**Menú de Getnet > Terminales.** Una por pinpad:

| campo | qué va |
|---|---|
| Nombre | algo que identifique la caja |
| TermCod | el código del pinpad, **lo da New Age Data** |
| Proveedor | el de arriba |

El lock de la terminal es **entre flujos**: si el mismo pinpad lo usan el cobro contable y otro
flujo, se excluyen solos. Con más de una terminal el proveedor se marca como múltiple y el pago
pide elegir.

**Una sola terminal de integración (`T00001`) para todos los proyectos.** Antes de una tanda de
pruebas, confirmar que nadie más la esté usando y que `lock_origin` esté vacío.

## 6 · La tasa del día — el prerrequisito que no parece uno

🔴 **Sin la tasa USD del día, Confirmar falla en CUALQUIER pago, aunque sea en pesos**, con
*«No se encontró tipo de cambio para la fecha … y moneda USD»*.

El culpable es `aml_secondary_currency`: exige tasa de la **fecha exacta** del asiento, no la
última conocida. En v17 esto dejó un cobro aprobado en el pinpad **sin poder confirmarse**, y con
él la conciliación con la factura origen sin ejecutar. No es un problema de Getnet y por eso
sorprende: el cobro sale bien y lo que falla es el paso siguiente.

En un entorno de pruebas se copia la última conocida antes de cada sesión:

```bash
odoo-bin shell -c <conf> -d <base> --no-http < getnet_tasa_hoy.py
```

En producción la carga el cron del BCU. **Verificar que ese cron esté activo** es parte del
montaje, no un detalle.

## 7 · Verificación del montaje

1. `select name, state from ir_module_module where name like 'odoo_pos_getnet%';` → los dos
   `installed`.
2. Abrir **un pago nuevo con el diario Getnet** y ver que aparezcan «Cobrar en terminal Getnet»,
   «Facturas origen (Getnet)» y el botón «Crear transacción Getnet».
3. Hacerlo **con un usuario de Contabilidad sin Ajustes**. Que el módulo instale no significa que
   la pantalla abra: en v19 este form reventaba con `AccessError` sobre `payment.provider` para
   exactamente ese usuario.
4. Un posteo contra el concentrador de integración y su cancelación, para confirmar que la URL y
   las credenciales están bien. La secuencia está en `smoke-v19.md`.
5. La tasa del día cargada.

## 8 · Lo que no está

- **TPV estándar de Odoo:** aparcado deliberadamente. Retomar si un cliente lo requiere.
- **Puente con Fiserv** (`odoo_pos_getnet_fiserv_flags`): fuera de esta entrega.
- **Botón en la factura:** el camino soportado es Contabilidad > Pagos. El wizard «Registrar pago»
  de la factura no sirve y no es un defecto (postea el pago al crearlo y el guard lo rechaza).
- **Refresco automático de la pantalla del pago:** hay que refrescar a mano. Backlog conocido.
