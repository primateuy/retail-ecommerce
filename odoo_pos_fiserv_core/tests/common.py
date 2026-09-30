# -*- coding: utf-8 -*-
"""Utilidades compartidas por las suites Fiserv (core y backend)."""

import json
from unittest.mock import MagicMock

import requests


class _RelojDeLaboratorio:
    """
    Reloj que sólo ve el módulo bajo prueba.

    Parchear ``time.monotonic`` sobre el módulo ``time`` real rompe el
    proceso entero: en 19.0 el cache del ORM mide tiempos con
    ``time.monotonic()`` en cada ``lookup`` y se come la secuencia (lección
    pagada en el port de Getnet). Sustituyendo el nombre ``time`` DENTRO del
    módulo, la secuencia la consume únicamente el código bajo prueba.
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


def respuesta_http(status=200, payload=None, texto=None):
    """Respuesta de `requests` falsa (sólo lo que usa fiserv_itd_http_post)."""
    resp = MagicMock()
    resp.status_code = status
    if texto is None:
        texto = json.dumps(payload) if payload is not None else ''
    resp.text = texto

    def _json():
        if payload is None:
            raise ValueError('no es JSON')
        return dict(payload)

    resp.json.side_effect = _json
    return resp


def post_secuencial(*respuestas):
    """
    Sustituto de `requests.post` que devuelve (o levanta) en orden y guarda
    cada llamada: ``(url, json)``.
    """
    llamadas = []
    pendientes = list(respuestas)

    def _post(url, json=None, headers=None, timeout=None):
        llamadas.append((url, json, timeout))
        siguiente = pendientes.pop(0) if len(pendientes) > 1 else pendientes[0]
        if isinstance(siguiente, BaseException):
            raise siguiente
        return siguiente

    return _post, llamadas


TIMEOUT = requests.Timeout('read timed out')
