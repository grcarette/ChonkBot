from utils.emojis import NUMBER_EMOJIS, INDICATOR_EMOJIS

async def create_numerical_reaction(bot, message, num_list, flag_type, user_filter=None):
    emoji_list = [NUMBER_EMOJIS[num] for num in num_list]
    for emoji in emoji_list:
        await message.add_reaction(emoji)
        
    await bot.dh.add_reaction_flag(message.id, flag_type, emoji_list, user_filter)
    
async def create_confirmation_reaction(bot, message, user_filter=None):
    emoji = INDICATOR_EMOJIS['green_check']
    await message.add_reaction(emoji)
    await bot.dh.add_confirmation_to_flag(message.id)