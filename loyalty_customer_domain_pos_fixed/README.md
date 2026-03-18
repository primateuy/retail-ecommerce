# Loyalty Customer Domain POS

Módulo para Odoo 17 que extiende al POS el campo `customer_domain` agregado por el módulo `loyality_customer_domain`.

## Qué hace

- Carga `customer_domain` de `loyalty.rule` en la sesión POS.
- Carga `category_id` del partner en POS para soportar dominios por etiquetas.
- Filtra recompensas reclamables en POS según el cliente seleccionado.
- Bloquea la aplicación manual de recompensas cuando el cliente no cumple el dominio.

## Alcance

Está pensado para dominios evaluables con campos ya disponibles en el POS. Especialmente:

- `id`
- `name`
- `email`
- `phone`
- `mobile`
- `barcode`
- `category_id`
- many2one básicos ya cargados en POS

## Operadores soportados en frontend

- `=`
- `!=`
- `in`
- `not in`
- `>`
- `>=`
- `<`
- `<=`
- `like`
- `ilike`
- `=?`
- combinaciones con `&`, `|`, `!`

## Limitaciones

- No intenta soportar operadores complejos como `child_of`.
- Si usás un domain con campos que no estén cargados en el POS, la regla no va a coincidir.
- Está orientado a POS con `pos_loyalty` en Odoo 17.
