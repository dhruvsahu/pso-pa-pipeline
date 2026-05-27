from ollama import chat

import google.generativeai as genai
import google.api_core.exceptions

from groq import Groq

from dotenv import load_dotenv

import os
import time


class ModelRouter:

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
        # Model: llama-3.1-8b-instant
        # =============================================

        if self.provider == "groq":

            self.groq_client = Groq(
                api_key=groq_key
            )

            self.groq_model = "llama-3.1-8b-instant"

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
        # GROQ  (llama-3.1-8b-instant)
        # =============================================

        if self.provider == "groq":

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

                    return (
                        response.choices[0]
                        .message.content
                    )

                except Exception as e:

                    err = str(e).lower()

                    if (
                        "rate_limit" in err
                        or "429" in err
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