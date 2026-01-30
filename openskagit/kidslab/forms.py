from django import forms

from .models import Card


class CardUploadForm(forms.ModelForm):
    as_maze = forms.BooleanField(
        required=False,
        help_text="Check to enable drawing on top of this image as a maze.",
        widget=forms.CheckboxInput(attrs={"class": "h-4 w-4"}),
    )
    class Meta:
        model = Card
        fields = ["title", "direction", "photo", "as_maze"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "w-full rounded-md border border-slate-300 px-3 py-2",
                "placeholder": "Card title",
            }),
            "direction": forms.Select(attrs={
                "class": "w-full rounded-md border border-slate-300 px-3 py-2",
            }),
            "photo": forms.ClearableFileInput(attrs={"class": "w-full"}),
        }

    def save(self, commit: bool = True):
        instance = super().save(commit=False)
        instance.card_type = (
            Card.CardType.MAZE if self.cleaned_data.get("as_maze") else Card.CardType.PHOTO
        )
        instance.is_active = True
        if commit:
            instance.save()
        return instance
