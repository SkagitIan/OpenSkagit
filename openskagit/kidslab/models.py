from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class Card(models.Model):
    class CardType(models.TextChoices):
        YOUTUBE = "YOUTUBE", "YouTube"
        ANIMAL_SOUND = "ANIMAL_SOUND", "Animal Sound"
        PHOTO = "PHOTO", "Photo"
        DRAW = "DRAW", "Draw"
        PLACEHOLDER = "PLACEHOLDER", "Placeholder"
        MAZE = "MAZE", "Maze"

    class Direction(models.TextChoices):
        UP = "up", "Up"
        DOWN = "down", "Down"
        LEFT = "left", "Left"
        RIGHT = "right", "Right"
        SEQUENCE = "sequence", "Sequence"

    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80, blank=True)
    card_type = models.CharField(max_length=20, choices=CardType.choices)
    direction = models.CharField(
        max_length=20, choices=Direction.choices, default=Direction.UP
    )
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    image = models.ImageField(upload_to="kidslab/images", null=True, blank=True)
    photo = models.ImageField(upload_to="kidslab/images", null=True, blank=True)
    audio = models.FileField(upload_to="kidslab/audio", null=True, blank=True)
    youtube_url = models.URLField(blank=True, null=True)
    config = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["direction", "order", "title"]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        errors = {}
        card_type = self.card_type

        if card_type == self.CardType.YOUTUBE:
            if not self.youtube_url:
                errors["youtube_url"] = ValidationError(
                    _("YouTube cards require a URL."), code="required"
                )
        elif card_type == self.CardType.ANIMAL_SOUND:
            if not self.image:
                errors["image"] = ValidationError(
                    _("Animal sound cards require an image."), code="required"
                )
            if not self.audio:
                errors["audio"] = ValidationError(
                    _("Animal sound cards require an audio file."), code="required"
                )
        elif card_type == self.CardType.PHOTO:
            if not self.photo:
                errors["photo"] = ValidationError(
                    _("Photo cards require a photo."), code="required"
                )
        elif card_type == self.CardType.DRAW:
            if any([self.image, self.photo, self.audio, self.youtube_url]):
                errors["card_type"] = ValidationError(
                    _("Draw cards must not include media attachments."), code="invalid"
                )
        elif card_type == self.CardType.MAZE:
            if not self.photo:
                errors["photo"] = ValidationError(
                    _("Maze cards require a background image."), code="required"
                )
        if errors:
            raise ValidationError(errors)

    def assets(self):
        assets = {}
        if self.image:
            assets["image"] = self.image.url
        if self.photo:
            assets["photo"] = self.photo.url
        if self.audio:
            assets["audio"] = self.audio.url
        if self.youtube_url:
            assets["youtube_url"] = self.youtube_url
        return assets
