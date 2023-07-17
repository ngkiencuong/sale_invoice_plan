from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class SequenceMixin(models.AbstractModel):
    _inherit = "sequence.mixin"


    def _get_last_sequence(self, relaxed=False, with_prefix=None, lock=True):
        """Retrieve the previous sequence.

        This is done by taking the number with the greatest alphabetical value within
        the domain of _get_last_sequence_domain. This means that the prefix has a
        huge importance.
        For instance, if you have INV/2019/0001 and INV/2019/0002, when you rename the
        last one to FACT/2019/0001, one might expect the next number to be
        FACT/2019/0002 but it will be INV/2019/0002 (again) because INV > FACT.
        Therefore, changing the prefix might not be convenient during a period, and
        would only work when the numbering makes a new start (domain returns by
        _get_last_sequence_domain is [], i.e: a new year).

        :param field_name: the field that contains the sequence.
        :param relaxed: this should be set to True when a previous request didn't find
            something without. This allows to find a pattern from a previous period, and
            try to adapt it for the new period.
        :param with_prefix: The sequence prefix to restrict the search on, if any.

        :return: the string of the previous sequence or None if there wasn't any.
        """
        self.ensure_one()
        if self._sequence_field not in self._fields or not self._fields[self._sequence_field].store:
            raise ValidationError(_('%s is not a stored field', self._sequence_field))
        where_string, param = self._get_last_sequence_domain(relaxed)
        if self.id or self.id.origin:
            where_string += " AND id != %(id)s "
            param['id'] = self.id or self.id.origin
        if with_prefix is not None:
            where_string += " AND sequence_prefix = %(with_prefix)s "
            param['with_prefix'] = with_prefix
        where_string += " AND invoice_plan_id is null "

        query = f"""
                SELECT {{field}} FROM {self._table}
                {where_string}
                AND sequence_prefix = (SELECT sequence_prefix FROM {self._table} {where_string} ORDER BY id DESC LIMIT 1)
                ORDER BY sequence_number DESC
                LIMIT 1
        """
        if lock:
            query = f"""
            UPDATE {self._table} SET write_date = write_date WHERE id = (
                {query.format(field='id')}
            )
            RETURNING {self._sequence_field};
            """
        else:
            query = query.format(field=self._sequence_field)

        self.flush([self._sequence_field, 'sequence_number', 'sequence_prefix'])
        self.env.cr.execute(query, param)
        return (self.env.cr.fetchone() or [None])[0]
