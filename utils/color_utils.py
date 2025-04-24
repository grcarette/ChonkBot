import discord

BRIGHTEN_FACTOR = 1.2
HEX_BASE = 16

def brighten_hex_color(hex_color: str):
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], HEX_BASE)
    g = int(hex_color[2:4], HEX_BASE)
    b = int(hex_color[4:6], HEX_BASE)

    r = min(int(r * BRIGHTEN_FACTOR), 255)
    g = min(int(g * BRIGHTEN_FACTOR), 255)
    b = min(int(b * BRIGHTEN_FACTOR), 255)

    return discord.Colour.from_rgb(r, g, b)

def discord_color_from_hex(hex_color: str) -> discord.Color:
    return discord.Color(int(hex_color.lstrip('#'), HEX_BASE))