import os
import httpx
import asyncio
import aiofiles
from dotenv import load_dotenv

class ImgurProcessor:
    def __init__(self):
        load_dotenv()
        self.client_id = os.getenv('IMGUR_CLIENT_ID')

    def get_imgur_image_id(self, url):
        return url.split('-')[-1].split('/')[-1]

    async def download_image(self, imgur_link, filepath):
        imgur_id = self.get_imgur_image_id(imgur_link)
        image_link = f"https://i.imgur.com/{imgur_id}.png"

        download_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": "https://imgur.com"
        }

        async with httpx.AsyncClient(headers=download_headers, follow_redirects=True) as client:
            try:
                response = await client.get(image_link, timeout=15.0)
                
                if response.status_code == 200:
                    await self.save_image(response.content, filepath)
                else:
                    print(f"[Download Error] Status {response.status_code} at {image_link}")
                    return None
            except httpx.RequestError as e:
                print(f"[Network Error] {e}")
                return None

    async def save_image(self, image_bytes, filepath):
        if image_bytes is None:
            print("No data to save.")
            return False
            
        try:
            async with aiofiles.open(filepath, mode='wb') as f:
                await f.write(image_bytes)
            
            return True
        except Exception as e:
            print(f"Error saving file: {e}")
            return False

