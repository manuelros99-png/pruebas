#!/usr/bin/env python3
"""
Extract all transcripts and metadata from a YouTube channel.
Usage: python extract.py <channel_url_or_handle>
Examples:
  python extract.py https://www.youtube.com/@MrBeast
  python extract.py https://www.youtube.com/channel/UCX6OQ3DkcsbYNE6H8uQQuVA
"""

import json
import os
import re
import sys
from pathlib import Path

import yt_dlp


def sanitize(text: str) -> str:
    return re.sub(r"[^\w\s-]", "", text).strip()


def extract_channel(channel_url: str, output_dir: str = "channel_data") -> None:
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    print(f"Fetching video list from: {channel_url}")

    # First pass: get all video IDs and metadata
    ydl_opts_list = {
        "quiet": True,
        "extract_flat": True,
        "playlist_end": 500,  # cap at 500 videos
    }

    with yt_dlp.YoutubeDL(ydl_opts_list) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    if not info:
        print("ERROR: Could not fetch channel info.")
        sys.exit(1)

    channel_name = info.get("channel") or info.get("uploader") or "unknown_channel"
    entries = info.get("entries") or []
    print(f"Channel: {channel_name} — {len(entries)} videos found")

    channel_meta = {
        "channel_name": channel_name,
        "channel_url": channel_url,
        "video_count": len(entries),
        "description": info.get("description", ""),
    }
    (output_path / "channel_meta.json").write_text(
        json.dumps(channel_meta, ensure_ascii=False, indent=2)
    )

    # Second pass: download subtitles/transcripts per video
    ydl_opts_subs = {
        "quiet": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["es", "en"],  # prefer Spanish, fallback English
        "subtitlesformat": "json3",
        "outtmpl": str(output_path / "%(id)s.%(ext)s"),
        "ignoreerrors": True,
    }

    videos_data = []
    failed = []

    with yt_dlp.YoutubeDL(ydl_opts_subs) as ydl:
        for i, entry in enumerate(entries, 1):
            video_id = entry.get("id")
            if not video_id:
                continue

            print(f"[{i}/{len(entries)}] {entry.get('title', video_id)[:60]}")

            try:
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                vinfo = ydl.extract_info(video_url, download=True)
                if not vinfo:
                    failed.append(video_id)
                    continue

                # Read subtitle file if it was written
                transcript_text = ""
                for lang in ["es", "en"]:
                    sub_file = output_path / f"{video_id}.{lang}.json3"
                    if sub_file.exists():
                        transcript_text = _parse_json3_subtitles(sub_file)
                        sub_file.unlink()  # clean up raw sub file
                        break

                video_record = {
                    "id": video_id,
                    "title": vinfo.get("title", ""),
                    "description": (vinfo.get("description") or "")[:2000],
                    "upload_date": vinfo.get("upload_date", ""),
                    "duration": vinfo.get("duration", 0),
                    "view_count": vinfo.get("view_count", 0),
                    "tags": vinfo.get("tags") or [],
                    "transcript": transcript_text,
                    "url": video_url,
                }
                videos_data.append(video_record)

            except Exception as e:
                print(f"  WARNING: {e}")
                failed.append(video_id)

    # Save all videos to a single JSON file
    out_file = output_path / "videos.json"
    out_file.write_text(json.dumps(videos_data, ensure_ascii=False, indent=2))

    with_transcript = sum(1 for v in videos_data if v["transcript"])
    print(f"\nDone! {len(videos_data)} videos saved to {out_file}")
    print(f"  With transcript: {with_transcript}")
    print(f"  Without transcript: {len(videos_data) - with_transcript}")
    if failed:
        print(f"  Failed to fetch: {len(failed)}")

    # Clean up any leftover subtitle files
    for f in output_path.glob("*.json3"):
        f.unlink()


def _parse_json3_subtitles(path: Path) -> str:
    """Convert YouTube json3 subtitle format to plain text."""
    try:
        data = json.loads(path.read_text())
        parts = []
        for event in data.get("events", []):
            segs = event.get("segs")
            if not segs:
                continue
            text = "".join(s.get("utf8", "") for s in segs).strip()
            if text and text != "\n":
                parts.append(text)
        return " ".join(parts)
    except Exception:
        return ""


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    extract_channel(sys.argv[1], output_dir="channel_data")
