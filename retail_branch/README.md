# Sucursal — ancla de local (`retail_branch`)

Representa la sucursal con el **almacén**, y resuelve la única consecuencia técnica de que
un local cruce la frontera de compañía.

## Por qué el almacén y no un modelo nuevo

El almacén ya es la entidad que tiene ubicaciones, tipos de operación y reglas de
reabastecimiento — todo lo que define operativamente a un local. Un modelo aparte solo
agregaría una tabla que habría que mantener sincronizada.

`is_branch` distingue los locales de los almacenes que no lo son, como el centro de
distribución o el laboratorio.

## El problema que resuelve `_sync_branch_companies()`

Una sucursal de franquicia **factura en la compañía del franquiciado pero mueve inventario
en un almacén de la casa central**. Para Odoo eso son dos compañías distintas.

Odoo 17 soporta jerarquía de compañías, y 26 reglas de core usan
`('company_id', 'parent_of', company_ids)`: con las franquicias declaradas como hijas de la
casa central, **productos, listas de precios, lealtad, impuestos y diarios se comparten
solos**.

Pero `stock` (16 reglas) y `point_of_sale` (7 reglas) usan `('company_id', 'in', company_ids)`,
**sin jerarquía**. Ahí la jerarquía no ayuda, y la única vía limpia es que el usuario tenga
las dos compañías en `company_ids`.

Eso hace `_sync_branch_companies()`, y **solo agrega**: nunca quita una compañía que el
usuario ya tenga, porque puede habérsela dado otro proceso por un motivo que este módulo no
conoce.

## `branch_pos_config_ids` va sin `check_company`

Es deliberado. El PDV de una franquicia pertenece a la compañía del franquiciado y el
almacén a la casa central; `check_company` rechazaría esa combinación, que es exactamente la
que el negocio necesita.

La coherencia se cuida con un `@api.constrains`: todos los PDV de una sucursal tienen que
facturar bajo **una sola** compañía, o la compañía de facturación del local sería ambigua.

## Invalidación de caché

`create` y `write` de `res.users` y de `stock.warehouse` llaman a
`self.env.registry.clear_cache()` cuando cambian `branch_warehouse_ids` o `branch_user_ids`.

Sin eso, los módulos que cachean `ir.rule._compute_domain` por `uid` no ven el cambio de
sucursal hasta que se reinicia el servidor.

## Qué NO hace este módulo

No define grupos ni restringe nada. El perfil de permisos que se apoya en este ancla vive en
`forum_branch_security`, que depende de un módulo de pago. El ancla no depende de nada más
que `stock` y `point_of_sale`, y por eso es reutilizable en cualquier cliente.
