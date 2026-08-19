from django import forms
from .models import Job


class JobSubmitForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = ["name", "description"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-green-500 focus:ring-1 focus:ring-green-500 focus:outline-none",
                "placeholder": "e.g. Canola field survey — June 2025",
            }),
            "description": forms.Textarea(attrs={
                "class": "w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-green-500 focus:ring-1 focus:ring-green-500 focus:outline-none",
                "rows": 3,
                "placeholder": "Optional notes about this submission…",
            }),
        }


class JobConfigureForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = ["conf", "marker_type"]
        widgets = {
            "conf": forms.NumberInput(attrs={
                "type": "range",
                "min": "0",
                "max": "1",
                "step": "0.01",
                "class": "w-full accent-brand-600",
                "x-model.number": "conf",
            }),
            "marker_type": forms.Select(attrs={
                "class": "w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-green-500 focus:ring-1 focus:ring-green-500 focus:outline-none",
            }),
        }
