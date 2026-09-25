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
 * CSS del envoltorio térmico.
 *
 * Deliberadamente NO toca html/body/@page ni el tipo de caja: el recibo que
 * imprime «Imprimir Boleta» tiene que salir exactamente igual que hasta ahora,
 * y hoy sale con los márgenes por defecto del motor. Acá sólo van reglas que
 * enganchan en las clases que traen los reportes QWeb del servidor.
 *
 * Por qué hacen falta: el recibo del PDV llega como fragmento pelado (un <div>
 * sin <html> ni CSS), mientras que el ticket de cambio y el voucher llegan
 * envueltos en ``web.html_container``, es decir con ``<body class="container">``
 * y los CSS de /web/assets pensados para A4, y con ``max-width`` fijado en
 * milímetros. Esos 80 mm clavados desbordan el área imprimible real del rollo
 * (~72 mm en una térmica de 80 mm): de ahí salía el recorte a izquierda y derecha.
 */
const THERMAL_CSS = `
.container, .container-fluid {
    width: 100% !important;
    max-width: 100% !important;
    margin-left: 0 !important;
    margin-right: 0 !important;
    padding-left: 0 !important;
    padding-right: 0 !important;
}
/* .article, .page y los contenedores térmicos conservan su max-width en mm:
   es el que fija el tamaño con el que QZ viene imprimiendo. Sólo se les saca
   el padding lateral de Bootstrap. */
.article, .page, .o_forum_loyalty_coupon_thermal, .oca-thermal-voucher {
    padding-left: 0 !important;
    padding-right: 0 !important;
}
img { max-width: 100% !important; }
`;
/**
 * Quita del HTML todo lo que apunte a los assets web de Odoo y cualquier script.
 *
 * Los reportes QWeb salen de ``web.html_container`` con <link> y <script> a
 * /web/assets/...: hojas de estilo de reporte A4 que no tienen nada que hacer en
 * un documento de 80 mm, y recursos que el WebView de QZ Tray tiene que resolver
 * contra el servidor antes de dar la página por cargada. El recibo del PDV es el
 * único documento que nunca los trajo, y es justamente el único que imprimía bien.
 *
 * @param {string} html
 * @returns {string}
 */
function stripWebAssets(html) {
    if (!html) {
        return "";
    }
    let out = String(html);
    out = out.replace(
        /<link[^>]+href=['"][^'"]*?\/web\/assets\/[^'"]+['"][^>]*\/?>/gi,
        ""
    );
    // Bloque: cualquier <script> sobra en un documento de impresión, venga de
    // /web/assets o sea inline.
    out = out.replace(/<script[\s\S]*?<\/script>/gi, "");
    return out;
}

/**
 * Extrae el cuerpo de un documento HTML completo y conserva sus <style> inline.
 *
 * @param {string} html
 * @returns {{body: string, styles: string}}
 */
function extractBody(html) {
    const txt = String(html || "");
    const bodyMatch = txt.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
    if (!bodyMatch) {
        return { body: txt, styles: "" };
    }
    const headMatch = txt.match(/<head[^>]*>([\s\S]*?)<\/head>/i);
    let styles = "";
    if (headMatch) {
        const found = headMatch[1].match(/<style[\s\S]*?<\/style>/gi);
        if (found) {
            styles = found.join("\n");
        }
    }
    return { body: bodyMatch[1], styles };
}

/**
 * Normaliza cualquier fragmento o documento a un HTML térmico autocontenido.
 *
 * Todos los documentos de la rutina pasan por acá, de modo que el recibo que
 * imprime «Imprimir Boleta» y el que imprime «Rutina» son byte a byte el mismo
 * documento: si los márgenes están bien en uno, están bien en el otro.
 *
 * @param {string} html - Fragmento o documento HTML.
 * @param {string} origin - Origen para el <base href>.
 * @returns {string} Documento HTML listo para QZ.
 */
function buildThermalDocument(html, origin) {
    const limpio = stripWebAssets(html);
    const { body, styles } = extractBody(limpio);
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\"/>" +
        `<base href="${origin}/"/>` +
        `<style>${THERMAL_CSS}</style>` +
        styles +
        `</head><body>${body}</body></html>`
    );
}

export const qzPrintService = {
    dependencies: [],
    /**
     * Inicializa el servicio QZ (sin dependencias de Odoo para permitir carga temprana).
     */
    start() {
        const certPath = "/pos_forum_qz_print/static/src/lib/digital-certificate.txt";
        const signPath = "/pos_forum_qz_print/sign";

        // Bloque: promesa única de conexión. Dos impresiones lanzadas casi a la vez
        // (p. ej. el recibo automático y un botón de la fila de acciones) llamaban
        // cada una a qz.websocket.connect(); la segunda se encontraba con un intento
        // en curso y moría con «The current connection attempt has not returned yet».
        let conexionEnCurso = null;

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
                return qz;
            }
            if (conexionEnCurso) {
                await conexionEnCurso;
                return qz;
            }
            console.info(`${LOG} Conectando a QZ Tray (WebSocket)...`);
            // Bloque: certificado público para firma del lado de QZ.
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
            // Bloque: reintentos. Una térmica compartida o un QZ Tray que acaba de
            // arrancar tarda en aceptar el socket; sin reintento el primer botón que
            // se aprieta cae al PDF y el operador cree que QZ no anda.
            conexionEnCurso = Promise.resolve(
                qz.websocket.connect({ retries: 2, delay: 1 })
            )
                .then(() => {
                    console.info(`${LOG} Conexión a QZ Tray establecida.`);
                })
                .finally(() => {
                    conexionEnCurso = null;
                });
            await conexionEnCurso;
            return qz;
        };

        /**
         * Configuración de impresión. Única para todos los documentos: es lo que
         * garantiza que la rutina y el botón de recibo compartan márgenes.
         */
        const crearConfig = (qz, name, options = {}) => {
            // Misma configuración que venía usando el recibo: márgenes en cero y
            // el tamaño de página del driver de la impresora. No se fuerza ``size``
            // a propósito — el driver ya sabe que el rollo es de 80 mm, y forzarlo
            // rompería el único camino que hoy imprime bien.
            return qz.configs.create(name, {
                margins: { top: 0, right: 0, bottom: 0, left: 0 },
                jobName: options.jobName || "Odoo PDV",
            });
        };

        return {
            /**
             * Expone el helper por si otro código arma HTML manualmente.
             */
            injectBaseHref(html) {
                return buildThermalDocument(html, window.location.origin);
            },

            /**
             * Normaliza un fragmento al documento térmico estándar (sin imprimir).
             */
            buildThermalDocument(html) {
                return buildThermalDocument(html, window.location.origin);
            },

            /**
             * Envía HTML a la impresora indicada vía QZ Tray.
             *
             * @param {string} printerName - Nombre exacto de la cola de impresión.
             * @param {string} html - HTML (fragmento o documento).
             * @param {Object} [options] - ``jobName`` para la cola de impresión.
             */
            async printHtml(printerName, html, options = {}) {
                if (!printerName || !String(printerName).trim()) {
                    console.error(`${LOG} printHtml abortado: nombre de impresora vacío.`);
                    throw new Error("Falta el nombre de impresora QZ en la configuración del POS.");
                }
                const name = String(printerName).trim();
                const htmlLen = html ? String(html).length : 0;
                console.info(
                    `${LOG} Enviando trabajo de impresión HTML a QZ | impresora=${JSON.stringify(
                        name
                    )} | documento=${options.jobName || "-"} | tamaño_html_entrada=${htmlLen} caracteres`
                );
                const qz = await connectIfNeeded();
                const documentHtml = buildThermalDocument(html, window.location.origin);
                console.info(
                    `${LOG} HTML térmico preparado | tamaño_final=${documentHtml.length} caracteres`
                );
                const config = crearConfig(qz, name, options);
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
             * Imprime varios documentos, uno por trabajo, en el orden recibido.
             *
             * Antes iban los cuatro en un único ``qz.print()`` multi-documento. Se
             * pasó a un trabajo por documento a propósito: es exactamente la misma
             * llamada que hace el botón «Imprimir Boleta», que es el camino que se
             * sabe que imprime con los márgenes correctos. Los bloques vacíos se omiten.
             *
             * @param {string} printerName - Nombre exacto de la cola de impresión.
             * @param {string[]} htmlParts - Lista de HTML en orden.
             * @param {Object} [options] - ``labels``: nombre de cada documento.
             */
            async printSequentialHtmlDocuments(printerName, htmlParts, options = {}) {
                if (!printerName || !String(printerName).trim()) {
                    console.error(`${LOG} printSequentialHtmlDocuments abortado: impresora vacía.`);
                    throw new Error("Falta el nombre de impresora QZ en la configuración del POS.");
                }
                const name = String(printerName).trim();
                const etiquetas = options.labels || [];
                const lista = [];
                (htmlParts || []).forEach((h, idx) => {
                    if (h != null && String(h).trim()) {
                        lista.push({ html: h, label: etiquetas[idx] || `documento ${idx + 1}` });
                    }
                });
                if (!lista.length) {
                    throw new Error("No hay HTML para imprimir en la secuencia QZ.");
                }
                console.info(
                    `${LOG} Enviando ${lista.length} documento(s) en trabajos separados | impresora=${JSON.stringify(
                        name
                    )}`
                );
                // Bloque: la conexión se resuelve una sola vez antes del bucle para
                // que un corte a mitad de la rutina no dispare varios reintentos.
                await connectIfNeeded();
                for (const doc of lista) {
                    await this.printHtml(name, doc.html, {
                        ...options,
                        jobName: doc.label,
                    });
                }
                console.info(`${LOG} Secuencia de ${lista.length} documento(s): enviada OK.`);
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
