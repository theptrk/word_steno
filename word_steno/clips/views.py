import json
import logging
import math

from django.contrib.auth.decorators import user_passes_test
from django.contrib.postgres.search import SearchQuery
from django.contrib.postgres.search import SearchRank
from django.contrib.postgres.search import SearchVector
from django.db.models import F
from django.http import HttpResponse
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from pytube import YouTube

from .embeddings import search_embeddings
from .models import Chapter
from .models import Clip
from .models import ClipParagraph
from .utils import download_audio
from .utils import extract_chapters
from .utils import extract_paragraphs
from .utils import extract_youtube_video_id
from .utils import get_description
from .utils import transcribe_audio

# Static
TWO_HOURS = 2 * 60 * 60

logger = logging.getLogger(__name__)


# Create your views here.
def index(request):
    search_term = request.GET.get("query", "")
    if not search_term:
        return render(request, "clips/search.html")

    # Define the search query
    search_query = SearchQuery(search_term, config="english")

    # Annotate each ClipParagraph with a search vector and rank based on the 'text'
    # key of the sentences JSONB field
    clip_paragraphs = (
        ClipParagraph.objects.annotate(
            search_vector=SearchVector(
                "full_transcription",
                config="english",
                weight="A",
            ),
        )
        .annotate(
            rank=SearchRank(F("search_vector"), search_query),
        )
        .filter(search_vector=search_query)
        .order_by("-rank")
        .select_related("clip")
    )

    grouped_results = {}
    for cp in clip_paragraphs:
        clip_id = cp.clip.id
        if clip_id not in grouped_results:
            grouped_results[clip_id] = {
                "clip_paragraph_id": cp.id,
                "clip_id": cp.clip.id,
                "clip_url": f"{cp.clip.url}&t={int(cp.start-3)}",
                "clip_title": cp.clip.title,
                "sentences": cp.sentences,
                "full_transcription": [],
                "rank": cp.rank,
                "start": math.floor(
                    cp.start,
                ),
                "end": math.ceil(cp.end),
                "speaker": cp.speaker,
                "channel_title": cp.clip.channel_title,
                "video_length": cp.clip.length,
                "video_transcription": cp.clip.full_transcription,
                "video_summary": cp.clip.summary,
                "video_id": cp.clip.video_id,
                "embed_url": (
                    f"https://www.youtube.com/embed/{extract_youtube_video_id(cp.clip.url)}"
                    f"?start={math.floor(cp.start)}"
                    f"&end={math.ceil(cp.end)}"
                ),
            }
        # Now append the full_transcription and any other necessary details
        grouped_results[clip_id]["full_transcription"].append(
            {
                "text": cp.full_transcription,
                "start": math.floor(cp.start),
                "end": math.ceil(cp.end),
            },
        )
        # Repeat for other fields as necessary

    # After appending all full_transcription entries to grouped_results
    for group in grouped_results.values():
        # Sort the full_transcription list for each group by the 'start' value
        group["full_transcription"] = sorted(
            group["full_transcription"],
            key=lambda x: x["start"],
        )

    # Convert grouped_results to a list format as per your requirement
    results = [value for key, value in grouped_results.items()]

    return render(
        request,
        "clips/search.html",
        {"results": results, "search_term": search_term},
    )


def clip(request, clip_id, start=0):
    try:
        if request.method == "POST":
            # Extract the updated speaker information from the POST data
            old_speaker = request.POST.get("speakers")
            updated_speaker = request.POST.get("new_speaker")

            # Update ClipParagraph instances
            if updated_speaker is not None:
                ClipParagraph.objects.filter(
                    clip_id=clip_id,
                    speaker=old_speaker,
                ).update(speaker=updated_speaker)
                return redirect(
                    reverse("clips:clip", args=[clip_id]),
                )

        # fetch clip data
        clip = Clip.objects.get(id=clip_id)
        paragraph_set = ClipParagraph.objects.filter(clip_id=clip_id).order_by("start")
        speakers = (
            ClipParagraph.objects.filter(clip_id=clip_id)
            .values_list("speaker", flat=True)
            .distinct()
            .order_by("speaker")
        )

        clip_paragraphs = [
            {
                "id": cp.id,
                "sentences": cp.sentences,
                "full_transcription": cp.full_transcription,
                "start": math.floor(cp.start),
                "end": math.ceil(cp.end),
                "speaker": cp.speaker,
            }
            for cp in paragraph_set
        ]

        # Get chapters
        chapters = Chapter.objects.filter(clip_id=clip_id).order_by("start").values()

        # Format chapter summaries
        formatted_summaries = []

        for chapter in chapters:
            chapter_data = {
                **chapter,
                "summary_list": (
                    chapter["summary"].split("\n") if chapter["summary"] else []
                ),
            }

            formatted_summaries.append(chapter_data)

        return render(
            request,
            "clips/clip.html",
            {
                "clip": clip,
                "clip_paragraphs": clip_paragraphs,
                "serialized_paragraphs": json.dumps(clip_paragraphs),
                "speakers": speakers,
                "start": start,
                "chapters": formatted_summaries,
            },
        )
    except Clip.DoesNotExist:
        return HttpResponse(f"Clip with ID {clip_id} does not exist.", status=500)


def update_speaker(request, clip_id):
    # Extract the updated speaker information from the POST data
    paragraph_id = request.POST.get("paragraph_id")
    updated_speaker = request.POST.get("new_speaker")

    # Update ClipParagraph instances
    if updated_speaker is not None:
        ClipParagraph.objects.filter(clip_id=clip_id, id=paragraph_id).update(
            speaker=updated_speaker,
        )
        # Redirect to a new URL to prevent form resubmission
        return redirect(
            reverse("clips:clip", args=[clip_id]),
        )

    return HttpResponse("No speaker name provided.", status=400)


def channels(request):
    try:
        # Fetch distinct channels
        channel_titles = Clip.objects.values_list("channel_title", flat=True).distinct()

        selected_channel = request.GET.get("channel", None)
        clips = None

        if selected_channel:
            # Fetch clips for the selected channel
            clips = Clip.objects.filter(channel_title=selected_channel).order_by(
                "-published_at",
            )

        return render(
            request,
            "clips/channels.html",
            {
                "channel_titles": channel_titles,
                "clips": clips,
                "selected_channel": selected_channel,
            },
        )

    except Clip.DoesNotExist:
        return HttpResponse("Channels do not exist.", status=500)


@user_passes_test(lambda u: u.is_superuser)
def download(request):
    if request.method == "POST":
        try:
            video_url = request.POST.get("youtube_url")

            if not video_url:
                return HttpResponse("No URL provided", status=400)

            # Initialize video url
            yt = YouTube(video_url)
            if yt.length > TWO_HOURS:
                return HttpResponse(
                    (
                        "Youtube Video is greater than 2 hours. "
                        "Please use a shorter video."
                    ),
                    status=400,
                )

            # Check if the Clip with this video_id already exists
            video_id = extract_youtube_video_id(video_url)
            clip, created = Clip.objects.get_or_create(
                video_id=video_id,
                defaults={
                    "url": video_url,
                    "title": yt.title,
                    "length": yt.length,
                    "channel_title": yt.author,
                    "description": get_description(video_url),
                    "published_at": yt.publish_date,
                },
            )

            if not created:
                return redirect(reverse("clips:clip", args=[clip.id]))

            # Download & Upload Audio to S3
            video_details = download_audio(yt)

            # Transcribe audio file from S3
            transcribed_audio = transcribe_audio(video_details["object_name"])

            # modify transcribed data to json format
            data = transcribed_audio.to_json()
            data = json.loads(data)
            deepgram_object = data["results"]["channels"][0]["alternatives"][0]
            paragraphs_data = deepgram_object["paragraphs"]["paragraphs"]

            # Save transcribed data to clip model
            clip.storage_path = video_details["storage_path"]
            clip.full_transcription = deepgram_object["paragraphs"]["transcript"]
            clip.summary = data["results"]["summary"]["short"]
            clip.paragraphs = paragraphs_data
            clip.words = deepgram_object["words"]

            clip.save()

            # Save Paragraphs in ClipParagraph model
            extracted_paragraphs = extract_paragraphs(paragraphs_data, clip)

            # Save Chapters in Chapters model
            extract_chapters(extracted_paragraphs, clip)

            # Redirect to results page
            return redirect(reverse("clips:clip", args=[clip.id]))
        except Exception as e:
            logging.exception(
                "Exception: download POST: downloading, transcribing and saving the clip.",
            )
            return HttpResponse(f"An error occurred: {e}", status=500)
    else:
        return render(request, "clips/download_form.html")


def delete(request, clip_id):
    try:
        # fetch clip data
        clip = Clip.objects.get(id=clip_id)
        clip.delete()

        return HttpResponse(f"Clip with ID {clip_id} is deleted", status=200)
    except Clip.DoesNotExist:
        return HttpResponse(f"Clip with ID {clip_id} does not exist.", status=500)


# transfer paragraphs to a new model
def paragraph(request, clip_id):
    try:
        # fetch clip data
        clip = Clip.objects.get(id=clip_id)
        paragraphs_data = clip.paragraphs

        if paragraphs_data:
            for paragraph in paragraphs_data:
                # Create Full Transcription for the paragraph
                full_transcription = ""
                sentences = paragraph.get("sentences")
                if sentences:
                    for sentence in sentences:
                        full_transcription += sentence.get("text") + " "

                ClipParagraph.objects.create(
                    clip=clip,
                    end=paragraph.get("end"),
                    start=paragraph.get("start"),
                    speaker=paragraph.get("speaker"),
                    sentences=paragraph.get("sentences"),
                    full_transcription=full_transcription,
                )
        return HttpResponse("Paragraphs transferred successfully.", status=200)
    except Clip.DoesNotExist:
        return HttpResponse("Clip not found.", status=404)


def embedding_save(request):
    try:
        for clip in Clip.objects.all():
            clip.video_id = extract_youtube_video_id(clip.url)
            clip.save()

        return HttpResponse("Embedding successfully.", status=200)

    except Exception as e:
        logging.exception("Exception: embedding_save.")
        return HttpResponse(f"An error occurred in embedding: {e}", status=500)


def embedding(request):
    search_term = request.GET.get("query", "")
    if search_term:
        clip_paragraphs = search_embeddings(search_term, ClipParagraph)
        results = [
            {
                "clip_paragraph_id": cp.id,
                "clip_id": cp.clip.id,
                "clip_url": f"{cp.clip.url}&t={int(cp.start-3)}",
                "clip_title": cp.clip.title,
                "sentences": cp.sentences,
                "full_transcription": cp.full_transcription,
                "start": cp.start,
                "end": cp.end,
                "speaker": cp.speaker,
                "channel_title": cp.clip.channel_title,
                "video_length": cp.clip.length,
                "video_transcription": cp.clip.transcription,
                "video_summary": cp.clip.summary,
            }
            for cp in clip_paragraphs
        ]
    else:
        results = ClipParagraph.objects.none()
        return render(request, "clips/embedding.html")
    return render(request, "clips/results.html", {"results": results})
