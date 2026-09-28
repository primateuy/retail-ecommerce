{
    "name": "Getnet TransAct - Promociones por tarjeta (POS Backend)",
    "summary": "Promociones por sello, emisor, tipo o BIN de la tarjeta al cobrar con Getnet en el POS Backend.",
    "description": """
Promociones por tarjeta para el cobro Getnet del POS Backend, como las de OCA,
con un catálogo propio (no loyalty) y tres modos por caja:

- **Detección automática** (por defecto): se lee la tarjeta ANTES de cobrar
  (PostearConsultaDatosTarjeta / ConsultarDatosTarjeta), se busca la promoción
  aplicable, se aplica y se cobra el monto reducido con la restricción de esa
  misma tarjeta. Si la lectura falla por cualquier motivo, esa venta pasa sola
  a selección manual, con un aviso al cajero.
- **Selección manual** (respaldo): el cajero elige la promoción; se cobra con
  la restricción TarjetaId/EmisorId/TarjetaTipo.
- **Sin promociones**.

La promoción es siempre una línea de descuento aparte, por grupo de impuestos,
que llega al sale.order y a la factura con la promoción y el ticket Getnet.
Quién la financia sólo decide la cuenta contable de esa línea.

Al aprobar cualquier cobro Getnet se compara la tarjeta devuelta con el
catálogo: PROMO NO COINCIDE y PROMO NO APLICADA quedan visibles y bloquean el
pedido hasta que el cajero elige una salida explícita. El sistema nunca aplica
ni saca una promoción por su cuenta.

Lo que el manual no confirma de la lectura previa está en un solo archivo,
`models/getnet_supuestos_lectura.py`, marcado como supuesto.
    """,
    "author": "PRIMATE",
    "website": "https://www.primate.com",
    "category": "Point of Sale",
    "version": "19.0.1.0.0",
    "depends": [
        "odoo_pos_getnet_pos_backend",
        "sale",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/getnet_promocion_data.xml",
        "views/getnet_promocion_views.xml",
        "views/pos_backend_box_payment_method_views.xml",
    ],
    "license": "LGPL-3",
}
