/** @odoo-module */

/**
 * Impresión del ticket de cambio vía navegador sin ventana emergente.
 *
 * Se usa un iframe oculto en la misma pestaña del POS: el HTML del reporte QWeb
 * se escribe ahí y se llama a print() sobre ese marco (impresora predeterminada
 * del sistema, o impresión silenciosa si el navegador está en modo quiosco).
 *
 * El HTML puede traer URLs relativas (códigos de barras); se inyecta <base>.
 */

/**
 * Inserta <base href="..."> tras la etiqueta <head> para resolver rutas relativas
 * del HTML generado en el servidor (imágenes, /report/barcode/, etc.).
 *
 * @param {string} html - Documento o fragmento HTML devuelto por el backend.
 * @param {string} origin - Origen absoluto (p. ej. window.location.origin).
 * @returns {string} HTML listo para document.write.
 */
function injectBaseHref(html, origin) {
    // Bloque: si ya existe <base>, no duplicar.
    if (/<base\s+/i.test(html)) {
        return html;
    }
    // Bloque: insertar base después de <head ...> si existe.
    const withHead = html.replace(/<head([^>]*)>/i, `<head$1><base href="${origin}/">`);
    if (withHead !== html) {
        return withHead;
    }
    // Bloque: sin <head>, envolver en un documento mínimo.
    return `<!DOCTYPE html><html><head><meta charset="utf-8"/><base href="${origin}/"></head><body>${html}</body></html>`;
}

/**
 * Imprime el HTML del ticket usando un iframe invisible (sin nueva ventana/pestaña).
 *
 * @param {string} html - HTML del reporte (respuesta del servidor).
 */
export function printChangeTicketHtmlViaHiddenFrame(html) {
    // Bloque: documento completo con URLs resueltas contra el origen de Odoo.
    const documentHtml = injectBaseHref(html, window.location.origin);

    // Bloque: iframe fuera de vista; evitar display:none porque en algunos navegadores afecta print.
    const iframe = document.createElement("iframe");
    iframe.setAttribute("title", "pos-change-ticket-print");
    iframe.setAttribute("aria-hidden", "true");
    Object.assign(iframe.style, {
        position: "fixed",
        width: "1px",
        height: "1px",
        right: "0",
        bottom: "0",
        border: "0",
        opacity: "0",
        pointerEvents: "none",
    });
    document.body.appendChild(iframe);

    const win = iframe.contentWindow;
    const doc = win.document;
    doc.open();
    doc.write(documentHtml);
    doc.close();

    let cleaned = false;
    let fallbackId;
    // Bloque: eliminar iframe al cerrar el diálogo de impresión; timeout por si afterprint no existe.
    const cleanup = () => {
        if (cleaned) {
            return;
        }
        cleaned = true;
        if (fallbackId !== undefined) {
            clearTimeout(fallbackId);
        }
        iframe.remove();
    };

    win.addEventListener("afterprint", cleanup, { once: true });
    fallbackId = setTimeout(cleanup, 120000);

    // Bloque: pequeña espera para imágenes (p. ej. barcode) antes de imprimir.
    const triggerPrint = () => {
        try {
            win.focus();
            win.print();
        } catch (e) {
            cleanup();
            throw e;
        }
    };

    const delayMs = 400;
    if (doc.readyState === "complete") {
        setTimeout(triggerPrint, delayMs);
    } else {
        iframe.onload = () => setTimeout(triggerPrint, delayMs);
    }
}
