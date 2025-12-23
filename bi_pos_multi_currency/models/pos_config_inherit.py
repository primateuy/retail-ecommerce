# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.
from odoo import models, fields, api, _
from datetime import datetime, timedelta, date
from odoo.tools import float_is_zero
from odoo.exceptions import ValidationError, UserError
from odoo.addons.base.models.ir_qweb_fields import Markup, escape, nl2br


class PosConfigInherit(models.Model):
    _inherit = "pos.config"

    multi_currency = fields.Boolean(string="Enable Multi Currency")
    curr_conv = fields.Boolean(string="Enable Multi Currency Conversation")
    selected_currency = fields.Many2many("res.currency", "pos_multi_currency_rel",  string="pos")


    @api.constrains('pricelist_id', 'use_pricelist', 'available_pricelist_ids', 'journal_id', 'invoice_journal_id', 'payment_method_ids')
    def _check_currencies(self):
        for config in self:
            if config.use_pricelist and config.pricelist_id and config.pricelist_id not in config.available_pricelist_ids:
                raise ValidationError(_("The default pricelist must be included in the available pricelists."))

            # Check if the config's payment methods are compatible with its currency
            if not config.multi_currency:
                for pm in config.payment_method_ids:
                    if pm.journal_id and pm.journal_id.currency_id and pm.journal_id.currency_id != config.currency_id:
                        raise ValidationError(_("All payment methods must be in the same currency as the Sales Journal or the company currency if that is not set."))

            if config.use_pricelist and any(config.available_pricelist_ids.mapped(lambda pricelist: pricelist.currency_id != config.currency_id)):
                raise ValidationError(_("All available pricelists must be in the same currency as the company or"
                                        " as the Sales Journal set on this point of sale if you use"
                                        " the Accounting application."))
            if config.invoice_journal_id.currency_id and config.invoice_journal_id.currency_id != config.currency_id:
                raise ValidationError(_("The invoice journal must be in the same currency as the Sales Journal or the company currency if that is not set."))


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_multi_currency = fields.Boolean(related='pos_config_id.multi_currency',readonly=False)
    pos_curr_conv = fields.Boolean(related='pos_config_id.curr_conv',readonly=False)
    pos_selected_currency = fields.Many2many(related='pos_config_id.selected_currency', readonly=False)


class CurrencyInherit(models.Model):
    _inherit = "res.currency"

    rate_in_company_currency = fields.Float(compute='_compute_company_currency_rate', string='Company Currency Rate',
                                            digits=0)



    def _compute_company_currency_rate(self):
        company = self.env['res.company'].browse(self._context.get('company_id')) or self.env.company
        company_currency = company.currency_id
        for currency in self:
            price = currency.rate
            if company_currency.id != currency.id:
                new_rate = (price) / company_currency.rate
                price = round(new_rate, 6)
            else:
                price = 1
            currency.rate_in_company_currency = price

    @api.depends('rate_ids.rate')
    @api.depends_context('to_currency', 'date', 'company', 'company_id')
    def _compute_current_rate(self):
        date = self._context.get('date') or fields.Date.context_today(self)
        company = self.env['res.company'].browse(self._context.get('company_id')) or self.env.company
        company = company.root_id
        to_currency = self.browse(self.env.context.get('to_currency')) or company.currency_id
        # the subquery selects the last rate before 'date' for the given currency/company
        currency_rates = (self + to_currency)._get_rates(self.env.company, date)
        for currency in self:
            currency.rate = currency_rates.get(currency._origin.id) / currency_rates.get(to_currency.id)
            currency.inverse_rate = 1 / currency.rate
            if currency != company.currency_id:
                currency.rate_string = '1 %s = %.6f %s' % (to_currency.name, currency.rate, currency.name)
            else:
                currency.rate_string = ''



class ExchangeRate(models.Model):
    _name = "currency.rate"
    _description = "Exchange Rate"

    currency_id = fields.Many2one("res.currency", string="Currency")
    symbol = fields.Char(related="currency_id.symbol", string="currency symbol")
    date = fields.Datetime(string="current Date", default=datetime.today())
    rate = fields.Float(related="currency_id.rate", string="Exchange Rate")
    pos = fields.Many2one("pos.config")


class ExchangeRate(models.Model):
    _inherit = "pos.payment"

    account_currency = fields.Float("Amount currency")
    currency_name = fields.Char("currency")


class ExchangeRate(models.Model):
    _inherit = "account.bank.statement.line"

    account_currency = fields.Monetary("Amount currency")
    currency_name = fields.Char("Currency")


class PosOrder(models.Model):
    _inherit = "pos.order"


    @api.model
    def _payment_fields(self, order, ui_paymentline):
        fields = super(PosOrder, self)._payment_fields(order, ui_paymentline)
        if ui_paymentline.get('currency_amount',0) > 0:
            account_currency = ui_paymentline.get('currency_amount',0)
            if ui_paymentline.get('amount',0) < 0 and ui_paymentline.get('currency_amount',0) > 0 :
                account_currency = - account_currency
                fields.update({
                'account_currency': account_currency if account_currency != 0 else ui_paymentline.get('amount',0),
                'currency_name' : ui_paymentline['currency_name'] if ui_paymentline.get('currency_name') else order.pricelist_id.currency_id.name,
                })

        if ui_paymentline.get('currency_amount_pay',0) > 0:
            account_currency = ui_paymentline.get('currency_amount_pay',0)
            if ui_paymentline.get('amount',0) < 0 and ui_paymentline.get('currency_amount_pay',0) > 0 :
                account_currency = - account_currency
                fields.update({
                'account_currency': account_currency if account_currency != 0 else ui_paymentline.get('amount',0),
                'currency_name' : ui_paymentline['currency_name_pay'] if ui_paymentline.get('currency_name_pay') else order.pricelist_id.currency_id.name,
                })

        if ui_paymentline.get('currency_symbol_pay'):
            account_currency = ui_paymentline.get('currency_amount_pay',0)
            currency_id = self.env['res.currency'].sudo().search([('name','=',ui_paymentline.get('currency_name_pay'))])
            fields.update({
            'account_currency': account_currency if account_currency != 0 else  ui_paymentline.get('amount',0),
            'currency_name' : ui_paymentline['currency_name_pay'] if ui_paymentline.get('currency_name_pay') else order.pricelist_id.currency_id.name,
            'currency' : currency_id.id,
            })
        return fields

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
        prec_acc = order.currency_id.decimal_places

        order._clean_payment_lines()
        for payments in pos_order['statement_ids']:
            order.add_payment(self._payment_fields(order, payments[2]))

        order.amount_paid = sum(order.payment_ids.mapped('amount'))

        if not draft and not float_is_zero(pos_order['amount_return'], prec_acc):
            cash_payment_method = pos_session.payment_method_ids.filtered('is_cash_count')[:1]
            if not cash_payment_method:
                raise UserError(_("No cash statement found for this session. Unable to record returned cash."))


            return_amount = 0
            sc = order.currency_id
            if  pos_order.get('currency_amount') and pos_order.get('currency_symbol'):
                oc = self.env['res.currency'].search([('name','=',pos_order.get('currency_name',''))])
                if oc != sc:
                    return_amount = sc._convert(pos_order.get('amount_return',0), oc, order.company_id, order.date_order)


            return_payment_vals = {
                'name': _('return'),
                'pos_order_id': order.id,
                'amount': -pos_order['amount_return'],
                'payment_date': fields.Datetime.now(),
                'payment_method_id': cash_payment_method.id,
                'is_change': True,
                'account_currency': -return_amount or 0.0,
                'currency_name' : pos_order.get('currency_name',order.pricelist_id.currency_id.name),
            }
            order.add_payment(return_payment_vals)


class POSSession(models.Model):
    _inherit = 'pos.session'

    bi_start_balance = fields.Monetary(
        string="Starting Balance in Foreign Currency",currency_field='updated_currency_id',
        readonly=True)

    bi_end_balance = fields.Monetary(
        string="Ending Balance in Foreign Currency", currency_field='updated_currency_id',
        readonly=True)

    updated_currency_id = fields.Many2one('res.currency',
        string='Company Currency', store=True, precompute=True,
    )

    def update_closing_balance(self, session_id, end_balance):
        session = self.browse(session_id)
        session.update({'bi_end_balance': end_balance})

    def get_open_new_balance(self,new_start_balance,session_id,journal_id,session_currency):
        session = self.browse(session_id)
        difference = new_start_balance - self.bi_start_balance
        session.update({'bi_start_balance': difference, 'updated_currency_id':session_currency})
        session._post_statement_difference_custom(journal_id,difference, True)

    def action_pos_session_open(self):
        # we only open sessions that haven't already been opened
        for session in self.filtered(lambda session: session.state == 'opening_control'):
            values = {}
            if not session.start_at:
                values['start_at'] = fields.Datetime.now()
            if session.config_id.cash_control and not session.rescue:
                last_session = self.search([('config_id', '=', session.config_id.id), ('id', '!=', session.id)], limit=1)
                session.cash_register_balance_start = last_session.cash_register_balance_end_real  # defaults to 0 if lastsession is empty
                session.bi_start_balance = last_session.bi_end_balance  # defaults to 0 if lastsession is empty
            else:
                values['state'] = 'opened'
            session.write(values)
        return True

    def _post_statement_difference_custom(self, journal_id, amount, is_opening):
        if amount:
            if self.config_id.cash_control:
                st_line_vals = {
                    'journal_id': journal_id,
                    'amount': amount,
                    'date': self.statement_line_ids.sorted()[-1:].date or fields.Date.context_today(self),
                    'pos_session_id': self.id,
                }

            if amount < 0.0:
                if not self.cash_journal_id.loss_account_id:
                    raise UserError(
                        _('Please go on the %s journal and define a Loss Account. This account will be used to record cash difference.',
                          self.cash_journal_id.name))

                st_line_vals['payment_ref'] = _("Cash difference observed during the counting (Loss)") + (_(' - opening') if is_opening else _(' - closing'))
                if not is_opening:
                    st_line_vals['counterpart_account_id'] = self.cash_journal_id.loss_account_id.id
            else:
                # self.cash_register_difference  > 0.0
                if not self.cash_journal_id.profit_account_id:
                    raise UserError(
                        _('Please go on the %s journal and define a Profit Account. This account will be used to record cash difference.',
                          self.cash_journal_id.name))

                st_line_vals['payment_ref'] = _("Cash difference observed during the counting (Profit)") + (_(' - opening') if is_opening else _(' - closing'))
                if not is_opening:
                    st_line_vals['counterpart_account_id'] = self.cash_journal_id.profit_account_id.id

            self.env['account.bank.statement.line'].create(st_line_vals)

    def _loader_params_pos_session(self):
        result = super()._loader_params_pos_session()
        result['search_params']['fields'].extend(['bi_start_balance','bi_end_balance'])
        return result

    def _loader_params_pos_payment_method(self):
        result = super()._loader_params_pos_payment_method()
        result['search_params']['fields'].extend(['journal_id','currency_id'])
        return result

    def _pos_ui_models_to_load(self):
        result = super()._pos_ui_models_to_load()
        result += [
            'account.journal',
        ]
        return result

    def _loader_params_account_journal(self):
        return {
            'search_params': {
                'domain': [], 
                'fields': ['id','name','type','currency_id']
            }
        }

    def _get_pos_ui_account_journal(self, params):
        return self.env['account.journal'].search_read(**params['search_params'])

    def get_closing_control_data(self):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_("You don't have the access rights to get the point of sale closing control data."))
        self.ensure_one()
        orders = self._get_closed_orders()
        payments = orders.payment_ids.filtered(lambda p: p.payment_method_id.type != "pay_later")
        cash_payment_method_ids = self.payment_method_ids.filtered(lambda pm: pm.type == 'cash')
        default_cash_payment_method_id = cash_payment_method_ids[0] if cash_payment_method_ids else None
        total_default_cash_payment_amount = sum(payments.filtered(lambda p: p.payment_method_id == default_cash_payment_method_id).mapped('amount')) if default_cash_payment_method_id else 0
        other_payment_method_ids = self.payment_method_ids - default_cash_payment_method_id if default_cash_payment_method_id else self.payment_method_ids
        cash_in_count = 0
        cash_out_count = 0
        cash_in_out_list = []
        last_session = self.search([('config_id', '=', self.config_id.id), ('id', '!=', self.id)], limit=1)
        for cash_move in self.sudo().statement_line_ids.sorted('create_date'):
            if cash_move.amount > 0:
                cash_in_count += 1
                name = f'Cash in {cash_in_count}'
            else:
                cash_out_count += 1
                name = f'Cash out {cash_out_count}'

            cash_in_out_list.append({
                'name': cash_move.payment_ref if cash_move.payment_ref else name,
                'amount': cash_move.amount,
                'journal_id': cash_move.journal_id.id,
                'currency_id': cash_move.currency_id.id
            })

        payment_list = []
        for pm in other_payment_method_ids:
            check_data = sum(self.sudo().statement_line_ids.filtered(lambda p: p.journal_id.id == pm.journal_id.id).mapped('amount'))
            payment_in_forign_currency = sum(payments.filtered(lambda p: p.payment_method_id == pm).mapped('amount'))

            currency = self.env['res.currency'].browse(pm.currency_id.id)
            show_combine_qty = check_data + payment_in_forign_currency
            vals = {
                    'name': pm.name,
                    'amount': show_combine_qty,
                    'number': len(orders.payment_ids.filtered(lambda p: p.payment_method_id == pm)),
                    'id': pm.id,
                    'type': pm.type,
                    'journal_id': pm.journal_id.id,
                    'currency_id': currency.symbol,
                    'payment_in_amount': payment_in_forign_currency
                }
            payment_list.append(vals)

        return {
            'orders_details': {
                'quantity': len(orders),
                'amount': sum(orders.mapped('amount_total'))
            },
            'opening_notes': self.opening_notes,
            'default_cash_details': {
                'name': default_cash_payment_method_id.name,
                'amount': last_session.cash_register_balance_end_real
                         + total_default_cash_payment_amount
                          + sum(self.sudo().statement_line_ids.mapped('amount')),
                'opening': last_session.cash_register_balance_end_real,
                'pay_opening': last_session.bi_end_balance,
                'payment_amount': total_default_cash_payment_amount,
                'moves': cash_in_out_list,
                'id': default_cash_payment_method_id.id,
                'currency_id': default_cash_payment_method_id.currency_id.id,
            } if default_cash_payment_method_id else None,
            'other_payment_methods': [{
                'name': pm.name,
                'amount': sum(orders.payment_ids.filtered(lambda p: p.payment_method_id == pm).mapped('amount')),
                'number': len(orders.payment_ids.filtered(lambda p: p.payment_method_id == pm)),
                'id': pm.id,
                'type': pm.type,
                'journal_id': pm.journal_id.id,
                'currency_id': pm.currency_id.id,
                'currency_symbol': self.env['res.currency'].browse(pm.currency_id.id).symbol
            } for pm in other_payment_method_ids],
            'pay_amount': [{
                'name': pl.get('name'),
                'amount': pl.get('amount'),
                'id': pl.get('id'),
                'type': pl.get('type'),
                'journal_id': pl.get('journal_id'),
                'currency_id': pl.get('currency_id'),
                'payment_in_amount': pl.get('payment_in_amount'),
            } for pl in payment_list],
            'is_manager': self.user_has_groups("point_of_sale.group_pos_manager"),
            'amount_authorized_diff': self.config_id.amount_authorized_diff if self.config_id.set_maximum_difference else None
        }
