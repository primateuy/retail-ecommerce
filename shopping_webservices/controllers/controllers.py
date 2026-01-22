# -*- coding: utf-8 -*-
# from odoo import http


# class /mnt/extra-addons/shoppingWebservices(http.Controller):
#     @http.route('//mnt/extra-addons/shopping_webservices//mnt/extra-addons/shopping_webservices', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('//mnt/extra-addons/shopping_webservices//mnt/extra-addons/shopping_webservices/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('/mnt/extra-addons/shopping_webservices.listing', {
#             'root': '//mnt/extra-addons/shopping_webservices//mnt/extra-addons/shopping_webservices',
#             'objects': http.request.env['/mnt/extra-addons/shopping_webservices./mnt/extra-addons/shopping_webservices'].search([]),
#         })

#     @http.route('//mnt/extra-addons/shopping_webservices//mnt/extra-addons/shopping_webservices/objects/<model("/mnt/extra-addons/shopping_webservices./mnt/extra-addons/shopping_webservices"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('/mnt/extra-addons/shopping_webservices.object', {
#             'object': obj
#         })

