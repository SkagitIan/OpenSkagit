from pathlib import Path

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


class StaffImageGeneratorForm(forms.Form):
    MAX_UPLOAD_BYTES = 10 * 1024 * 1024
    ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

    prompt = forms.CharField(
        label="Prompt",
        required=True,
        widget=forms.Textarea(attrs={"rows": 6}),
    )
    init_image = forms.FileField(
        label="Attach Initial Image (optional - for image-to-image mode)",
        required=False,
    )
    steps = forms.IntegerField(
        label="Number of inference steps",
        min_value=1,
        max_value=150,
        initial=28,
    )
    guidance_scale = forms.FloatField(
        label="Guidance scale",
        min_value=0.0,
        max_value=25.0,
        initial=3.5,
    )
    width = forms.IntegerField(
        label="Width",
        min_value=256,
        max_value=2048,
        initial=1024,
    )
    height = forms.IntegerField(
        label="Height",
        min_value=256,
        max_value=2048,
        initial=1024,
    )
    seed = forms.IntegerField(
        label="Seed",
        min_value=0,
        max_value=2147483647,
        initial=42,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        text_classes = (
            "mt-1 block w-full rounded-xl border border-slate-300 bg-white px-4 py-3 "
            "text-sm text-slate-900 shadow-sm focus:border-sage-500 focus:ring-sage-500"
        )
        for field_name, field in self.fields.items():
            classes = text_classes
            if isinstance(field.widget, forms.Textarea):
                classes += " resize-y"
            field.widget.attrs.setdefault("class", classes)
            if field_name == "prompt":
                field.widget.attrs.setdefault("placeholder", "Describe the image you want to generate.")

    def clean_prompt(self) -> str:
        prompt = (self.cleaned_data.get("prompt") or "").strip()
        if not prompt:
            raise forms.ValidationError("Prompt is required.")
        return prompt

    def clean_init_image(self):
        uploaded = self.cleaned_data.get("init_image")
        if not uploaded:
            return uploaded
        if uploaded.size > self.MAX_UPLOAD_BYTES:
            raise forms.ValidationError("Initial image must be 10MB or smaller.")
        extension = Path(uploaded.name or "").suffix.lower()
        if extension and extension not in self.ALLOWED_IMAGE_EXTENSIONS:
            raise forms.ValidationError("Upload a supported image file (PNG, JPG, WEBP, or BMP).")
        content_type = (getattr(uploaded, "content_type", "") or "").lower()
        if content_type and not content_type.startswith("image/"):
            raise forms.ValidationError("Uploaded file must be an image.")
        return uploaded

    def clean(self):
        cleaned = super().clean()
        for field_name in ("width", "height"):
            value = cleaned.get(field_name)
            if value is not None and value % 8 != 0:
                self.add_error(field_name, "Must be divisible by 8.")
        return cleaned
