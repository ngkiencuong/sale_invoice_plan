# Copyright 2019 Ecosoft Co., Ltd (http://ecosoft.co.th/)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html)
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_round

import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    invoice_plan_ids = fields.Many2many(
        comodel_name="sale.invoice.plan",
        string="Inovice Plan",
        copy=False,
    )
    use_invoice_plan = fields.Boolean(
        default=False,
        copy=False,
    )
    ip_invoice_plan = fields.Boolean(
        string="Invoice Plan In Process",
        compute="_compute_ip_invoice_plan",
        help="At least one invoice plan line pending to create invoice",
    )

    @api.onchange('invoice_plan_ids', 'invoice_plan_ids.absolute_value', 'invoice_plan_ids.percent')
    def onchange_percent(self):
        total = self.amount_total
        sum_percent = sum(self.invoice_plan_ids.mapped('percent'))
        if self.invoice_plan_ids:
            if self.invoice_plan_ids[0].choose_type == 'percent':
                last_line = self.invoice_plan_ids[-1]
                if sum_percent == 100:
                    last_line.percent = 0
                else:
                    last_line.percent = last_line.percent + 100 - sum_percent
                for line in self.invoice_plan_ids:
                    line.absolute_value = line.percent / 100 * total
            else:
                sum_amount = sum(self.invoice_plan_ids.mapped('absolute_value'))
                last_line = self.invoice_plan_ids[-1]
                if sum_amount == total:
                    last_line.absolute_value = 0
                else:
                    last_line.absolute_value = (last_line.absolute_value + self.amount_total - sum_amount)

                for line in self.invoice_plan_ids:
                    line.percent = line.absolute_value / total * 100

    def _compute_ip_invoice_plan(self):
        for rec in self:
            has_invoice_plan = rec.use_invoice_plan and rec.invoice_plan_ids
            to_invoice = rec.invoice_plan_ids.filtered(lambda l: not l.invoiced)
            if rec.state == "sale" and has_invoice_plan and to_invoice:
                if rec.invoice_status == "to invoice" or (
                        rec.invoice_status == "no"
                        and "advance" in to_invoice.mapped("invoice_type")
                ):
                    rec.ip_invoice_plan = True
                    continue
            rec.ip_invoice_plan = False

    @api.constrains("state")
    def _check_invoice_plan(self):
        for rec in self:
            if rec.state != "draft":
                if rec.invoice_plan_ids.filtered(lambda l: not l.percent):
                    raise ValidationError(
                        _("Please fill percentage for all invoice plan lines")
                    )

    def action_confirm(self):
        if self.filtered(lambda r: r.use_invoice_plan and not r.invoice_plan_ids):
            raise UserError(_("Use Invoice Plan selected, but no plan created"))
        return super().action_confirm()

    def create_invoice_plan(
            self, num_installment, installment_date, interval, interval_type, advance, choose_type
    ):
        self.ensure_one()
        self.invoice_plan_ids.unlink()
        invoice_plans = []
        Decimal = self.env["decimal.precision"]
        prec = Decimal.precision_get("Product Unit of Measure")
        percent = float_round(1.0 / num_installment * 100, prec)
        percent_last = 100 - (percent * (num_installment - 1))
        # Advance
        if advance:
            vals = {
                "sale_id": self.id,
                "installment": 0,
                "plan_date": installment_date,
                "invoice_type": "advance",
                "percent": 0.0,
                "choose_type": choose_type
            }
            if choose_type == 'absolute':
                vals.update({
                    "absolute_value": self.amount_total / num_installment
                })
            invoice_plans.append((0, 0, vals))
            installment_date = self._next_date(
                installment_date, interval, interval_type
            )
        # Normal
        for i in range(num_installment):
            this_installment = i + 1
            if num_installment == this_installment:
                percent = percent_last
            vals = {
                "sale_id": self.id,
                "installment": this_installment,
                "plan_date": installment_date,
                "invoice_type": "installment",
                "percent": percent,
                "choose_type": choose_type
            }
            if choose_type == 'absolute':
                vals.update({
                    "absolute_value": self.amount_total / num_installment
                })
            invoice_plans.append((0, 0, vals))
            installment_date = self._next_date(
                installment_date, interval, interval_type
            )
        self.write({"invoice_plan_ids": invoice_plans})
        return True

    def remove_invoice_plan(self):
        self.ensure_one()
        self.invoice_plan_ids.unlink()
        return True

    @api.model
    def _next_date(self, installment_date, interval, interval_type):
        installment_date = fields.Date.from_string(installment_date)
        if interval_type == "month":
            next_date = installment_date + relativedelta(months=+interval)
        elif interval_type == "year":
            next_date = installment_date + relativedelta(years=+interval)
        else:
            next_date = installment_date + relativedelta(days=+interval)
        next_date = fields.Date.to_string(next_date)
        return next_date

    def _create_invoices(self, grouped=False, final=False, date=None):
        moves = super()._create_invoices(grouped=grouped, final=final, date=date)
        invoice_plan_id = self._context.get("invoice_plan_id")
        if invoice_plan_id:
            plan = self.env["sale.invoice.plan"].browse(invoice_plan_id)
            moves.ensure_one()  # Expect 1 invoice for 1 invoice plan
            plan._compute_new_invoice_quantity(moves[0])
            moves.invoice_date = plan.plan_date
            moves._onchange_invoice_date()
            plan.invoice_move_ids += moves
            moves.invoice_plan_id = plan.id
        return moves
