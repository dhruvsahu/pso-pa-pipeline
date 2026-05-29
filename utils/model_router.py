import threading
import uuid
from collections import deque
from ollama import chat

import google.generativeai as genai
import google.api_core.exceptions

from groq import Groq

from dotenv import load_dotenv

import os
import time


class ModelRouter:

    # Groq TPM ceiling for llama-3.3-70b-versatile
    GROQ_TPM_LIMIT = 12000

    # Safety margin — target 90% of limit so we never
    # sit right on the edge
    GROQ_TPM_TARGET = int(GROQ_TPM_LIMIT * 0.90)

    # Gemini RPM ceiling (free tier: 15 RPM)
    # Target 80% so we never sit right on the edge
    GEMINI_RPM_LIMIT = 15
    GEMINI_RPM_TARGET = int(GEMINI_RPM_LIMIT * 0.80)  # 12

    def __init__(self):

        load_dotenv()

        # =============================================
        # AUTO-DETECT PROVIDER FROM ENV
        # Priority: GROQ_API_KEY → GEMINI_API_KEY → ollama
        # Reviewers: add GROQ_API_KEY to .env — no code
        # changes needed.
        # =============================================

        groq_key = os.getenv("GROQ_API_KEY")
        gemini_key = os.getenv("GEMINI_API_KEY")

        if groq_key:
            self.provider = "groq"
        elif gemini_key:
            self.provider = "gemini"
        else:
            self.provider = "ollama"

        print(f"[MODEL ROUTER] Provider: {self.provider}")

        # Single lock protecting ALL throttle windows in this instance
        self._throttle_lock = threading.Lock()

        # =============================================
        # GROQ SETUP
        # Model: llama-3.3-70b-versatile (12K TPM)
        # Token-aware throttle: list of
        # (timestamp, tokens, call_id) over the last 60s.
        # List (not deque) so entries can be replaced by call_id.
        # =============================================

        if self.provider == "groq":

            self.groq_client = Groq(
                api_key=groq_key
            )

            self.groq_model = "llama-3.3-70b-versatile"

            # Each entry: (unix_timestamp, token_count, call_id)
            self._groq_token_window = []

        # =============================================
        # GEMINI SETUP
        # =============================================

        elif self.provider == "gemini":

            genai.configure(
                api_key=gemini_key
            )

            self.gemini_model = (

                genai.GenerativeModel(
                    "gemini-3.1-flash-lite"
                )
            )

            # Each entry: unix timestamp of a completed request
            self._gemini_rpm_window = deque()

    # =================================================
    # GROQ TOKEN-AWARE THROTTLE
    # Tracks tokens used in the last 60s and sleeps
    # only as long as needed to stay under GROQ_TPM_TARGET.
    # Returns a call_id used to replace the estimate with
    # actual usage after the response arrives.
    # Lock is held only during read-modify-write; released
    # while sleeping so other threads can make progress.
    # =================================================

    def _groq_throttle(self, tokens_about_to_use):
        """
        Call BEFORE each Groq API request.
        Evicts entries older than 60s, checks headroom, sleeps
        if needed, then records the call.
        Returns a call_id for the matching _groq_update_actual call.
        """
        call_id = str(uuid.uuid4())

        while True:
            with self._throttle_lock:
                now = time.time()

                # Evict entries outside the 60s window
                self._groq_token_window = [
                    e for e in self._groq_token_window
                    if now - e[0] < 60
                ]

                tokens_in_window = sum(
                    e[1] for e in self._groq_token_window
                )
                headroom = self.GROQ_TPM_TARGET - tokens_in_window

                if tokens_about_to_use <= headroom:
                    # Safe to proceed — record with call_id
                    self._groq_token_window.append(
                        (now, tokens_about_to_use, call_id)
                    )
                    return call_id

                # Need to sleep — calculate minimum wait
                oldest_ts = self._groq_token_window[0][0]
                sleep_needed = oldest_ts + 60 - now + 0.5

            # Sleep OUTSIDE the lock so other threads aren't blocked
            print(
                f"[GROQ THROTTLE] "
                f"{tokens_in_window} tokens used in last 60s "
                f"(target {self.GROQ_TPM_TARGET}) — "
                f"waiting {sleep_needed:.1f}s"
            )
            time.sleep(max(sleep_needed, 1))

    def _groq_update_actual(self, call_id, actual_tokens):
        """
        Replace the estimated token count for `call_id` with the
        actual usage returned by the API.  Identified by call_id,
        not by position or value, so concurrent calls never collide.
        """
        with self._throttle_lock:
            now = time.time()
            for i, entry in enumerate(self._groq_token_window):
                if entry[2] == call_id:
                    self._groq_token_window[i] = (now, actual_tokens, call_id)
                    return

    # =================================================
    # GEMINI RPM-AWARE THROTTLE
    # Tracks request timestamps in the last 60s and
    # sleeps only as long as needed to stay under
    # GEMINI_RPM_TARGET before each API call.
    # Lock held only during read-modify-write; released
    # while sleeping.
    # =================================================

    def _gemini_throttle(self):
        """
        Call BEFORE each Gemini request.
        Evicts timestamps older than 60s, then waits
        if the rolling count would exceed RPM_TARGET.
        Records the timestamp after proceeding.
        """
        window = self._gemini_rpm_window

        while True:
            with self._throttle_lock:
                now = time.time()

                # Evict entries outside the 60s window
                while window and now - window[0] >= 60:
                    window.popleft()

                if len(window) < self.GEMINI_RPM_TARGET:
                    # Safe to proceed — record this request
                    window.append(now)
                    return

                # Too many requests — calculate minimum wait
                oldest = window[0]
                sleep_needed = oldest + 60 - now + 0.5

            # Sleep OUTSIDE the lock
            print(
                f"[GEMINI THROTTLE] "
                f"{len(window)} requests in last 60s "
                f"(target {self.GEMINI_RPM_TARGET} RPM) — "
                f"waiting {sleep_needed:.1f}s"
            )
            time.sleep(max(sleep_needed, 1))

    # =================================================
    # GENERATE
    # =================================================

    def generate(
        self,
        prompt,
        context=""
    ):

        # =============================================
        # GROQ  (llama-3.3-70b-versatile, 12K TPM)
        # Token-aware throttle runs before each call.
        # Actual token usage is recorded after the
        # response arrives so the window stays accurate.
        # =============================================

        if self.provider == "groq":

            # Estimate prompt tokens before the call
            # (~4 chars per token is a safe approximation)
            estimated_tokens = len(prompt) // 4 + 300

            call_id = self._groq_throttle(estimated_tokens)

            print(
                f"[LLM] Using Groq: {self.groq_model}"
            )

            max_retries = 6
            wait = 30

            for attempt in range(max_retries):

                try:

                    response = (
                        self.groq_client.chat.completions.create(
                            model=self.groq_model,
                            messages=[
                                {
                                    "role": "user",
                                    "content": prompt
                                }
                            ],
                            temperature=0.0
                        )
                    )

                    # Replace the estimate with actual usage
                    # identified by call_id — safe under threads
                    actual_tokens = response.usage.total_tokens
                    self._groq_update_actual(call_id, actual_tokens)

                    print(
                        f"[GROQ TOKENS] {actual_tokens} "
                        f"tokens used this call"
                    )

                    return (
                        response.choices[0]
                        .message.content
                    )

                except Exception as e:

                    err = str(e).lower()

                    if (
                        "rate_limit" in err
                        or "429" in err
                        or "tokens per minute" in err
                    ):

                        if attempt == max_retries - 1:
                            raise

                        print(
                            f"[RATE LIMIT] Groq 429 — "
                            f"waiting {wait}s "
                            f"(attempt {attempt + 1}"
                            f"/{max_retries})"
                        )

                        time.sleep(wait)
                        wait *= 2

                    else:
                        raise

        # =============================================
        # GEMINI
        # =============================================

        elif self.provider == "gemini":

            print(
                "[LLM] Using Gemini"
            )

            # RPM-aware throttle — sleeps only as long
            # as needed, replaces fixed pipeline sleeps
            self._gemini_throttle()

            max_retries = 6
            wait = 30

            for attempt in range(max_retries):

                try:

                    response = (
                        self.gemini_model.generate_content(
                            prompt
                        )
                    )

                    return response.text

                except google.api_core.exceptions.ResourceExhausted:

                    if attempt == max_retries - 1:
                        raise

                    print(
                        f"[RATE LIMIT] Gemini 429 — "
                        f"waiting {wait}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )

                    time.sleep(wait)
                    wait *= 2

        # =============================================
        # OLLAMA  (local fallback)
        # =============================================

        else:

            # qwen2.5:7b for all context lengths
            model = "qwen2.5:7b"

            print(
                f"[LLM] Using Ollama: {model}"
            )

            response = chat(

                model=model,

                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )

            return response.message.content


# =================================================
# PROCESS-WIDE SINGLETON ACCESSOR
# All extractors call get_router() instead of
# ModelRouter() so there is exactly one throttle
# window per process regardless of how many
# extractor instances are created.
# Double-checked locking is safe here because
# _INSTANCE is only ever set once (None → instance).
# =================================================

_INSTANCE: "ModelRouter | None" = None
_INSTANCE_LOCK = threading.Lock()


def get_router() -> ModelRouter:
    """Return the process-wide shared ModelRouter instance."""
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = ModelRouter()
    return _INSTANCE
