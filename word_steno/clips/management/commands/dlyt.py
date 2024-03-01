import json
import logging
from pathlib import Path

import yt_dlp
from django.core.management.base import BaseCommand
from pytube import YouTube

from word_steno.clips.models import Clip
from word_steno.clips.utils import download_audio
from word_steno.clips.utils import extract_chapters
from word_steno.clips.utils import extract_paragraphs
from word_steno.clips.utils import extract_youtube_video_id
from word_steno.clips.utils import get_description
from word_steno.clips.utils import transcribe_audio

TWO_HOURS = 2 * 60 * 60


class Command(BaseCommand):
    help = "Download YouTube videos as MP3 files"

    def add_arguments(self, parser):
        parser.add_argument(
            "video_ids_file",
            type=str,
            help="Path to the file containing video IDs",
        )

    def handle(self, *args, **options):
        video_ids_file = Path(options["video_ids_file"])

        # Function to check if a YouTube video exists
        def check_video_exists(video_id):
            with yt_dlp.YoutubeDL({"quiet": True, "ignoreerrors": True}) as ydl:
                info_dict = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={video_id}",
                    download=False,
                )
                if info_dict:
                    return True

                self.stdout.write(
                    self.style.ERROR(
                        f"Video {video_id} does not exist or is unavailable.",
                    ),
                )
                return False

        # Function to download YouTube video as audio
        def download(video_id):
            try:
                video_url = f"https://www.youtube.com/watch?v={video_id}"

                if not video_url:
                    self.stdout.write(self.style.ERROR("No URL provided"))
                    return

                # Initialize video url
                yt = YouTube(video_url)
                if yt.length > TWO_HOURS:
                    self.stdout.write(
                        self.style.ERROR(
                            "Youtube Video is greater than 2 hours. Please use a shorter video.",
                        ),
                    )
                    return

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
                    self.stdout.write(
                        self.style.ERROR("Youtube Video is already uploaded."),
                    )
                    return

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

            except Exception as e:
                logging.exception(
                    "Exception: download POST: downloading, transcribing and saving the clip.",
                )
                self.stdout.write(self.style.ERROR(f"An error occurred: {e!s}"))

        # Main script logic
        with video_ids_file.open() as file:
            for line in file:
                video_id = line.strip()
                if video_id and check_video_exists(video_id):
                    download(video_id)
