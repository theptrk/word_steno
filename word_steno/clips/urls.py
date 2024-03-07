from django.urls import path

from . import views

app_name = "clips"

urlpatterns = [
    path("", views.index, name="index"),
    path("clip/<int:clip_id>/", views.clip, name="clip"),
    path(
        "clip/<int:clip_id>/<str:phrase>/<int:start>",
        views.clip,
        name="clip_with_start",
    ),
    path("update_speaker/<int:clip_id>", views.update_speaker, name="update_speaker"),
    path("channels", views.channels, name="channels"),
    path("download", views.download, name="download"),
]
