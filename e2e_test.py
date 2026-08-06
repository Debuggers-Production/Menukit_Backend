import requests
import json,time,uuid

ACCESS_TOKEN = "EAAdWY9yswpUBSMLlkZCRJljZAOwJ7kVbRRxPBCjZB2oATroBNuleuWAZAtAVFMNxAFDleS8jJYHZA2PGx6aCGJoi6jrIMm1ckcxK2up5yAgORoLX4e6iSqoAoL3ZAonJ1H2JfAgGftdFt6naThjth4NFpyuPOvRSBZADbAD6taRVb8xnfWN4YKaKdBVwsMMDLacGTAfPx5HnVkZAn4b3g7s4hAQNjolB1mxIDsWdcDX5wu62LbZC0wyu9eYG5ZCTGqeU0qM57j3KPVp2HdwCHkavLwbZAUiIO8ZD"
PHONE_NUMBER_ID = "1209211872274267"

url = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

unique_id = str(uuid.uuid4())[:8]

payload = {
    "messaging_product": "whatsapp",
    "to": "918248692839",
    "type": "template",
    "template": {
        "name": "contest_created_template",
        "language": {
            "code": "en"
        },
        "components": [
            {
                "type": "header",
                "parameters": [
                    {
                        "type": "image",
                        "image": {
                            "link": f"https://picsum.photos/900/600?{int(time.time())}"
                        }
                    }
                ]
            },
            {
                "type": "body",
                "parameters": [
                    {
                        "type": "text",
                        "text": f"Coffee Corner {unique_id}"
                    },
                    {
                        "type": "text",
                        "text": "Lucky Draw"
                    },
                    {
                        "type": "text",
                        "text": "Win an iPhone 16"
                    },
                    {
                        "type": "text",
                        "text": f"https://menukit.debuggers.co.in/{unique_id}"
                    }
                ]
            },
            {
                "type": "button",
                "sub_type": "url",
                "index": "0",
                "parameters": [
                    {
                        "type": "text",
                        "text": f"shop/{unique_id}/contest"
                    }
                ]
            }
        ]
    }
}

print(json.dumps(payload, indent=4))

response = requests.post(
    url,
    headers=headers,
    json=payload
)

print("\nStatus:", response.status_code)
print(json.dumps(response.json(), indent=4))