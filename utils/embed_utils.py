import discord
from utils.discord_preset_colors import get_random_color

async def create_stage_embed(level):
    creator_names = [creator['username'] for creator in level['creators']]
    creators_string = ", ".join(creator_names)

    embed = discord.Embed(
        title=level['name'],
        color=get_random_color()
    )
    embed.add_field(name="Made by", value=creators_string, inline=True)
    embed.add_field(name="Code", value=f"`{level['code']}`", inline=True)

    if level.get('imgur_url'):
        raw_url = level['imgur_url'].split('?')[0].rstrip('/')
        split_index = max(raw_url.rfind('-'), raw_url.rfind('/'))
        image_id = raw_url[split_index + 1:].split('.')[0]
        direct_link = f"https://i.imgur.com/{image_id}.png"
        
        embed.set_image(url=direct_link)
        embed.description = f"[View on Imgur]({level['imgur_url']})"     

    return embed