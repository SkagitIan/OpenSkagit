from django import forms

from .models import (
    ContactSubmission,
    WeeklyBriefingSection,
    WeeklyBriefingTemplate,
)


class ContactSubmissionForm(forms.ModelForm):
    class Meta:
        model = ContactSubmission
        fields = ["email", "topic", "message"]
        labels = {
            "email": "Email",
            "topic": "Topic",
            "message": "How can we help?",
        }
        help_texts = {
            "topic": "Pick the option that best matches your request.",
        }
        widgets = {
            "message": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base_classes = (
            "mt-1 block w-full rounded-xl border border-slate-200 bg-white px-4 py-3 "
            "text-base text-slate-900 shadow-sm focus:border-sage-500 focus:ring-sage-500"
        )
        for name, field in self.fields.items():
            classes = base_classes
            if isinstance(field.widget, forms.Textarea):
                classes += " resize-none"
            field.widget.attrs.setdefault("class", classes)
            if name == "email":
                field.widget.attrs.setdefault("placeholder", "you@example.com")
            if name == "message":
                field.widget.attrs.setdefault("placeholder", "Let us know how we can help.")

    def clean_message(self) -> str:
        message = self.cleaned_data.get("message", "")
        message = message.strip()
        if not message:
            raise forms.ValidationError("Please share a short message.")
        return message


class ConsultIntakeForm(forms.Form):
    email = forms.EmailField(label="Contact email")
    business_description = forms.CharField(
        label="Business description",
        help_text="One sentence about the company and location.",
    )
    biggest_question = forms.CharField(
        label="Biggest question or uncertainty",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base_classes = (
            "mt-1 block w-full rounded-xl border border-slate-200 bg-white px-4 py-3 "
            "text-base text-slate-900 shadow-sm focus:border-sage-500 focus:ring-sage-500"
        )
        for name, field in self.fields.items():
            classes = base_classes
            if isinstance(field.widget, forms.Textarea):
                classes += " resize-none"
            field.widget.attrs.setdefault("class", classes)
            if name == "email":
                field.widget.attrs.setdefault("placeholder", "you@company.com")
            if name == "business_description":
                field.widget.attrs.setdefault("placeholder", "Restaurant in downtown Sedro-Woolley, contractor in Burlington, etc.")
            if name == "biggest_question":
                field.widget.attrs.setdefault("placeholder", "What feels unclear right now?")


class WeeklyBriefingTemplateForm(forms.ModelForm):
    class Meta:
        model = WeeklyBriefingTemplate
        fields = [
            "subject",
            "preheader",
            "hero_title",
            "hero_lede",
            "hero_stat_label",
            "hero_stat_value",
            "cta_label",
            "cta_url",
            "footer_note",
        ]
        widgets = {
            "hero_lede": forms.Textarea(attrs={"rows": 4}),
            "footer_note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base_classes = (
            "mt-1 block w-full rounded-xl border border-slate-200 bg-white px-4 py-3 "
            "text-base text-slate-900 shadow-sm focus:border-sage-500 focus:ring-sage-500"
        )
        for name, field in self.fields.items():
            classes = base_classes
            if isinstance(field.widget, forms.Textarea):
                classes += " resize-none"
            field.widget.attrs.setdefault("class", classes)


class WeeklyBriefingSectionForm(forms.ModelForm):
    class Meta:
        model = WeeklyBriefingSection
        fields = ["title", "summary", "badge", "highlight", "order"]
        widgets = {
            "summary": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base_classes = (
            "mt-1 block w-full rounded-xl border border-slate-200 bg-white px-4 py-2 "
            "text-sm text-slate-900 shadow-sm focus:border-sage-500 focus:ring-sage-500"
        )
        for field in self.fields.values():
            classes = base_classes
            if isinstance(field.widget, forms.Textarea):
                classes += " resize-none"
            field.widget.attrs.setdefault("class", classes)
