import discord
from discord.ext import commands
import time
from datetime import datetime, timezone

from utils.emojis import NUMBER_EMOJIS, INDICATOR_EMOJIS
from utils.reaction_flags import *

def create_future_timestamp(seconds_from_now):
    future_timestamp = time.time() + seconds_from_now
    future_datetime = datetime.fromtimestamp(future_timestamp, timezone.utc)
    return future_datetime

async def create_numerical_reaction(bot, message, num_list, flag_type, user_filter=False, require_all_to_react=False):
    emoji_list = [NUMBER_EMOJIS[num] for num in num_list]
    for emoji in emoji_list:
        await create_reaction_flag(bot, message, flag_type, user_filter=user_filter, require_all_to_react=require_all_to_react, emoji_list=emoji_list)
        
async def create_reaction_flag(bot, message, flag_type, user_filter=False, require_all_to_react=False, emoji_list=False, value=False):
    if not emoji_list:
        emoji_list = FLAG_DICTIONARY[flag_type]['dict'].keys()
    for emoji in emoji_list:
        try:
            if FLAG_DICTIONARY[flag_type]['timestamp'] == None:
                timestamp = None
            else:
                timestamp = create_future_timestamp(FLAG_DICTIONARY[flag_type]['timestamp'])
            await bot.dh.add_reaction_flag(
                message.id, 
                flag_type, 
                emoji, 
                user_filter=user_filter, 
                require_all_to_react=require_all_to_react, 
                value=value, 
                timestamp=timestamp
            )
            await message.add_reaction(emoji)
        except discord.errors.NotFound:
            await bot.dh.remove_reaction_flag(message.id)
            return
    
async def create_confirmation_reaction(bot, message):
    emoji = INDICATOR_EMOJIS['green_check']
    await message.add_reaction(emoji)
    await bot.dh.add_confirmation_to_flag(message.id)

async def create_tournament_configuration(bot, message, num_list, user_filter=False):
    await create_reaction_flag(bot, message, 'create_tournament', user_filter)
    await create_confirmation_reaction(bot, message)