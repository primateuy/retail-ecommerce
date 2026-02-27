/** @odoo-module */

import { Input } from "@point_of_sale/app/generic_components/inputs/input/input";

// Extender props para soportar readonly en inputs del POS (sin reemplazar si está congelado)
if (Input && typeof Input.props === "object" && !Object.prototype.hasOwnProperty.call(Input.props, "readonly")) {
    Input.props = { ...Input.props, readonly: { type: Boolean, optional: true } };
}
if (Input && Input.defaultProps && !Object.prototype.hasOwnProperty.call(Input.defaultProps, "readonly")) {
    Input.defaultProps = { ...Input.defaultProps, readonly: false };
}
