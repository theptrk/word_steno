import logging
import os
import re
from io import BytesIO
from json import loads

import boto3
from botocore.exceptions import ClientError
from deepgram import DeepgramClient
from deepgram import PrerecordedOptions
from pytube import YouTube

from .embeddings import generate_summary_with_prompt
from .models import Chapter
from .models import ClipParagraph

TWO_HOURS = 2 * 60 * 60
FORMAT_HOURS = 3
FORMAT_MINUTES = 2


def get_description(video_url) -> str:
    video = YouTube(video_url)
    i: int = video.watch_html.find('"shortDescription":"')
    desc: str = '"'
    i += 20  # excluding the `"shortDescription":"`
    while True:
        letter = video.watch_html[i]
        desc += letter  # letter can be added in any case
        i += 1
        if letter == "\\":
            desc += video.watch_html[i]
            i += 1
        elif letter == '"':
            break
    return loads(desc)


def timestamp_to_seconds(timestamp):
    """Converts a timestamp in HH:MM:SS or MM:SS format to seconds."""
    parts = timestamp.split(":")
    parts = [int(part) for part in parts]

    if len(parts) == FORMAT_HOURS:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == FORMAT_MINUTES:
        return parts[0] * 60 + parts[1]
    return 0  # Return 0 seconds if the format is unexpected


def extract_chapters(paragraphs_data, clip):
    """Extracts chapters and their timestamps (in seconds) from a video description."""

    # Needs to check all "dash" characters (hyphen-minus, en dash, em dash) in but RUF001 doesn't allow it
    # Error Message: RUF001 String contains ambiguous (EN DASH). Did you mean (HYPHEN-MINUS)?
    chapter_regex = re.compile(
        r"(?:\((\d{1,2}:\d{2}(?::\d{2})?)\)|(\d{1,2}:\d{2}(?::\d{2})?))\s*[-–—)]?\s*(.*)",  # noqa: RUF001
    )

    chapters = []
    for line in clip.description.split("\n"):
        match = chapter_regex.match(line.strip())
        if match:
            # Choose the first matching group if it captured the timestamp, otherwise use the second
            timestamp_str = match.group(1) if match.group(1) else match.group(2)
            timestamp_seconds = timestamp_to_seconds(timestamp_str)
            title = match.group(3)
            chapters.append({"start": timestamp_seconds, "title": title})

    if len(chapters) == 0:
        return

    for i, chapter in enumerate(chapters):
        next_chapter_start = (
            clip.length  # Set the next chapter's start time to the end of the video
        )
        if i + 1 < len(chapters):
            next_chapter_start = chapters[i + 1]["start"]

        # Filter paragraphs that fall into the current chapter's time range
        chapter_paragraphs = [
            p
            for p in paragraphs_data
            if chapter["start"] <= p["start"] < next_chapter_start
        ]

        # Generate aggregated text for the chapter
        chapter_transcription = "\n\n".join(
            [
                f"Speaker: {p['speaker']}\n{p['full_transcription']}"
                for p in chapter_paragraphs
            ],
        )

        # Generate Speakers
        unique_speakers = {p["speaker"] for p in chapter_paragraphs}
        speakers = ", ".join([f"'{speaker}'" for speaker in unique_speakers])

        # Generate Summary for the chapter
        summarizer = generate_summary_with_prompt(
            chapter_transcription,
            speakers,
            chapter["title"],
        )

        Chapter.objects.create(
            clip=clip,
            title=chapter["title"],
            start=chapter["start"],
            paragraphs=chapter_paragraphs,
            chapter_transcription=chapter_transcription,
            prompt=summarizer["prompt"],
            summary=summarizer["summary"],
        )


def download_audio(yt):
    video_title = yt.title
    # Replace problematic characters in the title to make it a valid filename
    # You might need to expand this list based on your requirements
    filename = "".join([c for c in video_title if c.isalpha() or c.isdigit()]).rstrip()

    audio_stream = yt.streams.filter(only_audio=True).first()
    buffer = BytesIO()
    audio_stream.stream_to_buffer(buffer)
    buffer.seek(0)  # Rewind the buffer to the beginning

    object_name = upload_to_s3(
        buffer,
        filename,
        os.environ.get("DJANGO_AWS_STORAGE_BUCKET_NAME"),
    )

    return {
        "storage_path": f"https://{os.environ.get('DJANGO_AWS_STORAGE_BUCKET_NAME')}.s3.{os.environ.get('DJANGO_AWS_S3_REGION_NAME')}.amazonaws.com/{object_name}",
        "object_name": object_name,
    }


def upload_to_s3(buffer, filename, bucket_name):
    s3 = boto3.client(
        "s3",
        aws_access_key_id=os.environ.get("DJANGO_AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("DJANGO_AWS_SECRET_ACCESS_KEY"),
    )
    s3.upload_fileobj(buffer, bucket_name, f"clips/{filename}.mp3")
    return f"clips/{filename}.mp3"


def transcribe_audio(file_path):
    # Initialize the Deepgram SDK
    dg_client = DeepgramClient()

    # Create a presigned url for the audio file in S3
    url = create_presigned_url(
        os.environ.get("DJANGO_AWS_STORAGE_BUCKET_NAME"),
        file_path,
    )

    if url is not None:
        audio_data = {"url": url}

    # Prepare the transcription request options
    options = PrerecordedOptions(
        model="nova-2",
        smart_format=True,
        diarize=True,
        summarize="v2",
    )

    try:
        # Perform transcription and return result
        return dg_client.listen.prerecorded.v("1").transcribe_url(
            audio_data,
            options,
            timeout=300,
        )

    except Exception:
        logging.exception("Error: occured while transcribing an audio.")
        return None


def create_presigned_url(bucket_name, object_name, expiration=3600):
    """Generate a presigned URL to share an S3 object

    :param bucket_name: string
    :param object_name: string
    :param expiration: Time in seconds for the presigned URL to remain valid
    :return: Presigned URL as string. If error, returns None.
    """

    # Generate a presigned URL for the S3 object
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=os.environ.get("DJANGO_AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("DJANGO_AWS_SECRET_ACCESS_KEY"),
    )
    try:
        response = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": object_name},
            ExpiresIn=expiration,
        )
    except ClientError as e:
        return e

    # The response contains the presigned URL
    return response


def extract_paragraphs(paragraphs_data, clip):
    if paragraphs_data:
        outputparagraphs = []
        for paragraph in paragraphs_data:
            # Create Full Transcription for the paragraph
            full_transcription = ""
            sentences = paragraph.get("sentences")
            if sentences:
                for sentence in sentences:
                    full_transcription += sentence.get("text") + " "

            outputparagraphs.append(
                {
                    "clip": clip.id,
                    "end": paragraph.get("end"),
                    "start": paragraph.get("start"),
                    "speaker": paragraph.get("speaker"),
                    "sentences": paragraph.get("sentences"),
                    "full_transcription": full_transcription,
                },
            )

            ClipParagraph.objects.create(
                clip=clip,
                end=paragraph.get("end"),
                start=paragraph.get("start"),
                speaker=paragraph.get("speaker"),
                sentences=paragraph.get("sentences"),
                full_transcription=full_transcription,
            )
    return outputparagraphs


def extract_youtube_video_id(url):
    # Regular expression for extracting the video ID
    patterns = [
        r"(?<=v=)[^&#]+",  # Match for standard URL query
        r"(?<=be/)[^&#]+",  # Match for shorthand youtu.be URL
        r"(?<=embed/)[^&#]+",  # Match for embed URL
        r"(?<=videos/)[^&#]+",  # Match for another type of URL
    ]

    video_id = None

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            video_id = match.group(0)
            break

    return video_id
