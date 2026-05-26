import google.generativeai as genai

from dotenv import load_dotenv

import os


class LLMClient:

    def __init__(self):

        load_dotenv()

        api_key = os.getenv(
            "GEMINI_API_KEY"
        )

        genai.configure(
            api_key=api_key
        )

        self.model = (
            genai.GenerativeModel(
                "gemini-1.5-flash"
            )
        )

    def generate(
        self,
        prompt
    ):

        response = self.model.generate_content(
            prompt
        )

        return response.text