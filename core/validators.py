import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

class CapitalFirstPasswordValidator:
    """
    Validator to ensure that:
    1. Password is at least min_length (default 8) characters long.
    2. The first character is an uppercase (capital) letter (A-Z).
    3. Password contains at least one lowercase letter (a-z).
    4. Password contains at least one digit (0-9).
    5. Password contains at least one special character.
    """
    def __init__(self, min_length=8):
        self.min_length = min_length

    def validate(self, password, user=None):
        if not password:
            raise ValidationError(
                _("Password cannot be empty."),
                code='password_empty',
            )

        errors = []

        if len(password) < self.min_length:
            errors.append(ValidationError(
                _("Password must be at least %(min_length)d characters long."),
                code='password_too_short',
                params={'min_length': self.min_length},
            ))

        if not password[0].isupper():
            errors.append(ValidationError(
                _("Password must start with a capital (uppercase) letter."),
                code='password_no_capital_first',
            ))

        if not re.search(r'[a-z]', password):
            errors.append(ValidationError(
                _("Password must contain at least one lowercase letter."),
                code='password_no_lower',
            ))

        if not re.search(r'\d', password):
            errors.append(ValidationError(
                _("Password must contain at least one digit."),
                code='password_no_digit',
            ))

        if not re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>/?]', password):
            errors.append(ValidationError(
                _("Password must contain at least one special character (e.g. !@#$%^&*)."),
                code='password_no_special',
            ))

        if errors:
            raise ValidationError(errors)

    def get_help_text(self):
        return _(
            "Your password must be at least %(min_length)d characters long, start with a capital letter, "
            "and contain at least one lowercase letter, one digit, and one special character."
        ) % {'min_length': self.min_length}
