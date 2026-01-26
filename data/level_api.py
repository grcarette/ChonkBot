import httpx
import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv

class LevelAPI:
    def __init__(self):
        env_path = Path(__file__).resolve().parent.parent / '.env'
        load_dotenv(dotenv_path=env_path)
        lvlnet_domain = str(os.getenv("LVLNET_DOMAIN"))
        self.url = lvlnet_domain
        self.client = httpx.AsyncClient(base_url=self.url)

    async def get_stage_by_code(self, code: str):
        try:
            response = await self.client.get(f"/levels/{code.upper()}")
            if response.status_code == 200:
                return response.json()
            return None
        except httpx.RequestError as e:
            print(f"API Error: {e}")
            return None

    async def get_random_stages(self, number):
        try:
            response = await self.client.get(f"/levels/random/{number}")
            if response.status_code == 200:
                return response.json()
            return None
        except httpx.RequestError as e:
            print(f"API Error: {e}")
            return None

if __name__ == "__main__":
    t = LevelAPI()
    level = asyncio.run(t.get_random_stages(1))
    stage = level[0]
    print(stage['creators'])