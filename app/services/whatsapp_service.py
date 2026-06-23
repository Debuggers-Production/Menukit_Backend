import requests
from typing import Optional
from app.core.config import get_settings


class WhatsAppClient:
    def __init__(
        self,
        access_token: str=get_settings().WHATSAPP_ACCESS_TOKEN,
        phone_number_id: str=get_settings().WHATSAPP_PHONE_NUMBER_ID,
    ):
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.base_url = f"https://graph.facebook.com/v23.0/{self.phone_number_id}/messages"

    def send_text_message(
        self,
        phone_number: str,
        message: str,
        preview_url: bool = False,
    ) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "text",
            "text": {
                "preview_url": preview_url,
                "body": message,
            },
        }

        response = requests.post(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        print("Status Code:", response.status_code)
        print("Response:", response.text)
        
        response.raise_for_status()
        return response.json()

    def send_template(
        self,
        phone_number: str,
        template_name: str,
        language: str,
        parameters: list[str],
    ) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {
                    "code": language,
                },
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {
                                "type": "text",
                                "text": value,
                            }
                            for value in parameters
                        ],
                    }
                ],
            },
        }

        response = requests.post(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )

        response.raise_for_status()
        return response.json()