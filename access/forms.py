from django import forms

from .models import User

_INPUT = "w-full rounded border border-slate-300 px-3 py-2 text-sm"


class OnboardUserForm(forms.ModelForm):
    """Create a login-capable user with an initial role, tier, and shift (issue #24)."""

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "employee_number",
            "role",
            "tier",
            "shift",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", _INPUT)
        self.fields["email"].required = True  # needed to send the password-setup link
