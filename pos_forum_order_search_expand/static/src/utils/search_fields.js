/** @odoo-module */

// Clave del campo de búsqueda "Todo" del buscador de órdenes. Vive acá y no en
// el override de TicketScreen para que el patch de PosStore no importe un
// override desde otro override.
export const ALL_SEARCH_FIELD = "ALL";
