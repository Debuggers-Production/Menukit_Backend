"""Gemini AI Service for parsing menus."""

import json
import asyncio
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List, Optional
from app.core.config import get_settings

settings = get_settings()

class ExtractedMenuItem(BaseModel):
    category_name: str = Field(description="Name of the category this item belongs to")
    name: str = Field(description="Name of the menu item")
    description: Optional[str] = Field(description="Description of the menu item, ingredients, etc.")
    price: float = Field(description="Price of the item as a number")
    food_type: str = Field(description="One of: 'veg', 'non-veg', 'egg', 'drink'")

class ExtractedMenu(BaseModel):
    items: List[ExtractedMenuItem] = Field(description="List of all extracted menu items")

class GeminiService:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        else:
            self.client = None

    async def parse_menu_file(self, file_bytes: bytes, mime_type: str) -> List[dict]:
        """Parse a menu image or PDF and extract items using Gemini with retry logic."""
        if not self.client:
            raise ValueError("GEMINI_API_KEY is not configured")

        prompt = """
        Analyze this restaurant menu. Extract all the categories and menu items.
        For each menu item, extract:
        - The category it belongs to (e.g. 'Starters', 'Main Course', 'Beverages')
        - The name of the item
        - The description (if any)
        - The price (extract the numeric value)
        - The food_type based on the name or description. Use 'drink' for beverages/liquids. Use 'veg' for vegetarian items, 'non-veg' for meat/seafood, and 'egg' if it contains egg but no meat. If unsure, default to 'veg'.

        Return the data as a structured JSON array of items.
        """

        RETRY_DELAYS = [5, 15, 30]  # seconds to wait before each retry attempt
        last_error = None

        for attempt, delay in enumerate(RETRY_DELAYS, start=1):
            try:
                response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                    contents=[
                        types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                        prompt
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=ExtractedMenu,
                        temperature=0.1
                    ),
                )

                data = json.loads(response.text)
                return data.get("items", [])

            except Exception as e:
                last_error = e
                error_str = str(e)
                is_transient = any(code in error_str for code in ["429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE"])
                if is_transient and attempt < len(RETRY_DELAYS):
                    await asyncio.sleep(delay)
                    continue
                raise Exception(f"Failed to parse menu with Gemini: {error_str}")

        raise Exception(f"Failed to parse menu with Gemini after {len(RETRY_DELAYS)} retries: {str(last_error)}")
