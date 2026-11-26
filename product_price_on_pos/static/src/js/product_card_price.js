/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ProductCard } from "@point_of_sale/app/components/product_card/product_card";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";

patch(ProductCard.prototype, {
    setup() {
        super.setup(...arguments);
        // usePos() envuelve el store en useState: sin eso la tarjeta no se vuelve a
        // dibujar al cambiar la orden o su lista de precios y queda un precio viejo.
        this.pos = usePos();
    },

    /**
     * Precio del producto formateado en la moneda del PdV.
     *
     * En v19 la tarjeta recibe un product.template (props.product), no una variante:
     * buscarlo por props.productId en product.product devuelve otro producto o nada.
     * Se calcula igual que el popup de información del producto: con la lista de
     * precios y la posición fiscal de la orden actual, con o sin impuestos según
     * la configuración de la caja.
     *
     * @returns {string} Precio formateado, o "" si no hay producto u orden.
     */
    get productCardPrice() {
        const product = this.props.product;
        const pos = this.pos;
        const order = pos.getOrder();
        if (!product || !order) {
            return "";
        }
        const opts = {
            overridedValues: {
                pricelist: order.pricelist_id,
                fiscalPosition: order.fiscal_position_id,
            },
        };
        const taxDetails =
            product.type === "combo"
                ? product.getComboTaxDetails(opts)
                : product.getTaxDetails(opts);
        const price =
            pos.config.iface_tax_included === "total"
                ? taxDetails.total_included
                : taxDetails.total_excluded;
        return this.env.utils.formatCurrency(price);
    },
});
