import json
import logging
from pathlib import Path

import yt_dlp
from django.conf import settings
from django.core.management.base import BaseCommand
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pytube import YouTube

from word_steno.clips.models import Clip
from word_steno.clips.utils import download_audio
from word_steno.clips.utils import extract_chapters
from word_steno.clips.utils import extract_paragraphs
from word_steno.clips.utils import extract_youtube_video_id
from word_steno.clips.utils import get_description
from word_steno.clips.utils import transcribe_audio

TWO_HOURS = 2 * 60 * 60

DEVELOPER_KEY = settings.GOOGLE_API_KEY
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"


class Command(BaseCommand):
    help = "Download YouTube videos as MP3 files"

    def add_arguments(self, parser):
        parser.add_argument(
            "channel_ids_file",
            type=str,
            help="Path to the file containing channel IDs",
        )

    def handle(self, *args, **options):
        channel_ids_file = Path(options["channel_ids_file"])
        youtube_service = build(
            YOUTUBE_API_SERVICE_NAME,
            YOUTUBE_API_VERSION,
            developerKey=DEVELOPER_KEY,
        )

        channel_ids = self.read_channel_ids(channel_ids_file)
        for channel_identifier in channel_ids:
            video_ids = self.fetch_latest_videos(youtube_service, channel_identifier)
            for video_id in video_ids:
                if self.check_video_exists(video_id):
                    self.download_and_process(youtube_service, video_id)

    def read_channel_ids(self, channel_ids_file):
        with channel_ids_file.open() as file:
            return [line.strip() for line in file if line.strip()]

    def get_channel_id_for_username(self, youtube_service, query):
        try:
            response = (
                youtube_service.search()
                .list(q=query, part="snippet", type="channel", maxResults=1)
                .execute()
            )
        except HttpError as error:
            self.stdout.write(
                self.style.ERROR(
                    f"An error occurred: {error}",
                ),
            )
            return None
        else:
            if response["items"]:
                return response["items"][0]["snippet"]["channelId"]
            return None

    def fetch_latest_videos(self, youtube_service, channel_identifier, max_results=3):
        # Check if the identifier needs username resolution
        if not channel_identifier.startswith("UC"):
            channel_identifier = self.get_channel_id_for_username(
                youtube_service,
                channel_identifier,
            )
            if not channel_identifier:
                return []  # Unable to resolve username to channel ID
        try:
            search_response = (
                youtube_service.search()
                .list(
                    channelId=channel_identifier,
                    part="id,snippet",
                    maxResults=max_results,
                    order="date",
                    type="video",
                )
                .execute()
            )

            return [
                search_result["id"]["videoId"]
                for search_result in search_response.get("items", [])
            ]
        except HttpError as e:
            self.stdout.write(
                self.style.ERROR(
                    f"An HTTP error {e.resp.status} occurred:\n{e.content}",
                ),
            )
            return []

    def check_video_exists(self, video_id):
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

    def download_and_process(self, youtube_service, video_id):
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

            # Modify transcribed data to JSON format
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
