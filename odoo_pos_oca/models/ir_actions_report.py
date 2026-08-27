# -*- coding: utf-8 -*-
"""
Generación de códigos de barras Code128 legibles en impresoras térmicas de 80 mm.

Motivo de este helper
---------------------
``ir.actions.report.barcode()`` (y por lo tanto ``/report/barcode/Code128/...``)
delega en ``createBarcodeDrawing(width=..., height=...)``, que **estira** el dibujo
por un factor arbitrario para llegar al tamaño pedido. Con los parámetros que se
venían usando (``width=600``) el factor es 3,577: cada módulo del código queda en
1,93 px y el PNG sale con ~115 de 600 píxeles en gris antialiaseado, con barras de
un mismo módulo midiendo 2, 4, 5 o 6 px. Una térmica binariza eso de forma
arbitraria y el lector no decodifica.

Acá se hace al revés: primero se cuenta cuántos módulos ocupa el código, después se
elige un ``barWidth`` **entero en puntos** y se renderiza **sin escalado**. Como
1 pt = 1 px a 72 dpi (el default de renderPM), cada módulo cae en un número exacto
de píxeles: cero antialiasing y proporciones de barra exactas.

El PNG resultante pesa ~400 bytes (contra ~3 kB del estirado).
"""

import base64
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# Ancho útil por defecto para papel de 80 mm. El área imprimible real de una
# térmica de 80 mm ronda los 72 mm; 70 mm deja margen y evita que el código quede
# pegado al borde (la quiet zone tiene que entrar dentro del papel, no fuera).
FORUM_BARCODE_TARGET_MM = 70.0

# Alto del código. Code128 pide como mínimo 6,35 mm; 12 mm da margen para que la
# pistola enganche sin que el operador tenga que apuntar fino.
FORUM_BARCODE_HEIGHT_MM = 12.0

# Resolución típica de las térmicas del parque (203 dpi). Se usa sólo para elegir
# cuántos píxeles por módulo generar, de forma que el PNG caiga casi 1:1 sobre la
# grilla de puntos de la impresora y no haya remuestreo.
FORUM_BARCODE_DPI = 203.0

# Quiet zone en módulos a cada lado. La norma Code128 exige 10.
FORUM_BARCODE_QUIET_MODULES = 10

# Píxeles por módulo mínimos: por debajo de 2 las barras finas se pierden.
FORUM_BARCODE_MIN_PX_PER_MODULE = 2

# Ancho de módulo mínimo aceptable en milímetros. Referencia Code128: 0,25 mm es
# el mínimo absoluto y 0,33 mm el recomendado. Por debajo de esto sólo se loguea
# un aviso; igual se genera, porque un código angosto es mejor que ninguno.
FORUM_BARCODE_MIN_MM_PER_MODULE = 0.30


class IrActionsReport(models.Model):
    """
    Helper de barcode térmico compartido por los recibos del PDV.
    """

    _inherit = 'ir.actions.report'

    @api.model
    def _forum_normalize_barcode_value(self, value):
        """
        Deja el valor listo para codificar quitando el prefijo textual de la orden.

        ``pos.order.pos_reference`` vale ``"Order 00013-001-0002"`` (o
        ``"Pedido ..."`` según el idioma del PDV): la palabra inicial no aporta nada
        al escaneo y cuesta caro. Son 77 módulos extra sobre 187, es decir un 41 %
        menos de ancho por módulo (0,374 mm -> 0,265 mm), que es la diferencia entre
        un código holgado y uno en el límite de lo legible.

        El resto se deja intacto, así lo escaneado sigue haciendo match por substring
        contra ``pos_reference`` tanto en la búsqueda del PDV como en el backend.

        :param value: valor crudo (p. ej. ``pos_reference``).
        :return: valor a codificar, sin el prefijo alfabético inicial.
        """
        text = (value or '').strip()
        if not text:
            return ''
        # Cortar lo anterior al primer dígito SÓLO si lo descartado es una palabra
        # suelta seguida de espacio ("Order ", "Pedido "). El espacio final es la
        # condición clave: sin él, un código pegado tipo "ABCD1234" (perfectamente
        # posible en un cupón de loyalty) quedaría reducido a "1234" y dejaría de
        # identificar al registro. Si el valor empieza con dígito, no tiene dígitos,
        # o el prefijo no es una palabra separada, se devuelve intacto.
        for index, char in enumerate(text):
            if char.isdigit():
                prefix = text[:index]
                is_separate_word = prefix != prefix.rstrip()
                if is_separate_word and prefix.strip().isalpha():
                    return text[index:].strip()
                return text
        return text

    @api.model
    def _forum_code128_thermal(self, value, target_mm=None, height_mm=None, dpi=None,
                               normalize=True):
        """
        Devuelve un Code128 nítido, alineado a módulo y dimensionado para 80 mm.

        :param value: texto a codificar.
        :param target_mm: ancho físico destino en mm (default 70).
        :param height_mm: alto físico destino en mm (default 12).
        :param dpi: resolución de la impresora, para elegir píxeles por módulo (default 203).
        :param normalize: si ``True`` (default) aplica ``_forum_normalize_barcode_value``
            para sacar el prefijo "Order "/"Pedido " de la referencia de la orden.
            Pasar ``False`` cuando el valor es un identificador que no se puede alterar
            (p. ej. el código de un cupón de loyalty).
        :return: dict con ``uri``, ``value``, ``width_mm``, ``height_mm``,
                 ``modules`` y ``mm_per_module``; o ``False`` si no se pudo generar.
        """
        encoded = self._forum_normalize_barcode_value(value) if normalize else (value or '').strip()
        if not encoded:
            return False

        target_mm = float(target_mm or FORUM_BARCODE_TARGET_MM)
        height_mm = float(height_mm or FORUM_BARCODE_HEIGHT_MM)
        dpi = float(dpi or FORUM_BARCODE_DPI)

        try:
            from reportlab.graphics.barcode import createBarcodeDrawing
        except ImportError:
            _logger.warning('odoo_pos_oca: reportlab no disponible, no se genera el Code128.')
            return False

        try:
            # Paso 1: sondeo con barWidth=1 para contar módulos (incluida la quiet
            # zone). getBounds() devuelve puntos; con barWidth=1 pt, 1 punto = 1 módulo.
            probe = createBarcodeDrawing(
                'Code128',
                value=encoded,
                barWidth=1,
                barHeight=10,
                lquiet=FORUM_BARCODE_QUIET_MODULES,
                rquiet=FORUM_BARCODE_QUIET_MODULES,
                humanReadable=False,
            )
            bounds = probe.contents[0].getBounds()
            modules = int(round(bounds[2] - bounds[0]))
            if modules <= 0:
                return False

            # Paso 2: píxeles por módulo enteros, para que el PNG caiga lo más cerca
            # posible de la grilla de puntos de la impresora sin remuestreo.
            target_dots = target_mm / 25.4 * dpi
            px_per_module = max(
                FORUM_BARCODE_MIN_PX_PER_MODULE,
                int(round(target_dots / modules)),
            )
            bar_height_px = int(round(height_mm / target_mm * modules * px_per_module))

            # Paso 3: render sin width/height, es decir sin escalado. Cada módulo
            # ocupa exactamente px_per_module píxeles.
            drawing = createBarcodeDrawing(
                'Code128',
                value=encoded,
                barWidth=px_per_module,
                barHeight=bar_height_px,
                lquiet=FORUM_BARCODE_QUIET_MODULES * px_per_module,
                rquiet=FORUM_BARCODE_QUIET_MODULES * px_per_module,
                humanReadable=False,
            )
            png = drawing.asString('png')
        except Exception as err:
            _logger.warning(
                'odoo_pos_oca: no se pudo generar el Code128 | valor=%r | %s', encoded, err
            )
            return False

        mm_per_module = target_mm / modules
        if mm_per_module < FORUM_BARCODE_MIN_MM_PER_MODULE:
            _logger.warning(
                'odoo_pos_oca: Code128 angosto | valor=%r | %s módulos | %.3f mm/módulo '
                '(mínimo recomendado %.2f). Puede costar leerlo con lectora CCD.',
                encoded, modules, mm_per_module, FORUM_BARCODE_MIN_MM_PER_MODULE,
            )

        return {
            'uri': 'data:image/png;base64,' + base64.b64encode(png).decode('ascii'),
            'value': encoded,
            'width_mm': target_mm,
            'height_mm': height_mm,
            'modules': modules,
            'mm_per_module': round(mm_per_module, 4),
        }
