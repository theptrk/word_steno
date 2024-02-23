from django.urls import path

from . import views

app_name = "clips"

urlpatterns = [
    path("", views.index, name="index"),
    # path("transcribe/<str:clip_id>/", views.transcribe, name="transcribe"),
    path("clip/<int:clip_id>/", views.clip, name="clip"),
    path("clip/<int:clip_id>/<int:start>", views.clip, name="clip_with_start"),
    path("update_speaker/<int:clip_id>", views.update_speaker, name="update_speaker"),
    path("channels", views.channels, name="channels"),
    path("download", views.download, name="download"),
    # path("delete/<str:clip_id>/", views.delete, name="delete"),
    # path("paragraph/<str:clip_id>/", views.paragraph, name="paragraph"),
    path("embedding", views.embedding, name="embedding"),
    path("embedding_save", views.embedding_save, name="embedding_save"),
]
