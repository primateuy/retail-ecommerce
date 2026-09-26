# -*- coding: utf-8 -*-
"""Utilidades compartidas por las suites Getnet (core, backend y TPV)."""


class _RelojDeLaboratorio:
    """
    Reloj que sólo ve el módulo bajo prueba.

    Antes se parcheaba ``time.monotonic`` sobre el módulo ``time`` real, que es
    compartido por todo el proceso. En 19.0 el cache del ORM mide tiempos con
    ``time.monotonic()`` en cada ``lookup`` (``odoo/tools/cache.py``), así que
    se comía los valores de la secuencia y el test moría con ``StopIteration``
    en un punto que no tiene nada que ver con lo que se está probando.

    Sustituyendo el nombre ``time`` DENTRO del módulo, la secuencia la consume
    únicamente el código bajo prueba y el resto del proceso sigue con su reloj.
    """

    def __init__(self, secuencia):
        self._it = iter(secuencia)
        self._ultimo = 0.0

    def monotonic(self):
        try:
            self._ultimo = next(self._it)
        except StopIteration:
            pass
        return self._ultimo

    def sleep(self, _segundos):
        return None

    def __getattr__(self, nombre):
        import time as _time_real
        return getattr(_time_real, nombre)
