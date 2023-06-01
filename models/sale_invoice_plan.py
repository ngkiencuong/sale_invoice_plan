from odoo import _, fields, models, api
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare

import logging

_logger = logging.getLogger(__name__)


class SaleInvoicePlan(models.Model):
    _name = "sale.invoice.plan"
    _description = "Invoice Planning Detail"
    _order = "installment"

    sale_id = fields.Many2one(
        comodel_name="sale.order",
        string="Sales Order",
        readonly=True
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer",
        related="sale_id.partner_id",
        store=True,
        index=True,
    )
    state = fields.Selection(
        string="Status",
        related="sale_id.state",
        store=True,
        index=True,
    )
    installment = fields.Integer()
    plan_date = fields.Date(required=True)
    invoice_type = fields.Selection(
        [("advance", "Advance"), ("installment", "Installment")],
        string="Type",
        required=True,
        default="installment",
    )
    last = fields.Boolean(
        string="Last Installment",
        compute="_compute_last",
        help="Last installment will create invoice use remaining amount",
    )
    percent = fields.Float(
        help="This percent will be used to calculate new quantity",
    )

    absolute_value = fields.Float(
        string="Absolute Value",
        compute="_compute_absolute_value",
        store=True,
        readonly=False

    )
    invoice_move_ids = fields.Many2many(
        "account.move",
        relation="sale_invoice_plan_invoice_rel",
        column1="plan_id",
        column2="move_id",
        string="Invoices",
        readonly=True,
    )
    to_invoice = fields.Boolean(
        string="Next Invoice",
        compute="_compute_to_invoice",
        help="If this line is ready to create new invoice",
    )
    invoiced = fields.Boolean(
        string="Invoice Created",
        compute="_compute_invoiced",
        help="If this line already invoiced",
    )

    description = fields.Char(string='Description')
    choose_type = fields.Selection(
        [("absolute", "Absolute Value"), ("percent", "Percent")],
        default="percent",
        required=True,
    )

    _sql_constraint = [
        (
            "unique_instalment",
            "UNIQUE (sale_id, installment)",
            "Installment must be unique on invoice plan",
        )
    ]

    # @api.onchange('absolute_value')
    # def on_change_absolute_value(self):
    #     for plan in self:
    #         total = plan.sale_id.amount_total
    #         plan.percent = plan.absolute_value / total * 100
    #         _logger.info(f'Absolute value {plan.absolute_value}, percent {plan.percent}')
    @api.depends("percent", "sale_id.amount_total", "absolute_value")
    def _compute_absolute_value(self):
        for record in self:
            if record.choose_type == 'percent':
                record.absolute_value = record.sale_id.amount_total * record.percent / 100
                get_order = self.env['sale.order'].search([('id', '=', record.sale_id.id)])

    @api.constrains("absolute_value")
    def _check_percent(self):
        for record in self:
            record.sudo().write({'percent': record.absolute_value / record.sale_id.amount_total * 100})

    # @api.onchange('percent')
    # def on_change_percent(self):
    #     for plan in self:
    #         total = plan.sale_id.amount_total
    #         plan.absolute_value = plan.percent / 100 * total
    #         _logger.info(f'Percent {plan.percent}, absolute value {plan.absolute_value}')

    def _compute_to_invoice(self):
        """If any invoice is in draft/open/paid do not allow to create inv.
        Only if previous to_invoice is False, it is eligible to_invoice.
        """
        for rec in self:
            rec.to_invoice = False
        for rec in self.sorted("installment"):
            if rec.state != "sale":  # Not confirmed, no to_invoice
                continue
            if not rec.invoiced:
                rec.to_invoice = True
                break

    def _compute_invoiced(self):
        for rec in self:
            invoiced = rec.invoice_move_ids.filtered(
                lambda l: l.state in ("draft", "posted")
            )
            rec.invoiced = invoiced and True or False

    def _compute_last(self):
        for rec in self:
            last = rec.sale_id.invoice_plan_ids.mapped("installment")
            if last:
                last = max(last)
                rec.last = rec.installment == last
            else:
                rec.last = False

    def _compute_new_invoice_quantity(self, invoice_move):
        self.ensure_one()
        if self.last:  # For last install, let the system do the calc.
            return
        percent = self.percent
        move = invoice_move.with_context(**{"check_move_validity": False})
        for line in move.invoice_line_ids:
            if not len(line.sale_line_ids) >= 0:
                raise UserError(_("No matched order line for invoice line"))
            order_line = fields.first(line.sale_line_ids)
            if order_line.is_downpayment:  # based on 1 unit
                line.write({"quantity": -percent / 100})
            else:
                plan_qty = order_line.product_uom_qty * (percent / 100)
                prec = order_line.product_uom.rounding
                if float_compare(plan_qty, line.quantity, prec) == 1:
                    raise ValidationError(
                        _(
                            "Plan quantity: %(plan_qty)s, exceed invoiceable quantity: "
                            "%(invoiceable_qty)s"
                            "\nProduct should be delivered before invoice"
                        )
                        % {"plan_qty": plan_qty, "invoiceable_qty": line.quantity}
                    )
                line.write({"quantity": plan_qty})
        # Call this method to recompute dr/cr lines
        move.line_ids.filtered("exclude_from_invoice_tab").unlink()
        move._move_autocomplete_invoice_lines_values()
