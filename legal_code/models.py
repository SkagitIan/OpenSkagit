from django.db import models

class Jurisdiction(models.Model):
    name = models.CharField(max_length=200, unique=True)
    state = models.CharField(max_length=2)

    def __str__(self):
        return self.name


class JurisdictionAlias(models.Model):
    jurisdiction = models.ForeignKey(
        Jurisdiction,
        on_delete=models.CASCADE,
        related_name="aliases",
    )
    alias = models.CharField(max_length=200)
    alias_normalized = models.CharField(max_length=200, unique=True, db_index=True)
    source = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["alias_normalized"]

    def __str__(self):
        return f"{self.alias} -> {self.jurisdiction.name}"


class LawDocument(models.Model):
    jurisdiction = models.ForeignKey(Jurisdiction, on_delete=models.CASCADE)
    title_number = models.CharField(max_length=20)
    title_name = models.CharField(max_length=255)
    source_vendor = models.CharField(max_length=100)
    effective_note = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ("jurisdiction", "title_number")

    def __str__(self):
        return f"{self.jurisdiction} Title {self.title_number}"


class LawChapter(models.Model):
    document = models.ForeignKey(LawDocument, on_delete=models.CASCADE)
    chapter_number = models.CharField(max_length=20)
    chapter_name = models.CharField(max_length=255)
    code_set = models.CharField(max_length=100,blank=True, null=True) 
    class Meta:
        unique_together = ("document", "chapter_number")

    def __str__(self):
        return f"Chapter {self.chapter_number}"


class LawSection(models.Model):
    chapter = models.ForeignKey(LawChapter, on_delete=models.CASCADE)
    section_id = models.CharField(max_length=50)
    heading = models.CharField(max_length=500)

    content = models.TextField()
    history = models.JSONField(default=list, blank=True)
    tables = models.JSONField(default=list, blank=True)

    content_hash = models.CharField(max_length=64, db_index=True)

    source_url = models.URLField()
    scraped_at = models.DateTimeField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["section_id"]),
            models.Index(fields=["content_hash"]),
        ]

    def __str__(self):
        return self.section_id

# yourapp/models.py
from django.db import models
from pgvector.django import VectorField

class LawSectionChunk(models.Model):
    section = models.ForeignKey(
        "LawSection",
        on_delete=models.CASCADE,
        related_name="chunks",
    )
    jurisdiction = models.ForeignKey(
        "Jurisdiction",
        on_delete=models.CASCADE,
        db_index=True,
    )

    # denormalized citation metadata
    law_section_ref = models.CharField(max_length=50, db_index=True)
    heading = models.CharField(max_length=500, blank=True)
    source_url = models.URLField()

    chunk_index = models.PositiveIntegerField(default=0)
    content = models.TextField()
    content_hash = models.CharField(max_length=64, db_index=True)

    embedding_model = models.CharField(max_length=100)
    embedding = VectorField(dimensions=1536, null=True, blank=True)

    embedded_at = models.DateTimeField(null=True, blank=True)

    lane_scores = models.JSONField(null=True, blank=True)
    lanes_classified_at = models.DateTimeField(null=True, blank=True)


    class Meta:
        unique_together = ("section", "chunk_index", "embedding_model")
        indexes = [
            models.Index(fields=["jurisdiction", "section_id"]),
            models.Index(fields=["content_hash"]),
        ]
