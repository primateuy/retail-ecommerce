# -*- coding: utf-8 -*-

# from odoo.http import Root, HttpRequest, JsonRequest

from . import api_controllers


# class Rooting(Root):
#
#     def get_request(self, httprequest):
#         # deduce type of request
#         endpoints = [
#             '/productos',
#             '/stockporsku',
#             '/permitecancelar',
#             '/orden',
#         ]
#         for endpint in endpoints:
#             if endpint in httprequest.base_url:
#                 return HttpRequest(httprequest)
#
#         # deduce type of request
#         if httprequest.mimetype in ("application/json", "application/json-rpc"):
#             return JsonRequest(httprequest)
#         else:
#             return HttpRequest(httprequest)
#
#
# Root.get_request = Rooting.get_request