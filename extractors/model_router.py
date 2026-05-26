from ollama import chat

import google.generativeai as genai
import google.api_core.exceptions

from dotenv import load_dotenv

import os
import time


class ModelRouter:

    def __init__(self):

        # =============================================
        # PROVIDER SWITCH (gemini or ollama)
        # =============================================

        self.provider = "gemini"

        # =============================================
        # GEMINI SETUP
        # =============================================

        if self.provider == "gemini":

            load_dotenv()

            api_key = os.getenv(
                "GEMINI_API_KEY"
            )

            genai.configure(
                api_key=api_key
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
        # GEMINI
        # =============================================

        if self.provider == "gemini":

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
        # OLLAMA
        # =============================================

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