# Promociones por tarjeta en el cobro Getnet del POS Backend

Módulo `odoo_pos_getnet_promociones`. Depende de `odoo_pos_getnet_pos_backend` (P3) y usa las
operaciones opcionales 8 del contrato de terminales de `pos_backend` (preparar el cobro, opciones
del medio, avisos del pedido). El POS no sabe que existen las promociones.

**Requiere `pos_backend`** con las operaciones opcionales 8 (`8b8356d`) y la recarga de la pantalla
tras un cobro que no arrancó (`eb18622`). Sin la primera el módulo no tiene dónde engancharse; sin
la segunda el cajero no ve la selección manual después de una lectura fallida hasta el próximo
refresco.

## Catálogo

**Configuración › Promociones Getnet** (sólo Manager POS). Una promoción tiene:

- sello (`TarjetaId`);
- emisor (`EmisorId`);
- tipo (crédito o débito);
- BIN opcional, como prefijos o rangos (`421301, 454600-454699`);
- porcentaje;
- vigencia;
- compañía;
- **quién financia**.

Lo que se deja vacío vale «cualquiera». Si una tarjeta califica para varias, gana la de menor
secuencia. La misma búsqueda (`getnet.promocion._buscar`) elige en el modo B y lista en el A.

**La promoción es SIEMPRE una línea de descuento aparte** (decisión del 27/09), en todos los modos
y la financie quien la financie. Las líneas de producto nunca cambian su precio ni su descuento
por una promoción, así el histórico se lee solo.

- **Una línea negativa por combinación de impuestos**, con el producto de descuento (por defecto
  «Descuento promoción Getnet», tipo servicio) y la descripción «Promoción <nombre>».
- **Viaja a todos lados:** se ve en el pedido, en el ticket de la pantalla, en el `sale.order` y en
  la factura. En el `sale.order` y en la factura lleva la promoción y el **ticket del cobro Getnet**
  (campos `getnet_promocion_id` y `getnet_ticket`).
- **Si cambian los productos del pedido**, la línea se rehace sola.
- **Sacar la promoción** borra sus líneas y nada más.
- **La cuenta contable de la línea en la factura es la de la promoción.** Quién financia sólo
  decide cuál:

  | financia | cuenta (`Cuenta contable` de la promoción) |
  |---|---|
  | la empresa | descuentos concedidos |
  | el banco | reintegro a reclamarle al banco |

- **Devoluciones:** cada producto devuelto lleva su parte de la promoción, con una línea por línea
  y sus impuestos. Se devuelve exactamente lo que se pagó y la nota de crédito usa la misma
  cuenta. La línea de descuento de la venta no se elige para devolver.
- **En el CFE (Uruware)** la línea sale como ítem con `Cantidad -1`, `PrecioUnitario` positivo,
  `MontoItem` negativo y el nombre de la promoción en `DscItem`. Los totales cierran: la suma de
  `MontoItem` es igual a `MntNetoIVATasaBasica`.
  - Es la misma forma que Uruware ya firmó en producción: eTickets 101-A-280511, -514, -531 y -536,
    de julio de 2026, con la línea «15% en tu orden».
  - XML de prueba sin firmar: `Desarrollos Documentos/Getnet Campera/cfe/`.
  - **No probado:** una e-Factura (a RUT) con esta línea validada individualmente por DGI. Los
    eTickets de consumidor final no se envían uno a uno.

## Modo por caja

Es el campo «Modo de promociones Getnet» del medio de pago, en el form de la caja, junto a la
terminal. El cambio rige desde el próximo cobro.

- **Automático (B, por defecto):**
  1. El cajero toca Agregar.
  2. Se postea `PostearConsultaDatosTarjeta` y la clienta pasa la tarjeta.
  3. La pantalla sondea `ConsultarDatosTarjeta`, con llamadas cortas, hasta 60 s.
  4. Con sello, emisor, tipo y BIN se busca la promoción y se aplica.
  5. Se cobra el importe reducido **restringido a esa misma tarjeta**: `TarjetaId`, `EmisorId` y
     `TarjetaTipo` de lo leído.

  Sin promoción, se cobra el total sin restricción. No se lee si no hay promociones vigentes, si
  el cobro es parcial, o si el medio no está en la moneda de la compañía.
- **Manual (A):**
  1. El cajero elige «Getnet · <promo>».
  2. Se cobra restringido a lo que pide la promoción, sin lectura.
- **Sin promociones.**

### B → A: la lectura nunca traba el cobro

Cualquier falla de la lectura pasa esa venta a manual y la marca en el pedido. El cajero recibe un
aviso, y el próximo Agregar cobra directo, sin volver a leer. Las fallas son:

- posteo o consulta con rc ≠ 0;
- HTTP o transporte;
- excepción;
- tope de 60 s sin tarjeta;
- respuesta finalizada sin datos de tarjeta;
- terminal ocupada por otro flujo.

## Verificación de cada cobro aprobado

La tarjeta aprobada (`TarjetaId`, `EmisorId`, `TarjetaTipo`, `TarjetaIIN`) se compara con el
catálogo. Nunca se aplica ni se quita una promoción por su cuenta.

| caso | bloquea Finalizar | salidas |
|---|---|---|
| **PROMO NO COINCIDE**: hay promo y la tarjeta que pagó no califica | sí | Reversar (DEV) y cobrar sin promo |
| **PROMO NO APLICADA**: no hay promo, la tarjeta pagó el total y califica | sí | Seguir sin promo · Reversar (DEV) y cobrar con promo |
| **PAGO DIVIDIDO**: hay promo, un cobro con tarjeta aprobado y además otro cobro | sí | Reversar (DEV) y cobrar sin promo, o quitar el otro cobro |
| promo aplicada sin cobro con tarjeta (p. ej. después de un rechazo) | no; sí si hay otro medio cobrando | Quitar promo |

Cada paso queda en el pedido: la solapa «Promoción Getnet» del form, modelo
`getnet.promocion.evento`, con usuario, tarjeta sin el número, ticket y descuento.

La lectura del pinpad queda en `getnet.lectura.tarjeta`, con la respuesta cruda saneada: sin
`TarjetaNro`, titular, vencimiento ni `EmpHASH`. El BIN se conserva.

**Pago dividido:** la promoción sólo aplica si la tarjeta paga el TOTAL. En B no se lee si el
importe es menor al saldo, o si ya hay otro cobro. En A no deja elegir la promoción, con un mensaje.

## Lo que el manual no confirma: `models/getnet_supuestos_lectura.py`

Todo lo que no está confirmado contra el WSDL (que no tenemos: el concentrador de testing está
caído desde el 26/09) está en ese archivo, marcado SUPUESTO, y se ajusta ahí y en ningún otro lado:

- el nombre del parámetro y del tipo del posteo (`ConsultaTarjeta`);
- sus campos (`EmpCod`, `EmpHASH`, `MontoTAP`, `MultiEmp`, `TermCod`);
- el token de la consulta (`TokenNro`);
- la bandera de «terminó».

Si algo no coincide con el concentrador real, la lectura falla y la caja cae sola en A: **nada de
esto puede impedir cobrar**.

Tampoco sabemos qué contesta el pinpad real cuando la clienta pasa una tarjeta que no cumple la
restricción. El simulador contesta `FINALIZADA_ERROR` «TARJETA NO PERMITIDA» (CONSTRUIDO). Se
pidió a New Age Data (mail del 27/09, §4).

## Contactless y `MontoTAP`

El control de cambios v1.1 del manual agrega `MontoTAP` a la lectura previa: con contactless el
pinpad necesita saber el importe **antes** de leer, porque el importe decide si la tarjeta pide PIN
(límite de CVM) y si el tap se admite.

- **Qué mandamos:** el total **sin** promoción, que es lo único que se sabe antes de leer. Como la
  promoción sólo baja el importe, el pinpad pide lo mismo o más de lo que después va a pedir el
  cobro. Es el lado seguro: nunca se lee sin PIN una tarjeta que después debería pedirlo.
- **Lo que no sabemos y hay que mirar en la primera venta real con tap:**
  1. Si el pinpad reusa el tap de la lectura para la transacción, que según el manual guarda los
     datos 30 s, o le pide a la clienta que acerque la tarjeta de nuevo.
  2. Si con tap la lectura devuelve `EmisorId` y `TarjetaIIN`. Algunas billeteras (Apple Pay /
     Google Pay) tokenizan el número y el BIN puede no ser el de la tarjeta física.

  Si falta el emisor, la búsqueda no califica promociones por emisor, se cobra el total, y el
  control de PROMO NO APLICADA sobre el aprobado lo detecta si la transacción sí trae el emisor.
- **Tiempo:** la lectura vence a los 25 s (`LECTURA_VIGENCIA_SEGUNDOS`). La promoción se aplica en
  el mismo sondeo que devuelve los datos y el posteo sale enseguida (en el video, segundos). Si igual se pasa del plazo, el pinpad vuelve a pedir la tarjeta, **con la
  restricción**: no hay forma de que pague otra tarjeta con la promoción.

## Pruebas

- `tests/test_promociones.py` tiene 30 tests por la puerta de la pantalla (`pos_backend.app`),
  mayormente con un **cajero**. Cubren:
  - el catálogo y sus obligatorios (cuenta y producto);
  - B completo;
  - las cinco caídas a A: error del concentrador, error de lectura, respuesta malformada,
    excepción y tope;
  - el cambio de modo;
  - A completo;
  - quitar la promo, que borra sólo su línea;
  - **modo × financiador**: automático, fallback y manual, con empresa y con banco. En todos, línea
    aparte por impuesto y productos intactos;
  - la línea que se rehace al cambiar productos, y que no se edita a mano;
  - el nombre de la promo en el ticket;
  - la promo en el `sale.order` y en la factura, con su cuenta y el ticket Getnet;
  - la devolución proporcional y su nota de crédito;
  - el pago dividido en B y en A, con el cobro parcial y con efectivo;
  - el rechazo;
  - NO APLICADA con sus dos salidas;
  - NO COINCIDE, y la reversa que falla;
  - quién financia (con una regla de firma activa: sin PIN);
  - el aviso con el cobro invisible en la foto del request (REPEATABLE READ).
- Videos contra el simulador, en `Desarrollos Documentos/Getnet Campera/simulador/video/`:
  - `2026-09-27_2241_promos_simulador.webm`: flujos y avisos, 36/36;
  - `2026-09-28_0011_promos_linea_simulador.webm`: la línea de descuento en los 6 casos de modo ×
    financiador, con el ticket, el pedido y la factura, 24/24.
