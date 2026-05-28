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

            # Each entry: (unix_timestamp, token_count)
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

    # =================================================
    # GROQ TOKEN-AWARE THROTTLE
    # Tracks tokens used in the last 60s and sleeps
    # only as long as needed to stay under GROQ_TPM_TARGET.
    # Gemini and Ollama paths never touch this.
    # =================================================

    def _groq_throttle(self, tokens_about_to_use):
        """
        Call BEFORE each Groq API request.
        Evicts entries older than 60s, then checks if
        adding `tokens_about_to_use` would exceed the
        TPM target.  Sleeps the minimum required time
        if it would, then records the call.
        """

        window = self._groq_token_window

        while True:

            now = time.time()

            # Drop entries outside the 60s window
            while (
                window
                and now - window[0][0] >= 60
            ):
                window.popleft()

            tokens_in_window = sum(
                t for _, t in window
            )

            headroom = (
                self.GROQ_TPM_TARGET
                - tokens_in_window
            )

            if tokens_about_to_use <= headroom:
                # Safe to proceed
                window.append(
                    (now, tokens_about_to_use)
                )
                return

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

            self._groq_throttle(estimated_tokens)

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

                    # Replace the estimate with actual
                    # usage so the window stays accurate
                    actual_tokens = (
                        response.usage.total_tokens
                    )
                    now = time.time()
                    # Pop the estimate entry we added
                    # and replace with actual
                    window = self._groq_token_window
                    if window and window[-1][1] == estimated_tokens:
                        window.pop()
                    window.append((now, actual_tokens))

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
