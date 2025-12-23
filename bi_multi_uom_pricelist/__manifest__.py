# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.

{
    "name" : "Product UOM based Pricelist",
    "version" : "17.0.0.0",
    "category" : "Sales",
    'summary': 'Apps for UOM based pricelist apply UOM on pricelist unit of measure based pricelist apply different uom on price-list multiple uom on price-list for multiple uom based pricelist on multi uom pricelist apply pricelist for product uom based pricelist',
    "description": """
    
   Multi UOM Pricelist in odoo apps,
   pricelist in odoo apps,
   uom pricelist in odoo apps,
   multi pricelist in odoo apps,
   sales pricelist in odoo apps,
   invoice pricelist in odoo apps,


    
    """,
    "author": "BrowseInfo",
    "website": "https://www.browseinfo.com/demo-request?app=bi_multi_uom_pricelist&version=17&edition=Community",
    "price": 29,
    "currency": 'EUR',
    "depends" : ['base','sale','stock','sale_management'],
    "data": [
        'views/product_template_inherited.xml',
        'views/product_pricelist.xml'
    ],
    'qweb': [
    ],
    "license":'OPL-1',
    "auto_install": False,
    "installable": True,
    'live_test_url': 'https://www.browseinfo.com/demo-request?app=bi_multi_uom_pricelist&version=17&edition=Community', 
    "images":["static/description/Banner.gif"],
}
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
