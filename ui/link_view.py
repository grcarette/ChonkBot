import discord
from utils.emojis import INDICATOR_EMOJIS

class LinkView(discord.ui.View):
    def __init__(self, label, url):
        super().__init__()
        self.url = url
        self.label = label
        
        self.bracket_button = discord.ui.Button(
            label=self.label, 
            style=discord.ButtonStyle.link, 
            url=self.url
            )

        self.add_item(self.bracket_button)
        