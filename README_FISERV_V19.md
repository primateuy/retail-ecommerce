# Fiserv ITD en Odoo 19 — estado de la rama

Rama `19.0_fiserv`, creada desde `1184177` (lo publicado de `origin/19.0_getnet`). Port de la
integración Fiserv ITD desde `17.0_getnet @ 2371fb1` (los módulos Fiserv son idénticos en los dos
commits).

Estructura: `1184177` → `[IMP] limpieza: solo módulos v19 en la rama` → `[ADD] odoo_pos_fiserv`.

## La rama tiene sólo módulos v19

La limpieza eliminó todo lo heredado de 17.0 (46 carpetas: los módulos de clientes, el Fiserv v17
completo con TPV, meta-módulo y puentes, el TPV de Getnet v17 y el puente de flags v17). Quedan
`odoo_pos_getnet_core` y `odoo_pos_getnet_backend` (v19, de `1184177`) y los tres de esta entrega.
Verificado: el cierre transitivo de dependencias de los cinco (36 módulos, resuelto contra
community/enterprise 19.0 y LocalizacionUy-19.0) no toca nada eliminado.

> **Pendiente de Daryl:** unificar este criterio («sólo v19 en la rama») con `19.0_getnet`, que
> todavía arrastra el árbol de 17.0.

## Qué entra en esta entrega

| módulo | qué es |
|---|---|
| `odoo_pos_fiserv_core` | proveedor, terminal (PosID), transacción, bucle de consultas ITD, voucher |
| `odoo_pos_fiserv_backend` | cobrar y devolver desde **Contabilidad > Pagos** |
| `odoo_pos_getnet_fiserv_flags` | puente auto-instalable: Getnet y Fiserv en la misma base |

## Suites

| base | suites | resultado |
|---|---|---|
| `o19_fiserv_test` (plan uy, uruware, sólo Fiserv) | core + backend | **82 / 82** (43 + 39) |
| `o19_fiserv_getnet_test` (los dos adquirentes + puente) | Fiserv core + backend + puente + Getnet core + backend | **197 / 197** (43 + 39 + 13 + 61 + 41) |

```bash
odoo-bin -c <conf> -d o19_fiserv_test -u odoo_pos_fiserv_core,odoo_pos_fiserv_backend \
  --test-enable --test-tags /odoo_pos_fiserv_core,/odoo_pos_fiserv_backend \
  --stop-after-init --max-cron-threads=0
```

Fiserv no tenía **ningún** test en 17.0: la suite es nueva entera.

## Documentación

| archivo | para quién |
|---|---|
| `odoo_pos_fiserv_core/docs/guia_usuario_fiserv_backend.md` (+ `.pdf`) | **quien configura y usa** la integración. Sin código |
| `odoo_pos_fiserv_core/docs/guia_instalacion_v19.md` (+ `.pdf`) | quien monta el entorno |
| `odoo_pos_fiserv_core/docs/evidencia/` (mp4 + `guion.md`) | video: instalación y flujo como contador en una **copia** de Campera, ITD simulado |
| `doc/dual-landing-fiserv.md` | defectos que valen para 17.0 y 19.0, con su estado |

## Validado además de las suites

- **Instalación en base limpia** (`o19_fiserv_limpia`): lo que crea el `-i` está en
  `odoo_pos_fiserv_core/docs/guia_instalacion_v19.md` §2.
- **Pantallas operadas en el navegador como contador sin Ajustes** (`o19_fiserv_e2e`, los dos
  adquirentes instalados, ITD **simulado**): factura → Pagar → Crear transacción → el form se
  refresca solo → Confirmar → factura pagada; ITD caído (502) → aviso «NO vuelva a cobrar»,
  pago bloqueado, «Verificada: sin cobro» lo libera; listado de transacciones; pago Getnet en
  la misma base con su botón y sin el de Fiserv. Cero errores de consola.
- **Video en una copia local de Campera** (`o19_campera_fiserv_video`, 30/09): instalación desde el
  árbol limpio con todo creado solo y el puente auto-instalado, configuración fuera de cámara,
  cobro aprobado y confirmado, y el error honesto de ITD sin respuesta, operado por un contador sin
  Ajustes. ITD simulado, rotulado en pantalla.

## PENDIENTE explícito

- **Smoke contra ITD real**: no hay credenciales ni ambiente de testing ITD-Fiserv. Queda
  pendiente antes del primer cliente (guía de instalación §5).
- **Instalar en la base de Campera real**: en `o19_campera_staging` hay dos vistas de módulos
  vaciados a stub (`sales_commission_generic`, campo `sol_id`; `readonly_unit_price_cybrosys`,
  campo `price_unit_boolean`) que rompen el form de factura: con ellas activas **Fiserv no
  instala** (ni ningún módulo que extienda ese form). En la copia del video se desactivaron; en el
  original siguen. Detalle en `odoo_pos_fiserv_core/docs/evidencia/guion.md`.
- **Recuperación automática** de operaciones en vuelo (el equivalente del cron de Getnet): no
  existe. Es manual con *Reconsultar en ITD*. No se agregó un cron porque requeriría decidir qué
  significa cada respuesta de ITD para una consulta vieja (p.ej. `110 No existe transacción`) y
  eso es contrato ITD que no está verificado; la reconsulta manual sólo cambia el estado ante un
  resultado final (RC 0).
- **Lock de terminal** entre flujos (Getnet lo tiene): Fiserv no lo tuvo nunca. Sin cambio.

## Lo que NO está, y por qué

> **TPV estándar de Fiserv (`odoo_pos_fiserv_pos`), `odoo_pos_fiserv_pos_payment`, el meta-módulo
> `odoo_pos_fiserv` y el puente `odoo_pos_fiserv_backend_internal_transfer_payment_fix` quedan
> aparcados** — mismo criterio que el TPV de Getnet: no se usan en los destinos actuales;
> retomar si un cliente lo requiere.

No están en esta rama (los eliminó la limpieza); el punto de partida es `17.0_getnet @ 2371fb1`.

Al retomar el TPV hay que saber:
- su JS importa del namespace del meta-módulo viejo (`@odoo_pos_fiserv/app/payment_fiserv`);
- la capa ITD del core ahora es privada (`_fiserv_itd_query`, `_fiserv_timestamp`, …) y la
  persistencia es `_fiserv_persist_query_result`: los nombres públicos de 17.0 que usaba el TPV
  (`processFinancialPurchaseQuery`, `update_fiserv_transaction`,
  `create_fiserv_transaction_with_complete_data`, `fiserv_persist_after_query_generic`) ya no
  existen, a propósito (eran alcanzables por RPC);
- no hay migración de datos desde 17.0 (hooks y `migrations/` de la partición 17.0.2 no
  viajaron); una base 17.0 con Fiserv se migra con la plataforma de upgrade y hay que revisar el
  proveedor y el diario `FSVR` a mano.

## Cambios de comportamiento respecto de 17.0 (decididos acá)

| | 17.0 | 19.0 |
|---|---|---|
| proveedor | lo crea un hook, en `test`, con tokenización | en data, `disabled`, sin credenciales |
| diario | hook crea `FSVR` en todas las compañías | se elige al habilitar el proveedor |
| sin respuesta de ITD | `error` definitivo (o traceback) | `pending` + marca de verificación; bloquea volver a cobrar |
| transacción | se crea al final del polling | se crea y consolida ANTES del POST |
| bloqueo de Confirmar | todo el diario con línea Fiserv | sólo pagos con método Fiserv |
| `write()` / `action_post` | en `sudo` para borradores (salteaba reglas multicompañía) | sin elevación |
| botón Pagar de la factura | reemplazado apenas se instala | sólo con proveedor Fiserv habilitado |
| wizard «Registrar pago» con método Fiserv | confirmaba y fallaba el guard | avisa y no deja seguir |
| capa ITD / persistencia | métodos públicos (RPC) | privados; guards de grupo en los botones |

Detalle y estado en 17.0: `doc/dual-landing-fiserv.md`.

## Lecciones que quedan

1. **Una versión `17.0.x` en una rama 19 no es instalable**: Odoo lo impide solo. Pero una versión
   SIN serie (`1.0.7`) Odoo la completa como `19.0.1.0.7` y la da por instalable aunque el código
   sea de 17: el número de versión no prueba que un módulo esté portado.
2. **Un pago recién creado y guardado tiene `props.resId = false`** en el cliente web de 19.0:
   quien reaccione al bus tiene que mirar `router.current.resId`. Sin eso el refresco del form
   «no anda» sólo en el caso más común (pago nuevo).
3. **Al habilitar un proveedor, Odoo le asigna el primer diario bancario**: cualquier regla «si el
   diario tiene línea X, bloquear» se vuelve una regla sobre el banco principal.
4. **Un rechazo es una respuesta; un transporte caído no**: vale para el POST inicial, para cada
   consulta del bucle y para el confirm. El que no contestó no dijo que no.
5. **La transacción se registra antes de hablar con el adquirente**, no después: el único rastro de
   un cobro en vuelo no puede vivir en la memoria de un hilo.
