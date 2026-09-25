/** @odoo-module */

/**
 * Rasterizado de documentos térmicos a ESC/POS.
 *
 * Por qué existe: mandarle el HTML a QZ Tray (``type: "html"``) depende del
 * WebView que QZ lleva adentro, y en la caja ese camino falla de una forma que
 * no avisa — saca un papelito en blanco de unos 3 cm, o imprime sólo el final
 * del documento, o lo agranda cuatro veces. Medido el 25-sep-2026 sobre una
 * CITIZEN CT-S310II con el driver oficial: de los cuatro documentos de la
 * rutina, por HTML no salió ninguno entero.
 *
 * Lo que sí sale perfecto —verificado en papel, los cuatro documentos— es el
 * bitmap por ESC/POS: se rasteriza el documento a 576 puntos de ancho (los
 * 72 mm imprimibles de un rollo de 80 mm a 203 dpi) y se manda con ``GS v 0``,
 * que es el comando que la impresora entiende sin intermediarios.
 *
 * Se rasteriza en el navegador, no en el servidor, por dos razones: el recibo
 * del PDV sólo existe acá (lo arma OWL, no hay reporte del que sacarlo), y las
 * imágenes —el código de barras y el logo— cargan con la sesión del cajero. Por
 * el camino del PDF del servidor el ticket salía sin QR y sin logo.
 */

/** Prefijo único para filtrar en consola del navegador (F12). */
const LOG = "[pos_forum_qz_print]";

/**
 * Ancho de impresión en puntos.
 *
 * 576 = 72 mm × 8 puntos/mm. No es el ancho del rollo (80 mm) sino el del
 * cabezal: los 8 mm restantes son el margen mecánico, y contar con ellos es lo
 * que venía cortando los documentos por la derecha.
 */
const ANCHO_PUNTOS = 576;

/** Bytes por línea: un bit por punto. */
const ANCHO_BYTES = ANCHO_PUNTOS / 8;

/** Líneas por comando ``GS v 0``, para no desbordar el buffer de la impresora. */
const BANDA = 128;

/**
 * Umbral de luminancia para decidir si un punto se imprime.
 *
 * Con texto conviene un umbral duro y no difuminado: el tramado convierte los
 * grises finos en un moteado que a 203 dpi se lee sucio. Los grises claros de
 * los reportes (separadores, texto secundario) quedan igual en negro porque
 * caen por debajo de este valor.
 */
const UMBRAL = 200;

/** Puntos en blanco que se dejan al final, antes del corte. */
const COLA_BLANCA = 24;

/** Milisegundos que se espera como máximo por una imagen. */
const ESPERA_IMAGEN_MS = 4000;

/**
 * Espera a que todas las imágenes del documento estén decodificadas.
 *
 * Es el paso que no se puede saltear: el código de barras llega como data URI y
 * tarda un ciclo en decodificarse. Rasterizar antes da un documento sin barcode
 * —o directamente vacío, que es el papelito en blanco de 3 cm—.
 *
 * 🔴 Y hay una trampa que costó una tira de papel: el cupón trae su código de
 * barras con ``loading="lazy"``. En un marco chico y fuera de pantalla el
 * navegador decide que esa imagen no se ve y **no la carga nunca**: no dispara
 * ``load`` ni ``error``, así que la espera no termina y la impresión queda
 * colgada sin un solo mensaje. Por eso acá se le saca el diferido a cada imagen
 * antes de esperarla, y además la espera tiene reloj: un documento no puede
 * dejar la caja esperando.
 *
 * @param {Document} doc
 * @returns {Promise<void>}
 */
async function esperarImagenes(doc) {
    const imagenes = Array.from(doc.images || []);
    imagenes.forEach((img) => {
        img.loading = "eager";
        img.removeAttribute("loading");
        img.decoding = "sync";
    });
    await Promise.all(
        imagenes.map((img) =>
            img.complete
                ? Promise.resolve()
                : new Promise((listo) => {
                      const reloj = setTimeout(() => {
                          console.warn(
                              `${LOG} Imagen sin cargar tras ${ESPERA_IMAGEN_MS} ms; se rasteriza igual.`
                          );
                          listo();
                      }, ESPERA_IMAGEN_MS);
                      const terminar = () => {
                          clearTimeout(reloj);
                          listo();
                      };
                      img.addEventListener("load", terminar, { once: true });
                      img.addEventListener("error", terminar, { once: true });
                  })
        )
    );
    // Dos cuadros: uno para que el navegador aplique el layout con las imágenes
    // ya medidas, otro para que lo pinte.
    await new Promise((listo) => requestAnimationFrame(() => requestAnimationFrame(listo)));
}

/**
 * Renderiza un documento HTML completo a un canvas de ``ANCHO_PUNTOS`` de ancho.
 *
 * El documento se monta en un iframe fuera de pantalla con el ancho natural que
 * declara (los 80 mm de los reportes), se deja reflowear, y recién ahí se
 * rasteriza con el factor de escala que lo lleva a 576 puntos. Así el texto se
 * dibuja directamente a la resolución del cabezal en vez de escalarse después.
 *
 * @param {string} documentHtml - Documento HTML autocontenido.
 * @returns {Promise<HTMLCanvasElement>}
 */
async function rasterizarDocumento(documentHtml) {
    const marco = document.createElement("iframe");
    marco.setAttribute("aria-hidden", "true");
    // Fuera de la pantalla pero NO oculto: html2canvas necesita que el navegador
    // lo haya maquetado y pintado; con ``visibility: hidden`` se rasteriza vacío.
    //
    // Y nace alto, no de 10 mm: un marco chico deja las imágenes diferidas fuera
    // de la vista y el navegador no las carga. Después se ajusta al alto real.
    marco.style.cssText =
        "position:fixed;left:-10000px;top:0;border:0;width:80mm;height:2000px;opacity:0;";
    document.body.appendChild(marco);
    try {
        const doc = marco.contentDocument;
        if (!doc) {
            throw new Error("No se pudo crear el marco de rasterizado.");
        }
        doc.open();
        doc.write(documentHtml);
        doc.close();
        await esperarImagenes(doc);

        const raiz = doc.body;
        const anchoCss = Math.max(raiz.scrollWidth, doc.documentElement.scrollWidth, 1);
        const altoCss = Math.max(raiz.scrollHeight, doc.documentElement.scrollHeight, 1);
        // El iframe tiene que ser tan alto como el documento: html2canvas
        // rasteriza lo que entra en la ventana, y con 10 mm de alto saldría
        // recortado a la primera línea.
        marco.style.height = `${altoCss}px`;
        await new Promise((listo) => requestAnimationFrame(listo));

        const escala = ANCHO_PUNTOS / anchoCss;
        console.info(
            `${LOG} Rasterizando | documento=${anchoCss}×${altoCss} px CSS | escala=${escala.toFixed(
                3
            )} | destino=${ANCHO_PUNTOS} puntos`
        );
        const html2canvas = window.html2canvas;
        if (typeof html2canvas !== "function") {
            throw new Error("Falta html2canvas: no se puede rasterizar el documento.");
        }
        return await html2canvas(raiz, {
            scale: escala,
            backgroundColor: "#ffffff",
            width: anchoCss,
            height: altoCss,
            windowWidth: anchoCss,
            windowHeight: altoCss,
            logging: false,
            // El documento ya está en su propio marco: no hace falta que
            // html2canvas clone otra vez el árbol a un tercer iframe.
            foreignObjectRendering: false,
        });
    } finally {
        marco.remove();
    }
}

/**
 * Convierte un canvas a los bytes ESC/POS que imprimen ese bitmap.
 *
 * Formato: ``GS v 0`` por bandas de ``BANDA`` líneas, un bit por punto, el bit
 * más significativo a la izquierda. Al final se recorta el blanco sobrante y se
 * manda avance + corte parcial, que es lo que hace que salga una tira del largo
 * del documento y no una hoja fija.
 *
 * @param {HTMLCanvasElement} canvas
 * @returns {Uint8Array} Bytes listos para la impresora.
 */
function canvasAEscPos(canvas) {
    const ancho = Math.min(canvas.width, ANCHO_PUNTOS);
    const alto = canvas.height;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    const pixeles = ctx.getImageData(0, 0, ancho, alto).data;

    // Bloque: pasar a blanco y negro y, de paso, ubicar la última línea con
    // tinta. La página del reporte es mucho más alta que el documento, y sin
    // este recorte cada ticket se llevaría el resto de la hoja en blanco.
    const filas = new Uint8Array(alto * ANCHO_BYTES);
    let ultimaConTinta = -1;
    for (let y = 0; y < alto; y++) {
        const base = y * ANCHO_BYTES;
        let tinta = false;
        for (let x = 0; x < ancho; x++) {
            const p = (y * ancho + x) * 4;
            const alfa = pixeles[p + 3];
            // Luminancia perceptual; lo transparente cuenta como papel.
            const lum =
                alfa === 0
                    ? 255
                    : 0.299 * pixeles[p] + 0.587 * pixeles[p + 1] + 0.114 * pixeles[p + 2];
            if (lum < UMBRAL) {
                filas[base + (x >> 3)] |= 0x80 >> (x & 7);
                tinta = true;
            }
        }
        if (tinta) {
            ultimaConTinta = y;
        }
    }
    const altoUtil = ultimaConTinta < 0 ? 0 : Math.min(alto, ultimaConTinta + 1 + COLA_BLANCA);
    if (!altoUtil) {
        throw new Error("El documento se rasterizó en blanco.");
    }

    const salida = [];
    const empujar = (...bytes) => bytes.forEach((b) => salida.push(b));
    empujar(0x1b, 0x40); // ESC @ — inicializar
    for (let y = 0; y < altoUtil; y += BANDA) {
        const lineas = Math.min(BANDA, altoUtil - y);
        empujar(0x1d, 0x76, 0x30, 0x00); // GS v 0 — bitmap en modo normal
        empujar(ANCHO_BYTES & 0xff, ANCHO_BYTES >> 8, lineas & 0xff, lineas >> 8);
        const desde = y * ANCHO_BYTES;
        for (let i = 0; i < lineas * ANCHO_BYTES; i++) {
            salida.push(filas[desde + i]);
        }
    }
    empujar(0x1b, 0x64, 0x04); // ESC d 4 — avanzar para despegar del cabezal
    empujar(0x1d, 0x56, 0x42, 0x00); // GS V B 0 — corte parcial
    console.info(
        `${LOG} ESC/POS generado | ${altoUtil} líneas de ${ANCHO_PUNTOS} puntos | ${salida.length} bytes`
    );
    return Uint8Array.from(salida);
}

/**
 * Codifica bytes en base64, que es como viajan los datos crudos hacia QZ.
 *
 * @param {Uint8Array} bytes
 * @returns {string}
 */
function aBase64(bytes) {
    let binario = "";
    const TRAMO = 0x8000; // por tramos: un apply con 300 KB de argumentos revienta
    for (let i = 0; i < bytes.length; i += TRAMO) {
        binario += String.fromCharCode.apply(null, bytes.subarray(i, i + TRAMO));
    }
    return btoa(binario);
}

/**
 * Convierte un documento HTML térmico en el payload crudo que espera QZ.
 *
 * @param {string} documentHtml - Documento HTML autocontenido.
 * @returns {Promise<string>} Bytes ESC/POS en base64.
 */
export async function documentoAEscPosBase64(documentHtml) {
    const canvas = await rasterizarDocumento(documentHtml);
    return aBase64(canvasAEscPos(canvas));
}
