# -*- coding: utf-8 -*-

from odoo import api, fields, models , tools
import logging
_logger = logging.getLogger(__name__)

class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def create_from_ui(self, orders, draft=False):
        order_ids = super(PosOrder, self).create_from_ui(orders, draft)
        for order_id in order_ids:
            try:
                pos_order_id = self.browse(order_id['id'])
                if pos_order_id:
                    ref_order = [o['data'] for o in orders if o['data'].get('name') == pos_order_id.pos_reference]
                    check_info_list =[]
                    check_info_dict = {}
                    for order in ref_order:
                        for payment_id in order.get('statement_ids'):
                            check_number = payment_id[2].get('check_number')
                            owner_name = payment_id[2].get('owner_name')
                            bank_account = payment_id[2].get('bank_account')
                            bank_name = payment_id[2].get('bank_name')
                            if check_number:
                                check_info = {'check_number': check_number, 'check_owner': owner_name, 'check_bank_account': bank_account,'bank_id':int(bank_name)}
                                check_info_list.append(check_info)

                        for check in pos_order_id.payment_ids:
                            for check_list in check_info_list:
                                if check.payment_method_id.allow_check_info:
                                    if check.id not in check_info_dict and check_list not in check_info_dict.values():
                                        check_info_dict.update({
                                           check.id : check_list
                                        })

                        for check in pos_order_id.payment_ids:
                            for data,data_value in check_info_dict.items():
                                if check.id == data:
                                    check.write(data_value)


            except Exception as e:
                _logger.error('Error in point of sale validation: %s', tools.ustr(e))
        return order_ids