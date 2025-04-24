import os
from utils.imgur_processor import ImgurProcessor

class ImageHandler:
    def __init__(self, image_root="../level_images"):
        self.image_root = image_root
        self.imgur_processor = ImgurProcessor()

    def get_image_path(self, map_code, extension="jpeg"):
        safe_code = map_code.upper()
        subfolder = safe_code[0]
        folder_path = os.path.join(self.image_root, subfolder)
        os.makedirs(folder_path, exist_ok=True)
        return os.path.join(folder_path, f"{safe_code}.{extension}")

    def retrieve_image(self, map_code, imgur_url):
        file_path = self.get_image_path(map_code)
        if os.path.exists(file_path):
            return file_path 
        imgur_id = self.imgur_processor.get_imgur_image_id(imgur_url)

        try:
            image_data = self.imgur_processor.fetch_imgur_image_data(imgur_id)

            if not os.path.exists(file_path):
                with open(file_path, 'wb') as f:
                    f.write(image_data)

            return file_path
        except Exception as e:
            raise Exception(f"Error retrieving image for map {map_code}: {str(e)}")
    
    
    
    