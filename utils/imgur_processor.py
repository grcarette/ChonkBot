import requests
import os
from dotenv import load_dotenv

load_dotenv()
IMGUR_CLIENT_ID = os.getenv('IMGUR_CLIENT_ID')

class ImgurProcessor:
    def __init__(self):
        self.client_id = IMGUR_CLIENT_ID

    def get_imgur_image_id(self, url):
        return url.split('-')[-1]

    def fetch_imgur_image_data(self, imgur_id):
        headers = {
            "Authorization": f"Client-ID {self.client_id}"
        }

        api_url = f"https://api.imgur.com/3/image/{imgur_id}"
        response = requests.get(api_url, headers=headers)

        if response.status_code != 200:
            raise Exception(f"[Imgur API] Error {response.status_code}: {response.text}")

        image_link = response.json()['data']['link']
        image_response = requests.get(image_link, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://imgur.com"
        })

        if image_response.status_code != 200:
            raise Exception(f"[Download] Error {image_response.status_code}: {image_response.text}")

        return image_response.content

