/** @odoo-module */

import { PartnerListScreen } from "@point_of_sale/app/screens/partner_list/partner_list";
import { patch } from "@web/core/utils/patch";

// Lo que la cajera escribe cuando busca por documento: dígitos, con o sin puntos y guión.
const PARECE_DOCUMENTO = /^[\d.\-\s]+$/;

patch(PartnerListScreen.prototype, {
    /**
     * Si lo que se escribió es un documento, busca sólo por el comienzo del documento.
     *
     * La búsqueda de Odoo prueba el texto en 12 campos a la vez (nombre, teléfono, mail, calle,
     * ciudad, documento…) y en cualquier parte del texto, así que la base no puede usar índices:
     * con los ~660.000 clientes de Forum tardaba 3,3 s por búsqueda en producción (11-2026).
     * Por documento usa el índice `res_partner_vat_prefijo_index` y tarda milisegundos. Lo que
     * no es un número (un nombre, un mail) sigue con la búsqueda de Odoo.
     */
    async getNewPartners() {
        const consulta = (this.state.query || "").trim();
        const digitos = consulta.replace(/[.\-\s]/g, "");
        if (!PARECE_DOCUMENTO.test(consulta) || digitos.length < 3) {
            return super.getNewPartners(...arguments);
        }
        // Hay documentos guardados con ceros adelante (01234561, 00030172641): se prueba el
        // número con 0 a 3 ceros adelante. Cada variante usa el índice por separado.
        const base = digitos.replace(/^0+/, "") || "0";
        const variantes = ["", "0", "00", "000"].map((ceros) => ["vat", "=like", ceros + base + "%"]);
        const domain = [...Array(variantes.length - 1).fill("|"), ...variantes];
        return await this.orm.silent.call(
            "pos.session",
            "get_pos_ui_res_partner_by_params",
            [
                [odoo.pos_session_id],
                {
                    domain,
                    limit: 30,
                    offset: this.state.currentOffset,
                },
            ]
        );
    },
});
