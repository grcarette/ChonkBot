import os
from utils.imgur_processor import ImgurProcessor

class ImageHandler:
    def __init__(self, image_root="level_images"):
        self.image_root = image_root
        self.imgur_processor = ImgurProcessor()

    async def get_image_path(self, map_code, extension="jpeg"):
        safe_code = map_code.upper()
        subfolder = safe_code[0]
        folder_path = os.path.join(self.image_root, subfolder)
        os.makedirs(folder_path, exist_ok=True)
        path = os.path.join(folder_path, f"{safe_code}.{extension}")
        print(os.path.abspath(path))
        return path

    async def retrieve_image(self, stage):
        map_code = stage['code']
        imgur_url = stage['imgur_url']
        file_path = await self.get_image_path(map_code)
        if os.path.exists(file_path):
            return file_path 

        try:
            await self.imgur_processor.download_image(imgur_url, file_path)
            return file_path
        except Exception as e:
            raise Exception(f"Error retrieving image for map {map_code}: {str(e)}")
    
    
    
    