from django.contrib.auth.forms import AuthenticationForm


class StudioLoginForm(AuthenticationForm):
    """Login form with the placeholders and autocomplete hints the studio login page expects."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {
                "placeholder": "Enter your username",
                "autocomplete": "username",
                "autofocus": True,
            }
        )
        self.fields["password"].widget.attrs.update(
            {
                "placeholder": "Enter your password",
                "autocomplete": "current-password",
            }
        )
