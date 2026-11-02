from django.db import models, router, transaction


class EmailStateMixin(models.Model):
    email_verified = models.BooleanField(default=False, editable=False, verbose_name='Email verified')

    class Meta:
        abstract = True

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        if 'email' in field_names:
            instance._email_at_load = instance.__dict__['email']
        return instance

    def save(self, *args, **kwargs):
        fields = kwargs.get('update_fields')
        if fields is not None:
            fields = set(fields)
            if not fields:
                return
            kwargs['update_fields'] = fields
        using = kwargs.get('using') or router.db_for_write(type(self), instance=self)
        if self._state.adding:
            self.email_verified = False
            result = super().save(*args, **kwargs)
            self._email_at_load = self.email
            return result
        if fields is not None and not fields.intersection({'email', 'email_verified'}):
            return super().save(*args, **kwargs)
        with transaction.atomic(using=using):
            current = type(self).objects.using(using).select_for_update().values('email', 'email_verified').get(pk=self.pk)
            if fields is None:
                requested = self.email
                baseline = getattr(self, '_email_at_load', current['email'])
                if requested == baseline:
                    self.email = current['email']
            elif 'email' not in fields:
                self.email = current['email']
            self.email_verified = bool(self.email and self.email == current['email'] and current['email_verified'])
            if fields is not None and 'email' in fields:
                fields.add('email_verified')
            result = super().save(*args, **kwargs)
            self._email_at_load = self.email
            return result
