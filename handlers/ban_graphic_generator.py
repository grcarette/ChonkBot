from PIL import Image, ImageDraw, ImageFont
from .image_handler import ImageHandler
import os

class StageBannerGenerator:
    def __init__(
        self,
        banner_width=1500,
        stage_height=250,
        top_padding=10,
        text_height=30,
        background_color="white",
        font_path="assets/fonts/KGNextToMeSolid.ttf",
        font_size=20,
        text_color="white"
    ):
        self.banner_width = banner_width
        self.stage_height = stage_height
        self.top_padding = top_padding
        self.text_height = text_height
        self.row_height = self.stage_height + self.text_height + self.top_padding
        self.banner_height = self.row_height * 2
        self.background_color = background_color
        self.font_path = font_path
        self.font_size = font_size
        self.text_color = text_color
        self.border_color = "black"
        self.border_width = 4
        self.banner_base_path = "assets/banners"
        self.image_handler = ImageHandler()

    def generate_banner(self, stage_data, tournament):
        file_name = f"{tournament['name']}_banner.jpg"
        output_path = os.path.join(self.banner_base_path, file_name)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        banner = Image.new("RGB", (self.banner_width, self.banner_height), self.background_color)
        draw = ImageDraw.Draw(banner)

        try:
            font = ImageFont.truetype(self.font_path, self.font_size)
        except IOError:
            font = ImageFont.load_default()

        layout = [stage_data[:3], stage_data[3:]]
        max_per_row = 3
        stage_width = self.banner_width // max_per_row

        for row_index, row_stages in enumerate(layout):
            y_offset = row_index * self.row_height
            stage_count = len(row_stages)

            # Fill side margins for short rows with black
            if stage_count < max_per_row:
                margin_width = (self.banner_width - (stage_width * stage_count)) // 2
                draw.rectangle([0, y_offset, margin_width, y_offset + self.row_height], fill="black")
                draw.rectangle([self.banner_width - margin_width, y_offset, self.banner_width, y_offset + self.row_height], fill="black")

            left_margin = (self.banner_width - (stage_width * stage_count)) // 2

            for i, stage in enumerate(row_stages):
                stage_path = self.image_handler.get_image_path(stage['code'])
                img = Image.open(stage_path)
                img = self.resize_and_crop(img, (stage_width, self.stage_height))

                x_offset = left_margin + i * stage_width
                y_image_offset = y_offset + self.text_height + self.top_padding

                banner.paste(img, (x_offset, y_image_offset))

                # Draw border around the image
                draw.rectangle(
                    [x_offset, y_image_offset, x_offset + stage_width, y_image_offset + self.stage_height],
                    outline=self.border_color,
                    width=self.border_width
                )

                # Draw text background box (semi-transparent black rectangle)
                text_bg_box = [
                    x_offset,
                    y_offset,
                    x_offset + stage_width,
                    y_offset + self.text_height + self.top_padding
                ]
                draw.rectangle(text_bg_box, fill=(0, 0, 0, 128))

                # Draw text centered
                text = stage['name']
                text_width = draw.textlength(text, font=font)
                draw.text(
                    (x_offset + (stage_width - text_width) / 2, y_offset + self.top_padding // 2),
                    text,
                    fill=self.text_color,
                    font=font
                )

        banner.save(output_path)
        return output_path

    def resize_and_crop(self, img, target_size):
        img_ratio = img.width / img.height
        target_ratio = target_size[0] / target_size[1]

        if img_ratio > target_ratio:
            new_height = target_size[1]
            new_width = int(new_height * img_ratio)
        else:
            new_width = target_size[0]
            new_height = int(new_width / img_ratio)

        img = img.resize((new_width, new_height), Image.LANCZOS)

        left = (new_width - target_size[0]) // 2
        top = (new_height - target_size[1]) // 2
        right = left + target_size[0]
        bottom = top + target_size[1]

        return img.crop((left, top, right, bottom))