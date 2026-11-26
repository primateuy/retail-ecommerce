// Tiempo que el iframe queda en la página: si se quita antes de que el cajero cierre el
// diálogo de impresión, el navegador cancela la impresión.
const IFRAME_LIFETIME_MS = 60000;
// Si el PDF no carga en este tiempo se abandona, para no dejar trabada la validación.
const LOAD_TIMEOUT_MS = 20000;

/**
 * Abre el diálogo de impresión del navegador con un PDF del mismo origen.
 *
 * @param {string} url URL del PDF servido en línea (p. ej. /web/content/<id>).
 * @returns {Promise<void>} se resuelve al abrir el diálogo; se rechaza si el PDF no carga.
 */
export function printPdf(url) {
    return new Promise((resolve, reject) => {
        const iframe = document.createElement("iframe");
        iframe.style.cssText = "position: fixed; right: 0; bottom: 0; width: 0; height: 0; border: 0;";
        const timeout = setTimeout(() => {
            iframe.remove();
            reject(new Error(`El PDF ${url} no cargó en ${LOAD_TIMEOUT_MS} ms`));
        }, LOAD_TIMEOUT_MS);
        iframe.onload = () => {
            clearTimeout(timeout);
            try {
                iframe.contentWindow.focus();
                iframe.contentWindow.print();
                resolve();
            } catch (error) {
                reject(error);
            } finally {
                setTimeout(() => iframe.remove(), IFRAME_LIFETIME_MS);
            }
        };
        iframe.src = url;
        document.body.appendChild(iframe);
    });
}
