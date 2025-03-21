import discord
from discord.ext import commands

class MessageCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.content.lower() == 'register' or message.content.lower() == 'unregister':
            if message.content.lower() == 'register':
                is_register = True
            else:
                is_register = False
                
            channel_id = message.channel.id
            category_id = message.channel.category.id
            register_flag = await self.bot.dh.get_registration_flag(channel_id=channel_id)
            if register_flag:
                await self.bot.th.process_registration(message, is_register=is_register)

async def setup(bot):
    await bot.add_cog(MessageCog(bot))