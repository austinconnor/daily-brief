import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from dateutil import parser, tz


def log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{timestamp}] {message}", flush=True)


def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Config:
    tz_name: str
    miniflux_url: str
    miniflux_api_token: str
    gemini_api_key: str
    gemini_model: str
    discord_webhook_url: str
    discord_username: str
    run_at_local_time: str
    lookback_hours: int
    max_items: int


PROMPT_HEADER = (
    "You are preparing a concise technical AI daily brief from RSS items. "
    "Prioritize model releases, benchmarks, open-source drops, papers, datasets, "
    "and major funding or infrastructure changes. Avoid hype and fluff. "
    "Deduplicate overlapping stories and group related topics.\n\n"
    "Output exactly with these sections:\n"
    "1) Executive summary (5-10 bullets)\n"
    "2) Notable OSS / Papers (bullets)\n"
    "3) Worth skimming (Title - URL bullets)"
)


def parse_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got: {raw}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got: {value}")
    return value


def load_config() -> Config:
    run_at_local_time = os.getenv("RUN_AT_LOCAL_TIME", "08:00").strip()
    parts = run_at_local_time.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError("RUN_AT_LOCAL_TIME must be in HH:MM format")
    hours, minutes = int(parts[0]), int(parts[1])
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise ValueError("RUN_AT_LOCAL_TIME must be a valid 24-hour HH:MM time")

    return Config(
        tz_name=os.getenv("TZ", "UTC").strip() or "UTC",
        miniflux_url=os.getenv("MINIFLUX_URL", "http://miniflux:8080").rstrip("/"),
        miniflux_api_token=get_required_env("MINIFLUX_API_TOKEN"),
        gemini_api_key=get_required_env("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash",
        discord_webhook_url=get_required_env("DISCORD_WEBHOOK_URL"),
        discord_username=os.getenv("DISCORD_USERNAME", "AI Morning Brief").strip() or "AI Morning Brief",
        run_at_local_time=run_at_local_time,
        lookback_hours=parse_positive_int("LOOKBACK_HOURS", 24),
        max_items=parse_positive_int("MAX_ITEMS", 60),
    )


def get_local_tz(tz_name: str):
    tz_info = tz.gettz(tz_name)
    if tz_info is None:
        log(f"Invalid TZ '{tz_name}', falling back to UTC")
        return timezone.utc
    return tz_info


def seconds_until_run(target_hhmm: str, tz_info) -> int:
    now_local = datetime.now(tz_info)
    hour, minute = [int(part) for part in target_hhmm.split(":", 1)]
    target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now_local >= target:
        target += timedelta(days=1)
    return max(1, int((target - now_local).total_seconds()))


def fetch_recent_unread_entries(config: Config) -> list[dict[str, Any]]:
    endpoint = f"{config.miniflux_url}/v1/entries"
    headers = {"X-Auth-Token": config.miniflux_api_token}
    params = {
        "status": "unread",
        "direction": "desc",
        "order": "published_at",
        "limit": 200,
    }

    response = requests.get(endpoint, headers=headers, params=params, timeout=30)
    response.raise_for_status()

    payload = response.json()
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        raise RuntimeError("Unexpected Miniflux response format: 'entries' is not a list")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.lookback_hours)
    selected: list[dict[str, Any]] = []

    for entry in entries:
        published_raw = entry.get("published_at")
        if not published_raw:
            continue

        try:
            published_dt = parser.isoparse(published_raw)
        except (ValueError, TypeError):
            continue

        if published_dt.tzinfo is None:
            published_dt = published_dt.replace(tzinfo=timezone.utc)
        published_utc = published_dt.astimezone(timezone.utc)

        if published_utc < cutoff:
            continue

        feed = entry.get("feed") or {}
        selected.append(
            {
                "title": (entry.get("title") or "(untitled)").strip(),
                "url": (entry.get("url") or "").strip(),
                "feed_title": (feed.get("title") or "Unknown feed").strip(),
                "published_at": published_utc.isoformat(),
            }
        )

        if len(selected) >= config.max_items:
            break

    return selected


def build_prompt(entries: list[dict[str, Any]]) -> str:
    lines = [PROMPT_HEADER, "", "Source entries:"]
    for index, entry in enumerate(entries, start=1):
        lines.append(
            f"{index}. [{entry['feed_title']}] {entry['title']}\n"
            f"   URL: {entry['url']}\n"
            f"   Published (UTC): {entry['published_at']}"
        )

    return "\n".join(lines)


def call_gemini(config: Config, prompt: str) -> str:
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.gemini_model}:generateContent?key={config.gemini_api_key}"
    )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 900,
        },
    }

    response = requests.post(endpoint, json=payload, timeout=90)
    response.raise_for_status()

    body = response.json()
    candidates = body.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini response has no candidates")

    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    chunks = [part.get("text", "").strip() for part in parts if part.get("text")]
    summary = "\n".join(chunk for chunk in chunks if chunk).strip()
    if not summary:
        raise RuntimeError("Gemini response did not contain summary text")

    return summary


def split_message(text: str, chunk_size: int = 1900) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []

    chunks: list[str] = []
    remaining = cleaned

    while len(remaining) > chunk_size:
        split_at = remaining.rfind("\n", 0, chunk_size)
        if split_at <= 0:
            split_at = chunk_size

        chunk = remaining[:split_at].rstrip()
        if not chunk:
            chunk = remaining[:chunk_size]
            split_at = len(chunk)

        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip("\n")

    if remaining:
        chunks.append(remaining)

    return chunks


def post_to_discord(config: Config, message: str) -> None:
    payload: dict[str, str] = {"content": message}
    if config.discord_username:
        payload["username"] = config.discord_username

    response = requests.post(config.discord_webhook_url, json=payload, timeout=30)
    if response.status_code not in (200, 204):
        raise RuntimeError(f"Discord webhook failed ({response.status_code}): {response.text[:300]}")


def post_message_chunks(config: Config, message: str) -> None:
    for chunk in split_message(message, chunk_size=1900):
        post_to_discord(config, chunk)
        time.sleep(1)


def run_job(config: Config, tz_info) -> None:
    report_date = datetime.now(tz_info).strftime("%Y-%m-%d")
    header = f"**AI Morning Brief** ({report_date})"

    try:
        entries = fetch_recent_unread_entries(config)
    except Exception as exc:
        post_message_chunks(config, f"{header}\n\nError fetching Miniflux entries: {exc}")
        return

    if not entries:
        post_message_chunks(config, f"{header}\n\nNo unread items found in the configured lookback window.")
        return

    try:
        summary = call_gemini(config, build_prompt(entries))
    except Exception as exc:
        post_message_chunks(config, f"{header}\n\nError generating Gemini summary: {exc}")
        return

    post_message_chunks(config, f"{header}\n\n{summary}")


def main() -> None:
    config = load_config()
    tz_info = get_local_tz(config.tz_name)

    log(
        "Daily brief service started "
        f"(run_at={config.run_at_local_time}, tz={config.tz_name}, "
        f"lookback_hours={config.lookback_hours}, max_items={config.max_items})"
    )

    while True:
        wait_seconds = seconds_until_run(config.run_at_local_time, tz_info)
        next_run_at = datetime.now(tz_info) + timedelta(seconds=wait_seconds)
        log(f"Next run scheduled at {next_run_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        time.sleep(wait_seconds)

        log("Running daily brief job")
        try:
            run_job(config, tz_info)
            log("Daily brief job completed")
        except Exception as exc:
            log(f"Unhandled error in daily brief job: {exc}")
            try:
                post_message_chunks(config, f"Daily brief runtime error: {exc}")
            except Exception as discord_exc:
                log(f"Failed to post runtime error to Discord: {discord_exc}")

        time.sleep(60)


if __name__ == "__main__":
    main()
