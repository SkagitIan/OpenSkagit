from django import forms

from .models import GISDiscoveredLayer, GISLayerManifest, GISSourceSubmission
from .services.manifest import suggest_manifest_key

_BASE_INPUT_CSS = (
    "mt-1 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 "
    "text-sm text-slate-900 shadow-sm focus:border-sky-500 focus:ring-sky-500"
)


class GISSourceSubmissionForm(forms.ModelForm):
    class Meta:
        model = GISSourceSubmission
        fields = ["submitted_url", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = _BASE_INPUT_CSS
            if isinstance(field.widget, forms.Textarea):
                css += " resize-y"
            field.widget.attrs.setdefault("class", css)
        self.fields["submitted_url"].widget.attrs.setdefault(
            "placeholder",
            "https://.../arcgis/rest/services/.../FeatureServer or map/viewer/item URL",
        )


class GISDiscoveredLayerReviewForm(forms.ModelForm):
    class Meta:
        model = GISDiscoveredLayer
        fields = ["source_org", "category", "coverage", "skagit_relevance", "usability", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = _BASE_INPUT_CSS
            if isinstance(field.widget, forms.Textarea):
                css += " resize-y"
            field.widget.attrs.setdefault("class", css)


class GISManifestPromotionForm(forms.Form):
    key = forms.CharField(max_length=128, help_text="snake_case key")
    label = forms.CharField(max_length=255)
    category = forms.ChoiceField(choices=GISLayerManifest._meta.get_field("category").choices)
    default_fields = forms.CharField(
        required=False,
        help_text="Comma-separated field names to query by default.",
        widget=forms.TextInput(),
    )
    canonical_for_category = forms.BooleanField(required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        discovered_layer = kwargs.pop("discovered_layer", None)
        super().__init__(*args, **kwargs)

        if discovered_layer is not None and not self.is_bound:
            self.initial.setdefault("key", suggest_manifest_key(discovered_layer))
            self.initial.setdefault("label", discovered_layer.layer_name or suggest_manifest_key(discovered_layer))
            self.initial.setdefault("category", discovered_layer.category or "other")
            if isinstance(discovered_layer.fields_json, list):
                sample = [str(item.get("name")) for item in discovered_layer.fields_json[:8] if isinstance(item, dict)]
                self.initial.setdefault("default_fields", ", ".join(item for item in sample if item))
            self.initial.setdefault("notes", discovered_layer.notes)

        for field in self.fields.values():
            css = _BASE_INPUT_CSS
            if isinstance(field.widget, forms.Textarea):
                css += " resize-y"
            field.widget.attrs.setdefault("class", css)

    def clean_key(self) -> str:
        value = (self.cleaned_data.get("key") or "").strip().lower()
        if not value:
            raise forms.ValidationError("Manifest key is required.")
        if value.replace("_", "").isalnum() is False:
            raise forms.ValidationError("Use only lowercase letters, numbers, and underscores.")
        return value


class GISManifestFilterForm(forms.Form):
    category = forms.ChoiceField(required=False)
    source_org = forms.CharField(required=False, max_length=255)
    usability = forms.ChoiceField(required=False)
    status = forms.ChoiceField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        category_choices = [("", "All categories")] + list(GISLayerManifest._meta.get_field("category").choices)
        usability_choices = [("", "All usability")] + list(GISLayerManifest._meta.get_field("usability").choices)
        status_choices = [("", "All statuses")] + list(GISLayerManifest._meta.get_field("status").choices)
        self.fields["category"].choices = category_choices
        self.fields["usability"].choices = usability_choices
        self.fields["status"].choices = status_choices
        self.fields["source_org"].widget.attrs.setdefault("placeholder", "Org contains...")

        for field in self.fields.values():
            field.widget.attrs.setdefault("class", _BASE_INPUT_CSS)
