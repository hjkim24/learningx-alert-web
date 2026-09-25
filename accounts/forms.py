from django import forms


class CanvasTokenForm(forms.Form):
    token = forms.CharField(
        label="Canvas 액세스 토큰",
        max_length=4096,
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "off"}),
    )
