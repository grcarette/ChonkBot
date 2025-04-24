import discord
import random

PRESET_COLORS = [
    discord.Color.blue(),
    discord.Color.green(),
    discord.Color.orange(),
    discord.Color.purple(),
    discord.Color.red(),
    discord.Color.teal(),
    discord.Color.gold(),
    discord.Color.blurple(),
    discord.Color.dark_gold(),
    discord.Color.dark_teal(),
    discord.Color.dark_purple(),
    discord.Color.dark_blue(),
]

def get_random_color():
    return random.choice(PRESET_COLORS)