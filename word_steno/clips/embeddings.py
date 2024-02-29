import logging

from django.conf import settings
from openai import OpenAI
from pgvector.django import L2Distance
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("BAAI/bge-large-en-v1.5")

logger = logging.getLogger(__name__)


def embed_transcriptions(queryset):
    for clip_paragraph in queryset:
        # using full_transcription directly:
        embedding = model.encode(
            clip_paragraph.full_transcription,
            convert_to_tensor=False,
        )
        clip_paragraph.embedding = embedding
        clip_paragraph.save()


def search_embeddings(query, transcription, top_n=5):
    query_embedding = model.encode(query, convert_to_tensor=False)

    return transcription.objects.order_by(
        L2Distance("embedding", query_embedding),
    )[:top_n]


def generate_summary_with_prompt(aggregated_text, speakers, topic):
    try:
        client = OpenAI(
            # This is the default and can be omitted
            api_key=settings.OPENAI_API_KEY,
        )

        custom_prompt = (
            f"I have a podcast transcript with speakers {speakers} discussing {topic}. "
            "Each offers unique perspectives.\n\n"
            "I need a summary of their views on {topic}, clearly differentiating speakers. "
            "Format the response as:\n\n"
            "**On Topic: {topic}:**\n"
            "  - **Speaker 1 ([Name]):** [Summary of views on Topic]\n"
            "  - **Speaker 2 ([Name]):** [Summary of views on Topic]\n"
            "  - [Continue for each speaker]\n\n"
            "Summaries should be neutral, highlighting differences in opinions. "
            "Include any direct responses or contradictions.\n\n"
            "The full topic transcription is below:\n\n"
        )

        # Combine the prompt with the aggregated text
        prompt_text = f"{custom_prompt} {aggregated_text}"

        chat_completion = client.chat.completions.create(
            model="gpt-3.5-turbo-0125",
            messages=[
                {"role": "user", "content": prompt_text},
            ],
        )

        return {
            "summary": chat_completion.choices[0].message.content,
            "prompt": prompt_text,
        }
    except Exception as e:
        logging.exception(
            "Exception: generating summary: Generating summary with prompt",
        )
        return e
