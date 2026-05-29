from collections import deque
from ollama import chat

import google.generativeai as genai
import google.api_core.exceptions

from groq import Groq

from dotenv import load_dotenv

import os
import time
import threading


# =====================================================
# PROCESS-WIDE SINGLETON
# The rolling-window throttlers are only meaningful if ONE
# router instance is shared by all extractors in a process
# (ADR-005). Each extractor previously built its own
# ModelRouter(), giving N independent windows and an
# effective rate ~N× the configured target. get_router()
# guarantees a single shared instance (double-checked lock).
# =====================================================

_ROUTER_SINGLETON = None
_ROUTER_SINGLETON_LOCK = threading.Lock()


def get_router():
    """Return the process-wide shared ModelRouter, creating it once."""
    global _ROUTER_SINGLETON
    if _ROUTER_SINGLETON is None:
        with _ROUTER_SINGLETON_LOCK:
            if _ROUTER_SINGLETON is None:
                _ROUTER_SINGLETON = ModelRouter()
    return _ROUTER_SINGLETON


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

        # Serializes all throttle-window read-modify-write so concurrent
        # threads (Flask threaded=True) cannot both observe headroom and
        # overshoot the rate target, or corrupt the window during the
        # Groq estimate→actual replacement.
        self._throttle_lock = threading.Lock()
        self._groq_uid = 0

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

        # =============================================
        # GROQ SETUP
        # Model: llama-3.3-70b-versatile (12K TPM)
        # Token-aware throttle: rolling deque of
        # (timestamp, tokens) over the last 60s.
        # =============================================

        if self.provider == "groq":

            self.groq_client = Groq(
                api_key=groq_key
            )

            self.groq_model = "llama-3.3-70b-versatile"

            # Each entry: (unix_timestamp, token_count, uid)
            # uid lets the post-call update replace exactly this call's
            # estimate with its actual usage, even under concurrency.
            self._groq_token_window = deque()

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
    # Gemini path uses its own RPM throttle below.
    # =================================================

    def _groq_throttle(self, tokens_about_to_use):
        """
        Call BEFORE each Groq API request.
        Evicts entries older than 60s, then checks if
        adding `tokens_about_to_use` would exceed the
        TPM target.  Sleeps the minimum required time
        if it would, then records the call.

        Returns a unique id (uid) identifying the window entry
        recorded for this call, so the caller can later replace
        the estimate with the actual token usage.

        The window read-modify-write runs under self._throttle_lock;
        the lock is RELEASED while sleeping so other threads can
        make progress / age out entries.
        """

        window = self._groq_token_window

        while True:

            with self._throttle_lock:

                now = time.time()

                # Drop entries outside the 60s window
                while (
                    window
                    and now - window[0][0] >= 60
                ):
                    window.popleft()

                tokens_in_window = sum(
                    t for _, t, _ in window
                )

                headroom = (
                    self.GROQ_TPM_TARGET
                    - tokens_in_window
                )

                if tokens_about_to_use <= headroom:
                    # Safe to proceed — record with a unique id
                    self._groq_uid += 1
                    uid = self._groq_uid
                    window.append(
                        (now, tokens_about_to_use, uid)
                    )
                    return uid

                # Not enough headroom — calculate minimum
                # sleep to free up space as old entries age out
                oldest_ts = window[0][0]
                sleep_needed = (
                    oldest_ts + 60 - now + 0.5
                )

                print(
                    f"[GROQ THROTTLE] "
                    f"{tokens_in_window} tokens used "
                    f"in last 60s "
                    f"(target {self.GROQ_TPM_TARGET}) — "
                    f"waiting {sleep_needed:.1f}s"
                )

            # Released the lock before sleeping
            time.sleep(max(sleep_needed, 1))

    def _groq_record_actual(self, uid, actual_tokens):
        """
        Replace the estimate recorded under `uid` with the actual token
        usage, identifying the entry by uid (never by position or by
        matching the estimate value) so concurrent calls cannot corrupt
        each other's accounting.
        """
        with self._throttle_lock:
            window = self._groq_token_window
            for i, (ts, _tok, u) in enumerate(window):
                if u == uid:
                    window[i] = (ts, actual_tokens, u)
                    return

    # =================================================
    # GEMINI RPM-AWARE THROTTLE
    # Tracks request timestamps in the last 60s and
    # sleeps only as long as needed to stay under
    # GEMINI_RPM_TARGET before each API call.
    # Replaces the hardcoded sleep in the pipeline.
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

                # Drop entries outside the 60s window
                while (
                    window
                    and now - window[0] >= 60
                ):
                    window.popleft()

                if len(window) < self.GEMINI_RPM_TARGET:
                    # Safe to proceed — record this request
                    window.append(now)
                    return

                # Too many requests in the last 60s —
                # sleep until the oldest one ages out
                oldest = window[0]
                sleep_needed = oldest + 60 - now + 0.5

                print(
                    f"[GEMINI THROTTLE] "
                    f"{len(window)} requests in last 60s "
                    f"(target {self.GEMINI_RPM_TARGET} RPM) — "
                    f"waiting {sleep_needed:.1f}s"
                )

            # Released the lock before sleeping
            time.sleep(max(sleep_needed, 1))

    # =================================================
    # MODEL SELECTION
    # =================================================

    def select_model(
        self,
        context
    ):

        context_length = len(context)

        if context_length > 12000:

            return "qwen2.5:7b"

        return "qwen2.5:7b"

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

            groq_uid = self._groq_throttle(estimated_tokens)

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

                    # Replace this call's estimate with the actual
                    # usage (identified by uid, lock-guarded) so the
                    # window stays accurate and concurrency-safe.
                    actual_tokens = (
                        response.usage.total_tokens
                    )
                    self._groq_record_actual(groq_uid, actual_tokens)

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

            model = self.select_model(
                context
            )

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
