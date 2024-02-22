from django.db import models
from django.utils import timezone
from django.utils.timesince import timesince
from pgvector.django import VectorField


# Create your models here.
class Clip(models.Model):
    url = models.URLField()
    video_id = models.CharField(max_length=255, blank=True, null=True)
    storage_path = models.CharField(max_length=255, blank=True, null=True)
    length = models.IntegerField(blank=True, null=True)
    title = models.CharField(max_length=255, blank=True, null=True)
    channel_title = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True, null=True)

    full_transcription = models.TextField(blank=True, null=True)
    summary = models.TextField(blank=True, null=True)
    paragraphs = models.JSONField(blank=True, null=True)
    words = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return self.title

    @property
    def published_ago(self):
        """Returns a human-readable string representing how long ago the clip was published."""
        if self.published_at:
            now = timezone.now()
            return timesince(self.published_at, now) + " ago"
        return "Not published yet"


class ClipParagraph(models.Model):
    clip = models.ForeignKey(Clip, on_delete=models.CASCADE)
    end = models.FloatField(blank=True, null=True)
    start = models.FloatField(blank=True, null=True)
    speaker = models.CharField(max_length=255, blank=True, null=True)
    sentences = models.JSONField(blank=True, null=True)
    full_transcription = models.TextField(blank=True, null=True)
    embedding = VectorField(
        dimensions=1024,
        blank=True,
        null=True,
    )  # For storing the sentence embedding
