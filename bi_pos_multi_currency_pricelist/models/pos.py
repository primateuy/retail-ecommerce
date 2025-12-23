# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero, float_compare, DEFAULT_SERVER_DATETIME_FORMAT
from datetime import datetime, timedelta
from functools import partial
import pytz


class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    currency_convert = fields.Float('Currency',related='currency_id.rate')


class POSConfig(models.Model):
    
    _inherit = 'pos.config'
        
    @api.constrains('pricelist_id', 'use_pricelist', 'available_pricelist_ids', 'journal_id', 'invoice_journal_id', 'payment_method_ids')
    def _check_currencies(self):
        for config in self:
            if config.use_pricelist and config.pricelist_id not in config.available_pricelist_ids:
                raise ValidationError(_("The default pricelist must be included in the available pricelists."))

        if self.invoice_journal_id.currency_id and self.invoice_journal_id.currency_id != self.currency_id:
            raise ValidationError(_("The invoice journal must be in the same currency as the Sales Journal or the company currency if that is not set."))

        if any(
            self.payment_method_ids\
                .filtered(lambda pm: pm.is_cash_count)\
                .mapped(lambda pm: self.currency_id not in (self.company_id.currency_id | pm.journal_id.currency_id))
        ):
            raise ValidationError(_("All payment methods must be in the same currency as the Sales Journal or the company currency if that is not set."))

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'


    @api.depends('pos_use_pricelist', 'pos_config_id', 'pos_journal_id')
    def _compute_pos_pricelist_id(self):
        for res_config in self:
            currency_id = res_config.pos_journal_id.currency_id.id if res_config.pos_journal_id.currency_id else res_config.pos_config_id.company_id.currency_id.id
            pricelists_in_current_currency = self.env['product.pricelist'].search([
                *self.env['product.pricelist']._check_company_domain(res_config.pos_config_id.company_id)])
            if not res_config.pos_use_pricelist:
                res_config.pos_pricelist_id = False
                res_config.pos_available_pricelist_ids = res_config.pos_config_id.available_pricelist_ids
            else:
                if any([p.currency_id.id != currency_id for p in res_config.pos_available_pricelist_ids]):
                    res_config.pos_available_pricelist_ids = pricelists_in_current_currency
                    res_config.pos_pricelist_id = pricelists_in_current_currency[:1]
                else:
                    res_config.pos_available_pricelist_ids = res_config.pos_config_id.available_pricelist_ids
                    res_config.pos_pricelist_id = res_config.pos_config_id.pricelist_id



class PosPayment(models.Model):
    _inherit = "pos.payment"

    amount_currency = fields.Float(string="Currency Amount")
    currency = fields.Many2one("res.currency", string="Currency")

    def _create_payment_moves(self, is_reverse=False):
        result = self.env['account.move']
        for payment in self:
            order = payment.pos_order_id
            payment_method = payment.payment_method_id
            if payment_method.type == 'pay_later' or float_is_zero(payment.amount, precision_rounding=order.currency_id.rounding):
                continue
            accounting_partner = self.env["res.partner"]._find_accounting_partner(payment.partner_id)
            pos_session = order.session_id
            journal = pos_session.config_id.journal_id

            if not payment.currency:
                payment_move = self.env['account.move'].with_context(default_journal_id=journal.id).create({
                    'journal_id': journal.id,
                    'date': fields.Date.context_today(order, order.date_order),
                    'ref': _('Invoice payment for %s (%s) using %s', order.name, order.account_move.name, payment_method.name),
                    'pos_payment_ids': payment.ids,
                })
                result |= payment_move
                payment_move.update({'bi_amount_in_currency': payment_move.pos_payment_ids.account_currency,
                'currency_id':payment_move.pos_payment_ids.payment_method_id.currency_id.id})
                payment.write({'account_move_id': payment_move.id})
                amounts = pos_session._update_amounts({'amount': 0, 'amount_converted': 0}, {'amount': payment.amount}, payment.payment_date)
                credit_line_vals = pos_session._credit_amounts({
                    'account_id': accounting_partner.with_company(order.company_id).property_account_receivable_id.id,  # The field being company dependant, we need to make sure the right value is received.
                    'partner_id': accounting_partner.id,
                    'move_id': payment_move.id,
                }, amounts['amount'], amounts['amount_converted'])
                is_split_transaction = payment.payment_method_id.split_transactions
                if is_split_transaction and is_reverse:
                    reversed_move_receivable_account_id = accounting_partner.with_company(order.company_id).property_account_receivable_id.id
                elif is_reverse:
                    reversed_move_receivable_account_id = payment.payment_method_id.receivable_account_id.id or self.company_id.account_default_pos_receivable_account_id.id
                else:
                    reversed_move_receivable_account_id = self.company_id.account_default_pos_receivable_account_id.id
                debit_line_vals = pos_session._debit_amounts({
                    'account_id': reversed_move_receivable_account_id,
                    'move_id': payment_move.id,
                    'partner_id': accounting_partner.id if is_split_transaction and is_reverse else False,
                }, amounts['amount'], amounts['amount_converted'])
                self.env['account.move.line'].create([credit_line_vals, debit_line_vals])
                payment_move._post()
            else:
                payment_move = self.env['account.move'].with_context(default_journal_id=journal.id).create({
                    'journal_id': journal.id,
                    'currency_id': payment.currency.id,
                    'date': fields.Date.context_today(order, order.date_order),
                    'ref': _('Invoice payment for %s (%s) using %s', order.name, order.account_move.name, payment_method.name),
                    'pos_payment_ids': payment.ids,
                })
                result |= payment_move
                payment_move.update({'bi_amount_in_currency': payment_move.pos_payment_ids.account_currency,
                'currency_id':payment_move.pos_payment_ids.payment_method_id.currency_id.id})
                payment.write({'account_move_id': payment_move.id})
                amounts = pos_session._update_amounts({'amount': 0, 'amount_converted': 0}, {'amount': payment.amount}, payment.payment_date)
                credit_line_vals = pos_session._credit_amounts({
                    'account_id': accounting_partner.with_company(order.company_id).property_account_receivable_id.id,  # The field being company dependant, we need to make sure the right value is received.
                    'partner_id': accounting_partner.id,
                    'move_id': payment_move.id,
                    'currency_id':payment.currency.id,
                }, amounts['amount'], amounts['amount_converted'])
                is_split_transaction = payment.payment_method_id.split_transactions
                if is_split_transaction and is_reverse:
                    reversed_move_receivable_account_id = accounting_partner.with_company(order.company_id).property_account_receivable_id.id
                elif is_reverse:
                    reversed_move_receivable_account_id = payment.payment_method_id.receivable_account_id.id or self.company_id.account_default_pos_receivable_account_id.id
                else:
                    reversed_move_receivable_account_id = self.company_id.account_default_pos_receivable_account_id.id
                debit_line_vals = pos_session._debit_amounts({
                    'account_id': reversed_move_receivable_account_id,
                    'move_id': payment_move.id,
                    'partner_id': accounting_partner.id if is_split_transaction and is_reverse else False,
                    'currency_id':payment.currency.id,
                }, amounts['amount'], amounts['amount_converted'])
                self.env['account.move.line'].create([credit_line_vals, debit_line_vals])
                payment_move._post()
        return result

class PosPaymentMethod(models.Model):

    _inherit = "pos.payment.method"

    currency_id = fields.Many2one("res.currency", 'Currency',compute='_compute_currency')

    def _compute_currency(self):
        for pm in self:
            pm.currency_id = pm.company_id.currency_id.id
            if pm.journal_id and pm.journal_id.currency_id:
                pm.currency_id = pm.journal_id.currency_id.id


class POSSession(models.Model):
    _inherit = 'pos.session'

    def _pos_ui_models_to_load(self):
        result = super()._pos_ui_models_to_load()
        result.extend(['product.pricelist.item'])
        return result

    def _loader_params_product_pricelist_item(self):
        return {
            'search_params': {
                'domain': [('pricelist_id', 'in', self.config_id.available_pricelist_ids.ids)],
                'fields': [],
            }
        }

    def _get_pos_ui_product_pricelist_item(self, params):
        return self.env['product.pricelist.item'].search_read(**params['search_params'])


    def load_pos_data(self):
        loaded_data = {}
        self = self.with_context(loaded_data=loaded_data)
        for model in self._pos_ui_models_to_load():
            loaded_data[model] = self._load_model(model)
        self._pos_data_process(loaded_data)        
        users_data = self._get_pos_ui_pos_res_currency(self._loader_params_pos_res_currency())
        loaded_data['currencies'] = users_data
        return loaded_data

    def _loader_params_pos_res_currency(self):
        return {
            'search_params': {
                'domain': [],
                'fields': ['name','symbol','position','rounding','rate','decimal_places','currency_convert'],
            },
        }

    def _get_pos_ui_pos_res_currency(self, params):
        currencies = self.env['res.currency'].search_read(**params['search_params'])
        return currencies


    def _loader_params_pos_payment_method(self):
        result = super()._loader_params_pos_payment_method()
        result['search_params']['fields'].append('currency_id')
        return result

    def _loader_params_product_pricelist(self):
        result = super()._loader_params_product_pricelist()
        result['search_params']['fields'].extend(['currency_id','currency_convert'])
        
        return result


class POSOrder(models.Model):

    _inherit = "pos.order"

    amount_total = fields.Float(string='Total', digits=0, required=True)
    amount_paid = fields.Float(string='Paid', digits=0, required=True)


    @api.model
    def _get_invoice_lines_values(self, line_values, pos_order_line):
        payment_date = fields.Datetime.now() if self.session_id.state == 'closed' else self.date_order
        price_unit_comp_curr = self.currency_id._convert(pos_order_line.price_unit, self.pricelist_id.currency_id, self.company_id, payment_date,round=False)
        return {
            'product_id': line_values['product'].id,
            'quantity': line_values['quantity'],
            'discount': line_values['discount'],
            'price_unit': price_unit_comp_curr,
            'name': line_values['name'],
            'tax_ids': [(6, 0, line_values['taxes'].ids)],
            'product_uom_id': line_values['uom'].id,
        }

    def _is_pos_order_paid(self):
        if (abs(self.amount_total - self.amount_paid) < 0.02):
            self.write({'amount_total': self.amount_paid})
            return True
        else:
            return False

    @api.model
    def _payment_fields(self, order, ui_paymentline):
        fields_data = super(POSOrder, self)._payment_fields(order, ui_paymentline)

        payment_total = []
        company_id = self.env.user.company_id
        payment_date = ui_paymentline['name']
        payment_date = fields.Date.context_today(self, fields.Datetime.from_string(payment_date))
        price_unit_foreign_curr = 0.0

        price_unit_comp_curr = ui_paymentline['amount'] or 0.0
        currency_id = False

        if order.pricelist_id.currency_id.id != order.currency_id.id:
            # Convert
            price_unit_foreign_curr = ui_paymentline['amount']
            price_unit_comp_curr = order.pricelist_id.currency_id._convert(price_unit_foreign_curr, order.currency_id, order.company_id, payment_date,round=False)
            currency_id = order.pricelist_id.currency_id.id
            price_unit_comp_curr = price_unit_comp_curr

        fields_data.update({
            'amount_currency': price_unit_foreign_curr,
            # 'currency': currency_id,
            'amount': price_unit_comp_curr or 0.0,
            'payment_date': ui_paymentline['name'],
            'payment_method_id': ui_paymentline['payment_method_id'],
            'card_type': ui_paymentline.get('card_type'),
            'cardholder_name': ui_paymentline.get('cardholder_name'),
            'transaction_id': ui_paymentline.get('transaction_id'),
            'payment_status': ui_paymentline.get('payment_status'),
            'pos_order_id': order.id,
        })

        return fields_data

    def _prepare_invoice_vals(self):
        self.ensure_one()
        timezone = pytz.timezone(self._context.get('tz') or self.env.user.tz or 'UTC')
        invoice_date = fields.Datetime.now() if self.session_id.state == 'closed' else self.date_order
        pos_refunded_invoice_ids = []
        for orderline in self.lines:
            if orderline.refunded_orderline_id and orderline.refunded_orderline_id.order_id.account_move:
                pos_refunded_invoice_ids.append(orderline.refunded_orderline_id.order_id.account_move.id)
        vals = {
            'invoice_origin': self.name,
            'pos_refunded_invoice_ids': pos_refunded_invoice_ids,
            'journal_id': self.session_id.config_id.invoice_journal_id.id,
            'move_type': 'out_invoice' if self.amount_total >= 0 else 'out_refund',
            'ref': self.name,
            'partner_id': self.partner_id.address_get(['invoice'])['invoice'],
            'partner_bank_id': self._get_partner_bank_id(),
            'currency_id': self.pricelist_id.currency_id.id if self.pricelist_id else self.currency_id.id,
            'invoice_user_id': self.user_id.id,
            'invoice_date': invoice_date.astimezone(timezone).date(),
            'fiscal_position_id': self.fiscal_position_id.id,
            'invoice_line_ids': self._prepare_invoice_lines(),
            'invoice_payment_term_id': self.partner_id.property_payment_term_id.id or False,
            'invoice_cash_rounding_id': self.config_id.rounding_method.id
            if self.config_id.cash_rounding and (not self.config_id.only_round_cash_method or any(p.payment_method_id.is_cash_count for p in self.payment_ids))
            else False
        }
        if self.refunded_order_ids.account_move:
            vals['ref'] = _('Reversal of: %s', self.refunded_order_ids.account_move.name)
            vals['reversed_entry_id'] = self.refunded_order_ids.account_move.id
        if self.note:
            vals.update({'narration': self.note})
        return vals

    @api.model
    def _order_fields(self, ui_order):
        amount_total = []
        amt_total = ui_order['amount_total']
        amt_paid = ui_order['amount_paid']

        if ui_order['lines']:
            pos_session = self.env['pos.session'].browse(ui_order.get('pos_session_id'))
            pricelist_id = self.env['product.pricelist'].browse(ui_order.get('pricelist_id'))
            payment_date = fields.Date.today()
            if pricelist_id :
                if pos_session.currency_id.id != pricelist_id.currency_id.id:
                    for line in ui_order['lines']:
                        price_unit_foreign_curr = line[2].get('price_unit') or 0.0
                        price_unit_comp_curr = pricelist_id.currency_id._convert(price_unit_foreign_curr, pos_session.currency_id, pos_session.company_id, payment_date,round=False)
                        price_subtotal_foreign_curr = line[2].get('price_subtotal') or 0.0
                        price_subtotal_comp_curr = pricelist_id.currency_id._convert(price_subtotal_foreign_curr, pos_session.currency_id, pos_session.company_id, payment_date,round=False)
                        price_subtotal_incl_foreign_curr = line[2].get('price_subtotal_incl') or 0.0
                        price_subtotal_incl_comp_curr = pricelist_id.currency_id._convert(price_subtotal_incl_foreign_curr, pos_session.currency_id, pos_session.company_id, payment_date,round=False)
                        line[2].update({
                            'price_unit':price_unit_comp_curr,
                            'price_subtotal':price_subtotal_comp_curr,
                            'price_subtotal_incl':price_subtotal_incl_comp_curr,
                            })
                        amount_total.append(price_subtotal_incl_comp_curr)
                    amount_total_foreign_curr = ui_order.get('amount_total')
                    amount_total_comp_curr = pricelist_id.currency_id._convert(amount_total_foreign_curr, pos_session.currency_id, pos_session.company_id, payment_date,round=False)
                    ui_order.update({'amount_total': sum(amount_total)})
                    amt_total = sum(amount_total)
                    amt_paid =  sum(amount_total)

                process_line = partial(self.env['pos.order.line']._order_line_fields, session_id=ui_order['pos_session_id'])
                return {
                    'user_id':      ui_order['user_id'] or False,
                    'session_id':   ui_order['pos_session_id'],
                    'lines':        [process_line(l) for l in ui_order['lines']] if ui_order['lines'] else False,
                    'pos_reference': ui_order['name'],
                    'sequence_number': ui_order['sequence_number'],
                    'partner_id':   ui_order['partner_id'] or False,
                    # 'date_order':   ui_order['creation_date'].replace('T', ' ')[:19],
                    'fiscal_position_id': ui_order['fiscal_position_id'],
                    'pricelist_id': ui_order['pricelist_id'],
                    'amount_paid':  amt_paid,
                    'amount_total':  amt_total,
                    'amount_tax':  ui_order['amount_tax'],
                    'amount_return':  ui_order['amount_return'],
                    'company_id': self.env['pos.session'].browse(ui_order['pos_session_id']).company_id.id,
                    'to_invoice': ui_order['to_invoice'] if "to_invoice" in ui_order else False,
                    'is_tipped': ui_order.get('is_tipped', False),
                    'tip_amount': ui_order.get('tip_amount', 0),
                }
            else:
                return super(POSOrder, self)._order_fields(ui_order)


    def _process_payment_lines(self, pos_order, order, pos_session, draft):
        """Create account.bank.statement.lines from the dictionary given to the parent function.

        If the payment_line is an updated version of an existing one, the existing payment_line will first be
        removed before making a new one.
        :param pos_order: dictionary representing the order.
        :type pos_order: dict.
        :param order: Order object the payment lines should belong to.
        :type order: pos.order
        :param pos_session: PoS session the order was created in.
        :type pos_session: pos.session
        :param draft: Indicate that the pos_order is not validated yet.
        :type draft: bool.
        """
        prec_acc = order.pricelist_id.currency_id.decimal_places
        pricelist_id = self.env['product.pricelist'].browse(pos_order.get('pricelist_id'))
        order_bank_statement_lines= self.env['pos.payment'].search([('pos_order_id', '=', order.id)])
        order_bank_statement_lines.unlink()
        payment_date = fields.Date.today()
        for payments in pos_order['statement_ids']:
            if not float_is_zero(payments[2]['amount'], precision_digits=prec_acc):
                order.add_payment(self._payment_fields(order, payments[2]))

        order.amount_paid = sum(order.payment_ids.mapped('amount'))

        currency_id = False
        amt_currncy = 0.0
        price_subtotal_comp_curr = pos_order['amount_return']
        if pos_session.currency_id.id != pricelist_id.currency_id.id:
            price_subtotal_comp_curr = pricelist_id.currency_id._convert(pos_order['amount_return'], pos_session.currency_id, pos_session.company_id, payment_date,round=False)
            currency_id = order.pricelist_id.currency_id.id
            amt_currncy = -pos_order['amount_return']
        if not draft and not float_is_zero(pos_order['amount_return'], prec_acc):
            cash_payment_method = pos_session.payment_method_ids.filtered('is_cash_count')[:1]
            if not cash_payment_method:
                raise UserError(_("No cash statement found for this session. Unable to record returned cash."))
            return_payment_vals = {
                'name': _('return'),
                'pos_order_id': order.id,
                'amount_currency': amt_currncy,
                'currency': currency_id,
                'amount': -price_subtotal_comp_curr,
                'payment_date': fields.Datetime.now(),
                'payment_method_id': cash_payment_method.id,
                'is_change': True,
            }
            order.add_payment(return_payment_vals)


class currency(models.Model):
    _inherit = 'res.currency'

    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.user.company_id)
    currency_convert = fields.Float('Currency', compute="_onchange_currency")

    @api.depends('company_id')
    def _onchange_currency(self):
        res_currency = self.env['res.currency'].search([])
        company_currency = self.env.user.company_id.currency_id
        for i in self:
            if i.id == company_currency.id:
                i.currency_convert = 1
            else:
                rate = (round(i.rate,6) / company_currency.rate)
                i.currency_convert = rate

# class AccountInvoiceLine(models.Model):
#     _inherit = 'account.move.line'

#     @api.depends('currency_rate', 'balance')
#     def _compute_amount_currency(self):
#         for line in self:
#             if line.amount_currency is False:
#                 line.amount_currency = line.currency_id.round(line.balance * line.currency_rate)
#             if line.currency_id == line.company_id.currency_id:
#                 line.amount_currency = line.balance
#             if line.currency_id != line.company_id.currency_id:
#                 line.amount_currency = line.currency_id.round(line.balance * line.currency_rate)