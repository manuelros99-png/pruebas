#!/usr/bin/env python3
"""
Chat with a YouTube creator based on their transcripts.
Requires running extract.py first to generate channel_data/videos.json

Usage: python chat.py [--data channel_data]
"""

import argparse
import json
import os
import textwrap
from pathlib import Path

import anthropic
import chromadb
from chromadb.utils import embedding_functions


CHUNK_SIZE = 800       # characters per chunk
CHUNK_OVERLAP = 100
TOP_K = 8              # chunks retrieved per query
MODEL = "claude-opus-4-8"


def chunk_text(text: str, video_id: str, title: str) -> list[dict]:
    """Split transcript into overlapping chunks with metadata."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end]
        if chunk.strip():
            chunks.append({
                "text": chunk,
                "video_id": video_id,
                "title": title,
            })
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


def build_index(data_dir: str) -> tuple[chromadb.Collection, dict]:
    videos_path = Path(data_dir) / "videos.json"
    meta_path = Path(data_dir) / "channel_meta.json"

    if not videos_path.exists():
        raise FileNotFoundError(
            f"No videos.json found in {data_dir}. Run extract.py first."
        )

    videos = json.loads(videos_path.read_text())
    channel_meta = {}
    if meta_path.exists():
        channel_meta = json.loads(meta_path.read_text())

    channel_name = channel_meta.get("channel_name", "the creator")

    ef = embedding_functions.DefaultEmbeddingFunction()
    client = chromadb.Client()
    collection = client.get_or_create_collection(
        name="channel", embedding_function=ef
    )

    if collection.count() > 0:
        print(f"Index already loaded ({collection.count()} chunks).")
        return collection, channel_meta

    print("Building search index from transcripts...")
    all_chunks = []
    all_ids = []
    all_metas = []

    for video in videos:
        text = video.get("transcript", "").strip()
        if not text:
            # Fall back to description if no transcript
            text = video.get("description", "").strip()
        if not text:
            continue

        chunks = chunk_text(text, video["id"], video["title"])
        for j, chunk in enumerate(chunks):
            all_ids.append(f"{video['id']}_{j}")
            all_chunks.append(chunk["text"])
            all_metas.append({
                "video_id": video["id"],
                "title": video["title"],
                "url": video.get("url", ""),
                "upload_date": video.get("upload_date", ""),
            })

    # Batch upsert (chromadb limit ~5000 per call)
    batch = 500
    for i in range(0, len(all_ids), batch):
        collection.upsert(
            ids=all_ids[i:i+batch],
            documents=all_chunks[i:i+batch],
            metadatas=all_metas[i:i+batch],
        )
        print(f"  Indexed {min(i+batch, len(all_ids))}/{len(all_ids)} chunks...")

    print(f"Index ready: {collection.count()} chunks from {len(videos)} videos.\n")
    return collection, channel_meta


def retrieve(collection: chromadb.Collection, query: str) -> str:
    results = collection.query(query_texts=[query], n_results=TOP_K)
    docs = results["documents"][0]
    metas = results["metadatas"][0]

    parts = []
    seen_titles = set()
    for doc, meta in zip(docs, metas):
        title = meta.get("title", "")
        url = meta.get("url", "")
        header = f"[{title}]({url})" if title not in seen_titles else ""
        seen_titles.add(title)
        parts.append(f"{header}\n{doc}".strip())

    return "\n\n---\n\n".join(parts)


def build_system_prompt(channel_meta: dict) -> str:
    name = channel_meta.get("channel_name", "the creator")
    desc = channel_meta.get("description", "")
    return textwrap.dedent(f"""
        You are {name}. You speak, think, and respond exactly as {name} does based on their YouTube content.

        Rules:
        - Answer in the same language the user writes in.
        - Use {name}'s vocabulary, tone, expressions, and style as shown in the provided transcripts.
        - Only draw from the context provided. If the answer isn't in the context, say so honestly in character.
        - Do not break character. Never say you are an AI or Claude.
        - Keep responses concise and natural, as if speaking in a video or conversation.

        Channel description: {desc[:500] if desc else "N/A"}
    """).strip()


def chat(data_dir: str) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set the ANTHROPIC_API_KEY environment variable.")
        return

    collection, channel_meta = build_index(data_dir)
    client = anthropic.Anthropic(api_key=api_key)
    system_prompt = build_system_prompt(channel_meta)
    channel_name = channel_meta.get("channel_name", "Creator")
    history = []

    print(f"\n{'='*60}")
    print(f"  Chatting with: {channel_name}")
    print(f"  Type 'exit' or Ctrl+C to quit.")
    print(f"{'='*60}\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            break

        # Retrieve relevant context
        context = retrieve(collection, user_input)

        # Add user message with injected context
        augmented_message = (
            f"[Relevant content from my videos:]\n{context}\n\n"
            f"[Question:] {user_input}"
        )
        history.append({"role": "user", "content": augmented_message})

        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=history,
        )
        answer = response.content[0].text
        history.append({"role": "assistant", "content": answer})

        # Keep only last 10 turns to avoid token overflow
        if len(history) > 20:
            history = history[-20:]

        print(f"\n{channel_name}: {answer}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data", default="channel_data", help="Directory with videos.json"
    )
    args = parser.parse_args()
    chat(args.data)
