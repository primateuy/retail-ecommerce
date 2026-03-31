/** @odoo-module */

/**
 * Servicio POS: conexión a QZ Tray e impresión HTML en impresora nominal.
 *
 * Requiere RSVP + Sha256 globales (cargados antes que qz-tray.js en el manifiesto)
 * y la app QZ Tray ejecutándose en la máquina del cajero.
 */

import { registry } from "@web/core/registry";

/** Prefijo único para filtrar en consola del navegador (F12). */
const LOG = "[pos_forum_qz_print]";

/**
 * Inserta <base href> para que imágenes y rutas relativas del HTML apunten a Odoo.
 *
 * @param {string} html - HTML del reporte o del recibo.
 * @param {string} origin - Origen (p. ej. window.location.origin).
 * @returns {string} Documento HTML listo para QZ.
 */
function injectBaseHref(html, origin) {
    // Bloque: no duplicar base.
    if (/<base\s+/i.test(html)) {
        return html;
    }
    // Bloque: insertar tras <head>.
    const withHead = html.replace(/<head([^>]*)>/i, `<head$1><base href="${origin}/">`);
    if (withHead !== html) {
        return withHead;
    }
    // Bloque: documento mínimo.
    return `<!DOCTYPE html><html><head><meta charset="utf-8"/><base href="${origin}/"></head><body>${html}</body></html>`;
}

export const qzPrintService = {
    dependencies: [],
    /**
     * Inicializa el servicio QZ (sin dependencias de Odoo para permitir carga temprana).
     */
    start() {
        const certPath = "/pos_forum_qz_print/static/src/lib/digital-certificate.txt";
        const signPath = "/pos_forum_qz_print/sign";

        // Bloque: comprobar que el bundle cargó el conector QZ.
        const ensureQzGlobal = () => {
            if (!window.qz) {
                console.error(
                    `${LOG} No hay window.qz: faltan scripts QZ en assets o el orden de carga es incorrecto.`
                );
                throw new Error(
                    "No se encontró el objeto global qz. Verifique que QZ Tray JS está en los assets."
                );
            }
            return window.qz;
        };

        // Bloque: conectar WebSocket a QZ Tray si aún no está activo.
        const connectIfNeeded = async () => {
            const qz = ensureQzGlobal();
            if (qz.websocket.isActive()) {
                console.info(`${LOG} WebSocket QZ ya activo; se reutiliza la conexión.`);
                return qz;
            }
            console.info(`${LOG} Conectando a QZ Tray (WebSocket)...`);
            // Bloque: certificado público para firma del lado de QZ (reemplazar en producción).
            qz.security.setCertificatePromise((resolve, reject) => {
                fetch(certPath, { credentials: "same-origin" })
                    .then((response) => {
                        if (!response.ok) {
                            console.error(
                                `${LOG} Certificado QZ: HTTP ${response.status} al leer ${certPath}`
                            );
                            reject(new Error("No se pudo cargar digital-certificate.txt"));
                            return null;
                        }
                        return response.text();
                    })
                    .then((text) => {
                        if (text !== null) {
                            console.info(
                                `${LOG} Certificado QZ cargado (${text.length} caracteres).`
                            );
                            resolve(text);
                        }
                    })
                    .catch(reject);
            });
            // Bloque: firma de requests hacia QZ usando endpoint backend protegido.
            qz.security.setSignaturePromise((toSign) => {
                return (resolve, reject) => {
                    fetch(signPath, {
                        method: "POST",
                        credentials: "same-origin",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ data: toSign }),
                    })
                        .then((response) => {
                            if (!response.ok) {
                                throw new Error(
                                    `No se pudo firmar payload QZ (HTTP ${response.status}).`
                                );
                            }
                            return response.text();
                        })
                        .then((signature) => {
                            if (!signature || !String(signature).trim()) {
                                throw new Error("La firma QZ llegó vacía desde el servidor.");
                            }
                            resolve(signature);
                        })
                        .catch((error) => {
                            console.error(`${LOG} Error en setSignaturePromise`, error);
                            reject(error);
                        });
                };
            });
            await qz.websocket.connect();
            console.info(`${LOG} Conexión a QZ Tray establecida.`);
            return qz;
        };

        return {
            /**
             * Expone el helper por si otro código arma HTML manualmente.
             */
            injectBaseHref(html) {
                return injectBaseHref(html, window.location.origin);
            },

            /**
             * Envía HTML a la impresora indicada vía QZ Tray.
             *
             * @param {string} printerName - Nombre exacto de la cola de impresión.
             * @param {string} html - HTML (fragmento o documento).
             */
            async printHtml(printerName, html) {
                if (!printerName || !String(printerName).trim()) {
                    console.error(`${LOG} printHtml abortado: nombre de impresora vacío.`);
                    throw new Error("Falta el nombre de impresora QZ en la configuración del POS.");
                }
                const name = String(printerName).trim();
                const htmlLen = html ? String(html).length : 0;
                console.info(
                    `${LOG} Enviando trabajo de impresión HTML a QZ | impresora=${JSON.stringify(
                        name
                    )} | tamaño_html_entrada=${htmlLen} caracteres`
                );
                const qz = await connectIfNeeded();
                const documentHtml = injectBaseHref(html, window.location.origin);
                console.info(
                    `${LOG} HTML preparado con base href | tamaño_final=${documentHtml.length} caracteres`
                );
                const config = qz.configs.create(name, {
                    margins: { top: 0, right: 0, bottom: 0, left: 0 },
                });
                const printData = [
                    {
                        type: "html",
                        format: "plain",
                        data: documentHtml,
                    },
                ];
                try {
                    await qz.print(config, printData);
                } catch (printErr) {
                    console.error(
                        `${LOG} qz.print() falló (impresora=${JSON.stringify(name)}).`,
                        printErr
                    );
                    throw printErr;
                }
                console.info(
                    `${LOG} qz.print() resuelto (trabajo enviado a la cola QZ / impresora). impresora=${JSON.stringify(
                        name
                    )}`
                );
            },

            /**
             * Imprime varios fragmentos HTML en un único trabajo QZ (p. ej. recibo + ticket
             * de cambio + voucher + cupón). Los bloques vacíos se omiten.
             *
             * @param {string} printerName - Nombre exacto de la cola de impresión.
             * @param {string[]} htmlParts - Lista de HTML en orden.
             */
            async printSequentialHtmlDocuments(printerName, htmlParts) {
                if (!printerName || !String(printerName).trim()) {
                    console.error(`${LOG} printSequentialHtmlDocuments abortado: impresora vacía.`);
                    throw new Error("Falta el nombre de impresora QZ en la configuración del POS.");
                }
                const name = String(printerName).trim();
                const list = (htmlParts || []).filter((h) => h != null && String(h).trim());
                if (!list.length) {
                    throw new Error("No hay HTML para imprimir en la secuencia QZ.");
                }
                console.info(
                    `${LOG} Enviando ${list.length} bloque(s) HTML | impresora=${JSON.stringify(name)}`
                );
                const qz = await connectIfNeeded();
                const config = qz.configs.create(name, {
                    margins: { top: 0, right: 0, bottom: 0, left: 0 },
                });
                const printData = list.map((html) => ({
                    type: "html",
                    format: "plain",
                    data: injectBaseHref(html, window.location.origin),
                }));
                try {
                    await qz.print(config, printData);
                } catch (err) {
                    console.error(
                        `${LOG} qz.print() falló (secuencia ${list.length} bloques, impresora=${JSON.stringify(
                            name
                        )}).`,
                        err
                    );
                    throw err;
                }
                console.info(`${LOG} Secuencia ${list.length} bloque(s): trabajo enviado OK.`);
            },

            /**
             * Compatibilidad: recibo + ticket de cambio + voucher OCA opcional.
             * Delega en ``printSequentialHtmlDocuments``.
             *
             * @param {string} printerName
             * @param {string} firstHtml
             * @param {string} secondHtml
             * @param {string|null} [thirdHtml] - Voucher OCA (opcional).
             */
            async printTwoHtmlWithEscPosCutBetween(printerName, firstHtml, secondHtml, thirdHtml = null) {
                const parts = [firstHtml, secondHtml];
                if (thirdHtml && String(thirdHtml).trim()) {
                    parts.push(thirdHtml);
                }
                return this.printSequentialHtmlDocuments(printerName, parts);
            },
        };
    },
};

registry.category("services").add("qz_print", qzPrintService);
