import discord

class InfoDisplayView(discord.ui.View):
    def __init__(self, tournament_info_display, timeout=None):
        super().__init__(timeout=timeout)
        self.tid = tournament_info_display
        
    async def add_link(self, link_label, link_url):
        link_button = discord.ui.Button(label=link_label, style=discord.ButtonStyle.link, url=link_url)
        self.add_item(link_button)