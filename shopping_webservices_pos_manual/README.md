# Shopping Webservices - POS Manual

Módulo puente entre `shopping_webservices` y `pos_forum_manual_payment`. Muestra el
**Código Shopping** de la transacción dentro del bloque **POS Manual**, debajo del **Sello**.

---

## Qué es un módulo puente

Es un módulo chico cuya única función es conectar dos módulos que no se conocen entre sí.

- El bloque **POS Manual** del formulario de `payment.transaction` lo agrega
  `pos_forum_manual_payment`.
- El campo **Código Shopping** (`shopping_payment_code`) lo agrega `shopping_webservices`.
- `shopping_webservices` **no** depende de `pos_forum_manual_payment`, así que su vista no
  puede referenciar ese bloque: fallaría en una base sin POS Manual.

Alternativas descartadas:

1. Que `shopping_webservices` dependa de `pos_forum_manual_payment`: el shopping arrastraría
   siempre POS Manual y sus dependencias (`odoo_pos_oca_multiple`, `bi_pos_check_info`,
   `l10n_latam_check`…), aunque no se use.
2. Que `pos_forum_manual_payment` dependa de `shopping_webservices`: el mismo problema al revés.

La solución es un tercer módulo que depende de los dos. Es el patrón que usa Odoo, por ejemplo
`sale_stock` une `sale` y `stock`.

---

## Instalación

El módulo tiene `auto_install: True`:

- **Bases nuevas**: Odoo lo instala solo cuando `shopping_webservices` y
  `pos_forum_manual_payment` están instalados. Si falta alguno, no se instala.
- **Bases existentes** (ya tienen los dos módulos): instalarlo una vez, junto con la
  actualización de `shopping_webservices` a `0.6`:

```bash
odoo-bin -c <conf> -u shopping_webservices -i shopping_webservices_pos_manual
```

> La actualización de `shopping_webservices` es necesaria: la vista de este módulo busca el
> campo en los datos generales de la transacción, donde lo ubica la versión `0.6`. Con la vista
> vieja en la base, la instalación falla con "cannot be located in parent view".

---

## Qué cambia

Vista `view_payment_transaction_form_shopping_pos_manual`, que hereda
`payment.payment_transaction_form`:

| Transacción | Dónde se ve el Código Shopping |
|-------------|--------------------------------|
| POS Manual (`is_pos_manual`) | Bloque **POS Manual**, debajo del **Sello** |
| OCA, Fiserv y demás | Datos generales, debajo de **Método de pago** (sin cambios) |

No agrega modelos, campos ni lógica: el cálculo del código está en `shopping_webservices`
(ver su README, sección *Código Shopping de la transacción*).

---

## Dependencias

| Módulo | Uso |
|--------|-----|
| `shopping_webservices` | Campo `shopping_payment_code` |
| `pos_forum_manual_payment` | Bloque POS Manual (`pos_manual_info`) y campos `is_pos_manual`, `manual_stamp` |

---

## Autor

**PrimateUY** — https://primate.uy
