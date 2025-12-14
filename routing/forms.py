from django import forms


class AreaSearchForm(forms.Form):
    city = forms.CharField(max_length=255, required=False)
    region = forms.CharField(max_length=255, required=False)
    state = forms.CharField(max_length=255, required=False)
