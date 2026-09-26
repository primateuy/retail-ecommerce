# Getnet / TransAct en Odoo 19 — estado de la rama

Rama `19.0_getnet`. Port de la integración Getnet/TransAct desde `17.0_getnet @ 2371fb1`.

## Qué entra en esta entrega

| módulo | qué es |
|---|---|
| `odoo_pos_getnet_core` | proveedor, terminal con lock entre flujos, transacción, motor de polling, cliente SOAP, cron de recuperación, cierre de lote |
| `odoo_pos_getnet_backend` | el flujo contable: cobrar y devolver desde **Contabilidad > Pagos** |

## Suites

Medido en `o19_getnet_test` (v19, con `l10n_uy_einvoice_base` y `l10n_uy_einvoice_uruware`
instalados y todo endpoint en modo testing):

| suite | resultado |
|---|---|
| `odoo_pos_getnet_core` | **58 / 58** |
| `odoo_pos_getnet_backend` | **37 / 37** |
| las dos juntas | **95 / 95** |

```bash
odoo-bin -c <conf> -d o19_getnet_test -u odoo_pos_getnet_core,odoo_pos_getnet_backend \
  --test-enable --test-tags /odoo_pos_getnet_core,/odoo_pos_getnet_backend \
  --stop-after-init --max-cron-threads=0
```

## Documentación

| archivo | para quién |
|---|---|
| `odoo_pos_getnet_core/docs/guia_usuario_getnet_backend.md` (+ `.pdf`) | **quien configura y usa** la integración. Sin código |
| `odoo_pos_getnet_core/docs/guia_instalacion_v19.md` | quien monta el entorno |
| `odoo_pos_getnet_core/docs/checklist_validacion_v19_backend.md` | para correr **frente al pinpad**, cuando se agende |
| `odoo_pos_getnet_core/docs/smoke_v19.md` | registro de cada tanda de posteos reales |
| `odoo_pos_getnet_core/docs/staging_checklist.md` | el de v17, que es de donde sale el de arriba |
| `doc/dual-landing.md` | arreglos que valen para las dos ramas |

## Lo que NO está, y por qué

### TPV estándar de Odoo — **paridad pendiente deliberadamente**

> **`odoo_pos_getnet_pos` (el TPV estándar de Odoo) queda fuera del criterio de cierre por decisión
> de Daryl: no se va a usar en los destinos actuales. Retomar si un cliente lo requiere.**

Es una decisión escrita, no un olvido. El módulo existe en la rama de v17 y no se portó; si algún
día hace falta, el punto de partida es ese y la sección 6.6 del checklist de v17.

### Otros

- **Puente con Fiserv** (`odoo_pos_getnet_fiserv_flags`): fuera de esta entrega.
- **Botón en la factura**: el camino soportado es Contabilidad > Pagos. El wizard «Registrar pago»
  de la factura no sirve para este flujo y no es un defecto.
- **Refresco automático del form del pago**: hay que refrescar a mano. Backlog conocido, está
  documentado en la guía de usuario sin disimulo.
- **Validación con pinpad**: pendiente de agenda. El smoke contra el concentrador de integración
  del 26/09/2026 no se pudo completar porque el concentrador devolvía 502/504 — ver `smoke_v19.md`.

## Trabajo en curso, fuera de la entrega

`odoo_pos_getnet_pos_backend` —la terminal Getnet para el **POS Backend** de campera (Sprint 12)—
va en commits propios **encima** de la entrega. No forma parte del `[ADD]`.
