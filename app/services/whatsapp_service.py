import json
import logging
import requests
from typing import Optional
from app.core.config import get_settings

logger = logging.getLogger("whatsapp_webhook")


class WhatsAppClient:
    def __init__(
        self,
        access_token: str=get_settings().WHATSAPP_ACCESS_TOKEN,
        phone_number_id: str=get_settings().WHATSAPP_PHONE_NUMBER_ID,
    ):
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.base_url = f"https://graph.facebook.com/v23.0/{self.phone_number_id}/messages"

    def _post(self, payload: dict) -> dict:
        """Internal POST helper with safe error handling and payload logging."""
        formatted_payload = json.dumps(payload, indent=2)
        logger.info(f"📤 Outgoing WhatsApp Payload:\n{formatted_payload}")
        print("📤 [WhatsApp Outgoing Payload]:", formatted_payload)

        response = requests.post(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        
        logger.info(f"📥 WhatsApp Meta API Response ({response.status_code}): {response.text}")
        print(f"📥 [WhatsApp Meta Response {response.status_code}]:", response.text)

        try:
            response.raise_for_status()
            return response.json()
        except Exception as err:
            logger.error(f"WhatsApp API Error ({response.status_code}): {err} | Response: {response.text}")
            print(f"WhatsApp API warning ({response.status_code}): {err}")
            return {"error": str(err), "status_code": response.status_code}

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
        return self._post(payload)

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
        return self._post(payload)

    def send_contest_created_template(
        self,
        phone_number: str,
        shop_name: str,
        contest_type: str,
        reward_value: str,
        contest_url_suffix: str,
        header_image_url: str = "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?w=800&auto=format&fit=crop",
    ) -> dict:
        """
        Sends the 'contest_created_template' WhatsApp template message.

        Header:
          IMAGE parameter (required by Meta template definition)

        Body variables:
          {{1}} = shop_name       (e.g. "Siva Shop")
          {{2}} = contest_type    (e.g. "Drawing")
          {{3}} = reward_value    (e.g. "Free Family Combo")
          {{4}} = url_domain      (e.g. "menukit.debuggers.co.in")

        Dynamic CTA button:
          Base URL: https://menukit.debuggerstechnologies.com
          {{1}} (button suffix) = contest_url_suffix (e.g. "shop/81b1.../contest")
        """
        frontend_url = get_settings().FRONTEND_URL or "https://menukit.debuggerstechnologies.com"
        url_domain = frontend_url.replace("http://", "").replace("https://", "").rstrip("/")
        image_link = header_image_url or "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?w=800&auto=format&fit=crop"
        clean_phone = "".join(filter(str.isdigit, phone_number))

        payload = {
            "messaging_product": "whatsapp",
            "to": clean_phone,
            "type": "template",
            "template": {
                "name": "contest_created_template",
                "language": {
                    "code": "en",
                },
                "components": [
                    {
                        "type": "header",
                        "parameters": [
                            {
                                "type": "image",
                                "image": {
                                    "link": image_link
                                }
                            }
                        ]
                    },
                    {
                        # Body component: 4 text params
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": shop_name},
                            {"type": "text", "text": contest_type},
                            {"type": "text", "text": reward_value},
                            {"type": "text", "text": url_domain},
                        ],
                    },
                    {
                        # Dynamic CTA button — index 0 is the first button
                        "type": "button",
                        "sub_type": "url",
                        "index": "0",
                        "parameters": [
                            {
                                # This appends to the base URL defined in template
                                "type": "text",
                                "text": contest_url_suffix,
                            }
                        ],
                    },
                ],
            },
        }
        return self._post(payload)
