from odoo import fields, models, api


class AccountMove(models.Model):
    _inherit = "account.move"

    invoice_plan_id = fields.Many2one('sale.invoice.plan', string='Invoice Plan')

    def action_post(self):
        res = super(AccountMove, self).action_post()
        if self.state == 'posted' and self.invoice_plan_id:
            if self.invoice_plan_id.description:
                self.write({'name': f'{self.invoice_plan_id.description}' + '/' + self.name.split('/')[1] + '/' + self.name.split('/')[2]})
        return res