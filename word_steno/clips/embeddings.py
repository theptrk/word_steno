from pgvector.django import L2Distance
from sentence_transformers import SentenceTransformer

# model = SentenceTransformer('all-MiniLM-L6-v2')
model = SentenceTransformer("BAAI/bge-large-en-v1.5")


def embed_transcriptions(queryset):
    print(queryset)
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

    similarities = transcription.objects.order_by(
        L2Distance("embedding", query_embedding),
    )[:top_n]
    return similarities


#     similarities = []
#     for clip_paragraph in queryset:
#         if clip_paragraph.embedding:
#             clip_embedding = np.array(clip_paragraph.embedding)
#             similarity = cosine_similarity([query_embedding], [clip_embedding])[0][0]
#             similarities.append((clip_paragraph, similarity))

#    # Sort by similarity
#     sorted_clips = sorted(similarities, key=lambda x: x[1], reverse=True)

#     # Return top N most similar ClipParagraph instances
#     return [clip for clip, _ in sorted_clips[:top_n]]
