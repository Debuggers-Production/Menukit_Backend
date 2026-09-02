import json
import logging
import re
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

    @staticmethod
    def _clean_param(text: Optional[str], default: str = "") -> str:
        """
        Sanitizes template text parameter to satisfy Meta WhatsApp API constraints:
        - No newlines (\r, \n) or tabs (\t)
        - No more than 4 consecutive spaces
        """
        if not text:
            return default
        cleaned = re.sub(r'[\r\n]+', ' ', str(text))
        cleaned = re.sub(r'[\t]+', ' ', cleaned)
        cleaned = re.sub(r' {2,}', ' ', cleaned)
        return cleaned.strip() or default


    def _post(self, payload: dict) -> dict:
        """Internal POST helper with safe error handling and payload logging."""
        formatted_payload = json.dumps(payload, indent=2)
        logger.info(f"📤 Outgoing WhatsApp Payload:\n{formatted_payload}")
        try:
            print("📤 [WhatsApp Outgoing Payload]:", formatted_payload)
        except Exception:
            print("[WhatsApp Outgoing Payload]:", formatted_payload.encode('ascii', 'replace').decode('ascii'))

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
        try:
            print(f"📥 [WhatsApp Meta Response {response.status_code}]:", response.text)
        except Exception:
            print(f"[WhatsApp Meta Response {response.status_code}]:", response.text.encode('ascii', 'replace').decode('ascii'))

        try:
            response.raise_for_status()
            return response.json()
        except Exception as err:
            logger.error(f"WhatsApp API Error ({response.status_code}): {err} | Response: {response.text}")
            try:
                print(f"WhatsApp API warning ({response.status_code}): {err}")
            except Exception:
                pass
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
        header_image_url: str = "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?fm=jpg&w=800&q=90",
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
        full_contest_url = f"{frontend_url.rstrip('/')}/{contest_url_suffix.lstrip('/')}"
        image_link = header_image_url or "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?fm=jpg&w=800&q=90"
        # image_link = "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?fm=jpg&w=800&q=90"
        clean_phone = "".join(filter(str.isdigit, phone_number))
        
        formatted_contest_type = f"{str(contest_type).capitalize()} Contest"

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
                            {"type": "text", "text": formatted_contest_type},
                            {"type": "text", "text": reward_value},
                            {"type": "text", "text": full_contest_url},
                        ],
                    },
                    {
                        # Dynamic CTA button — index 0 is the first button
                        "type": "button",
                        "sub_type": "url",
                        "index": "0",
                        "parameters": [
                            {
                                "type": "text",
                                "text": contest_url_suffix,
                            }
                        ],
                    },
                ],
            },
        }
        return self._post(payload)

    def send_customer_credit_refund_template(
        self,
        phone_number: str,
        customer_name: str,
        contest_title: str,
        shop_name: str,
        cancel_reason: str,
        contest_description: str,
        reward_value: str,
    ) -> dict:
        """
        Sends the 'customer_credid_refund_template' WhatsApp template message.
        """
        clean_phone = "".join(filter(str.isdigit, phone_number))

        payload = {
            "messaging_product": "whatsapp",
            "to": clean_phone,
            "type": "template",
            "template": {
                "name": "customer_credid_refund_template",
                "language": {
                    "code": "en",
                },
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": customer_name},
                            {"type": "text", "text": contest_title},
                            {"type": "text", "text": shop_name},
                            {"type": "text", "text": cancel_reason},
                            {"type": "text", "text": contest_description},
                            {"type": "text", "text": reward_value},
                        ],
                    }
                ],
            },
        }
        return self._post(payload)

    def send_order_create_template(
        self,
        phone_number: str,
        customer_name: str,
        shop_name: str,
        bill_id: str,
        amount_paid: str,
        customer_url: str = "https://menukit.debuggerstechnologies.com/customer/",
    ) -> dict:
        """
        Sends the 'menukit_order_created' WhatsApp template message.

        Body variables:
          {{1}} = customer_name (e.g. "Siva")
          {{2}} = shop_name     (e.g. "Siva Hotel")
          {{3}} = bill_id       (e.g. "1234566")
          {{4}} = amount_paid   (e.g. "₹1000")
          {{5}} = customer_url  (e.g. "https://menukit.debuggerstechnologies.com/customer/")
        """
        clean_phone = "".join(filter(str.isdigit, str(phone_number)))
        if len(clean_phone) == 10:
            clean_phone = f"91{clean_phone}"

        payload = {
            "messaging_product": "whatsapp",
            "to": clean_phone,
            "type": "template",
            "template": {
                "name": "menukit_order_created",
                "language": {
                    "code": "en",
                },
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": self._clean_param(customer_name, "Customer")},
                            {"type": "text", "text": self._clean_param(shop_name, "Restaurant")},
                            {"type": "text", "text": self._clean_param(str(bill_id))},
                            {"type": "text", "text": self._clean_param(str(amount_paid))},
                            {"type": "text", "text": self._clean_param(customer_url, "https://menukit.debuggerstechnologies.com/customer/")},
                        ],

                    }
                ],
            },
        }
        return self._post(payload)

    def send_user_campaign_template(
        self,
        phone_number: str,
        customer_name: str,
        shop_name: str,
        custom_message: str,
        shop_id: str,
        header_image_url: Optional[str] = None,
    ) -> dict:
        """
        Sends the 'menukit_user_template' WhatsApp marketing broadcast template message.

        Header:
          IMAGE parameter (custom URL or default fallback banner)

        Body variables:
          {{1}} = customer_name (e.g. "Siva")
          {{2}} = shop_name     (e.g. "Siva Hotel")
          {{3}} = custom_message (e.g. "We are currently providing a 50% off 🙌")

        CTA Button:
          'Visit Shop' button with shop URL suffix
        """
        clean_phone = "".join(filter(str.isdigit, str(phone_number)))
        if len(clean_phone) == 10:
            clean_phone = f"91{clean_phone}"

        # Default fallback image if none provided
        image_link = (
            header_image_url
            if header_image_url and header_image_url.strip().startswith("http")
            else "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?fm=jpg&w=800&q=90"
        )

        button_suffix = f"shop/{str(shop_id)}"

        payload = {
            "messaging_product": "whatsapp",
            "to": clean_phone,
            "type": "template",
            "template": {
                "name": "menukit_user_template",
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
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": self._clean_param(customer_name, "Valued Customer")},
                            {"type": "text", "text": self._clean_param(shop_name, "Restaurant")},
                            {"type": "text", "text": self._clean_param(custom_message, "Special offers and updates for you!")},
                        ],
                    },

                    {
                        "type": "button",
                        "sub_type": "url",
                        "index": "0",
                        "parameters": [
                            {
                                "type": "text",
                                "text": button_suffix,
                            }
                        ],
                    }
                ],
            },
        }

        res = self._post(payload)
        # If error occurs due to button parameter mismatch (e.g. static button in template), retry without button component
        if isinstance(res, dict) and ("error" in res or res.get("status_code", 200) >= 400):
            err_msg = str(res.get("error", "")).lower()
            if "button" in err_msg or "parameter" in err_msg or res.get("status_code") == 400:
                payload["template"]["components"] = [
                    c for c in payload["template"]["components"] if c.get("type") != "button"
                ]
                res = self._post(payload)

        return res




