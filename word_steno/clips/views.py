import json
import math

from django.contrib.postgres.search import SearchQuery
from django.http import HttpResponse
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse

from .embeddings import search_embeddings
from .models import Clip
from .models import ClipParagraph
from .utils import check_url_exists
from .utils import download_audio
from .utils import extract_chapters
from .utils import extract_paragraphs
from .utils import extract_youtube_video_id
from .utils import get_description
from .utils import transcribe_audio


# Create your views here.
def index(request):
    # Handle the POST request
    if request.method == "POST":
        try:
            video_url = request.POST.get("youtube_url")

            if not video_url:
                return HttpResponse("No URL provided", status=400)

            # Check if there's an existing youtube URL
            clips = Clip.objects.all()
            if clips:
                matching_url = check_url_exists(clips, video_url)
                if matching_url:
                    return redirect(reverse("clips:clip", args=[matching_url.id]))

            # Get Video Details & Download file
            video_details = download_audio(video_url)

            if not video_details:
                return HttpResponse(
                    "Youtube Video is greater than 2 hours. Please use a shorter video.",
                    status=400,
                )

            # Transcribe downloaded audio file
            transcribed_audio = transcribe_audio(video_details["object_name"])
            # modify transcribed data to json format
            data = transcribed_audio.to_json()
            data = json.loads(data)
            paragraphs_data = data["results"]["channels"][0]["alternatives"][0][
                "paragraphs"
            ]["paragraphs"]
            # Save transcribed data to clip model
            clip = Clip(
                url=video_url,
                video_id=extract_youtube_video_id(video_url),
                storage_path=video_details["storage_path"],
                title=video_details["video_title"],
                length=video_details["video_length"],
                channel_title=video_details["channel_title"],
                description=video_details["video_description"],
                published_at=video_details["publish_date"],
                full_transcription=data["results"]["channels"][0]["alternatives"][0][
                    "paragraphs"
                ]["transcript"],
                summary=data["results"]["summary"]["short"],
                paragraphs=paragraphs_data,
                words=data["results"]["channels"][0]["alternatives"][0]["words"],
            )
            clip.save()

            extract_paragraphs(paragraphs_data, clip)

            # Redirect to results page
            return redirect(reverse("clips:clip", args=[clip.id]))

            return HttpResponse("Audio download complete!")
        except Exception as e:
            return HttpResponse(f"An error occurred: {e}", status=500)

    # Handle the GET request
    else:
        search_term = request.GET.get("query", "")
        if search_term:
            # Define the search query
            search_query = SearchQuery(search_term, config="english")

            # Annotate each ClipParagraph with a search vector and rank based on the 'text' key of the sentences JSONB field
            clip_paragraphs = ClipParagraph.search_by_transcription(search_query)

            grouped_results = {}
            for cp in clip_paragraphs:
                clip_id = cp.clip.id
                if clip_id not in grouped_results:
                    grouped_results[clip_id] = {
                        "clip_paragraph_id": cp.id,
                        "clip_id": cp.clip.id,
                        "clip_url": f"{cp.clip.url}&t={int(cp.start-3)}",  # Example of including Clip detail
                        "clip_title": cp.clip.title,  # Example of including Clip detail
                        "sentences": cp.sentences,
                        "full_transcription": [],
                        "rank": cp.rank,
                        "start": math.floor(
                            cp.start,
                        ),  # Example of including Clip detail, cp.start,
                        "end": math.ceil(cp.end),
                        "speaker": cp.speaker,
                        "channel_title": cp.clip.channel_title,
                        "video_length": cp.clip.length,
                        "video_transcription": cp.clip.full_transcription,
                        "video_summary": cp.clip.summary,
                        "video_id": cp.clip.video_id,
                        "embed_url": f"https://www.youtube.com/embed/{extract_youtube_video_id(cp.clip.url)}?start={math.floor(cp.start)}&end={math.ceil(cp.end)}",
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
            for clip_id, group in grouped_results.items():
                # Sort the full_transcription list for each group by the 'start' value
                group["full_transcription"] = sorted(
                    group["full_transcription"],
                    key=lambda x: x["start"],
                )

            # Convert grouped_results to a list format as per your requirement
            results = [value for key, value in grouped_results.items()]

        else:
            results = Clip.objects.none()
            return render(request, "clips/search.html")
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
                )  # Redirect to a new URL to prevent form resubmission

        # fetch clip data
        clip = Clip.objects.get(id=clip_id)
        paragraph_set = ClipParagraph.objects.filter(clip_id=clip_id).order_by("start")
        speakers = (
            ClipParagraph.objects.filter(clip_id=clip_id)
            .values_list("speaker", flat=True)
            .distinct()
            .order_by("speaker")
        )

        desc = get_description(clip.url)
        chapters = extract_chapters(desc)

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

        return render(
            request,
            "clips/clip.html",
            {
                "clip": clip,
                "clip_paragraphs": clip_paragraphs,
                "serialized_paragraphs": json.dumps(clip_paragraphs),
                "speakers": speakers,
                "start": start,
                "chapters": chapters,
            },
        )
    except Clip.DoesNotExist:
        return HttpResponse(f"Clip with ID {clip_id} does not exist.", status=500)


def update_speaker(request, clip_id):
    if request.method == "POST":
        # Extract the updated speaker information from the POST data
        paragraph_id = request.POST.get("paragraph_id")
        updated_speaker = request.POST.get("new_speaker")

        # Update ClipParagraph instances
        if updated_speaker is not None:
            ClipParagraph.objects.filter(clip_id=clip_id, id=paragraph_id).update(
                speaker=updated_speaker,
            )
            return redirect(
                reverse("clips:clip", args=[clip_id]),
            )  # Redirect to a new URL to prevent form resubmission


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


def download(request):
    try:
        return render(request, "clips/download_form.html")

    except Clip.DoesNotExist:
        return HttpResponse("Channels do not exist.", status=500)


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
                        # print(sentence.get("text"), sentence)
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
            # print(extract_youtube_video_id(clip.url))
            clip.video_id = extract_youtube_video_id(clip.url)
            clip.save()

        return HttpResponse("Embedding successfully.", status=200)

    except Exception as e:
        return HttpResponse(f"An error occurred in embedding: {e}", status=500)


def embedding(request):
    search_term = request.GET.get("query", "")
    if search_term:
        clip_paragraphs = search_embeddings(search_term, ClipParagraph)
        results = [
            {
                "clip_paragraph_id": cp.id,
                "clip_id": cp.clip.id,
                "clip_url": f"{cp.clip.url}&t={int(cp.start-3)}",  # Example of including Clip detail
                "clip_title": cp.clip.title,  # Example of including Clip detail
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
