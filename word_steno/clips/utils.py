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

from .models import ClipParagraph

TWO_HOURS = 2 * 60 * 60


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

    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    elif len(parts) == 2:
        return parts[0] * 60 + parts[1]
    else:
        return 0  # Return 0 seconds if the format is unexpected


def extract_chapters(description):
    """Extracts chapters and their timestamps (in seconds) from a video description."""
    chapter_regex = re.compile(
        r"(?:\((\d{1,2}:\d{2}(?::\d{2})?)\)|(\d{1,2}:\d{2}(?::\d{2})?))\s*[-–—)]?\s*(.*)",
    )

    chapters = []
    for line in description.split("\n"):
        match = chapter_regex.match(line.strip())
        if match:
            # Choose the first matching group if it captured the timestamp, otherwise use the second
            timestamp_str = match.group(1) if match.group(1) else match.group(2)
            timestamp_seconds = timestamp_to_seconds(timestamp_str)
            title = match.group(3)
            chapters.append({"timestamp": timestamp_seconds, "title": title})

    return chapters


def download_audio(video_url):
    yt = YouTube(video_url)

    # Get the length of the video in seconds
    video_length = yt.length
    if video_length > TWO_HOURS:
        return None

    # Get the title of the video
    video_title = yt.title
    # Get the channel title
    channel_title = yt.author
    # Get the video description
    video_description = yt.description
    # Get the publish date of the video
    publish_date = yt.publish_date

    # Replace problematic characters in the title to make it a valid filename
    # You might need to expand this list based on your requirements
    filename = "".join([c for c in video_title if c.isalpha() or c.isdigit()]).rstrip()

    audio_stream = yt.streams.filter(only_audio=True).first()
    buffer = BytesIO()
    audio_stream.stream_to_buffer(buffer)
    buffer.seek(0)  # Rewind the buffer to the beginning

    ### AWS UPLOAD Error uploading ###
    print(os.environ.get("DJANGO_AWS_STORAGE_BUCKET_NAME"))
    object_name = upload_to_s3(
        buffer, filename, os.environ.get("DJANGO_AWS_STORAGE_BUCKET_NAME")
    )
    print(object_name)

    # Define the download path
    # download_folder = os.path.join(settings.BASE_DIR, 'downloaded_videos')
    # if not os.path.exists(download_folder):
    #     os.makedirs(download_folder)

    # audio_stream.download(output_path=download_folder, filename=f"{filename}.mp3")

    return {
        "video_title": video_title,
        "video_length": video_length,
        "channel_title": channel_title,
        "publish_date": publish_date,
        "video_description": video_description,
        # "storage_path": os.path.join(settings.BASE_DIR, 'downloaded_videos', f"{filename}.mp3")
        "storage_path": f"https://{os.environ.get('DJANGO_AWS_STORAGE_BUCKET_NAME')}.s3.{os.environ.get('DJANGO_AWS_S3_REGION_NAME')}.amazonaws.com/{object_name}",
        "object_name": object_name,
    }


def upload_to_s3(buffer, filename, bucket_name):
    s3 = boto3.client("s3")
    s3.upload_fileobj(buffer, bucket_name, f"clips/{filename}.mp3")
    return f"clips/{filename}.mp3"


def transcribe_audio(file_path):
    # Initialize the Deepgram SDK
    dg_client = DeepgramClient()

    url = create_presigned_url(
        os.environ.get("DJANGO_AWS_STORAGE_BUCKET_NAME"), file_path
    )
    print(url)
    if url is not None:
        audio_data = {"url": url}

    # Open the audio file in binary mode
    # with open(file_path, 'rb') as audio_file:
    #     audio_data = audio_file.read()

    # payload: FileSource = {
    #     "buffer": audio_data,
    # }

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

        # Since the SDK is asynchronous, make sure to await the response if you're using async views
        # response = await dg_client.transcription.prerecorded(audio_data, options)
    except Exception as e:
        return print(f"An error occurred during transcription: {e}")


def create_presigned_url(bucket_name, object_name, expiration=3600):
    """Generate a presigned URL to share an S3 object

    :param bucket_name: string
    :param object_name: string
    :param expiration: Time in seconds for the presigned URL to remain valid
    :return: Presigned URL as string. If error, returns None.
    """

    print(bucket_name, object_name)

    # Generate a presigned URL for the S3 object
    s3_client = boto3.client("s3")
    try:
        response = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": object_name},
            ExpiresIn=expiration,
        )
    except ClientError as e:
        logging.exception(e)
        return None

    # The response contains the presigned URL
    return response


def extract_paragraphs(paragraphs_data, clip):
    if paragraphs_data:
        for paragraph in paragraphs_data:
            # Create Full Transcription for the paragraph
            full_transcription = ""
            sentences = paragraph.get("sentences")
            if sentences:
                for sentence in sentences:
                    print(sentence.get("text"), sentence)
                    full_transcription += sentence.get("text") + " "

            ClipParagraph.objects.create(
                clip=clip,
                end=paragraph.get("end"),
                start=paragraph.get("start"),
                speaker=paragraph.get("speaker"),
                sentences=paragraph.get("sentences"),
                full_transcription=full_transcription,
            )


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


def check_url_exists(existing_urls, new_url):
    # Extract the video ID from the new URL
    new_video_id = extract_youtube_video_id(new_url)

    # Iterate through the list of existing URLs and extract their video IDs
    for existing_url in existing_urls:
        existing_video_id = extract_youtube_video_id(existing_url.url)
        if new_video_id == existing_video_id:
            return existing_url  # Found a matching video ID in the list

    return None  # No matching video ID found in the list
