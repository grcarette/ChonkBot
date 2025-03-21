import discord
from discord.ext import commands

from utils.reaction_utils import create_reaction_flag

DEFAULT_STAGE_NUMBER = 5

class TournamentHandler():
    def __init__(self, bot):
        self.bot = bot
    
    async def set_up_tournament(self, message_id):
        guild = self.bot.guilds[0]
        tournament = await self.bot.dh.get_tournament(message_id=message_id)
        
        organizer_role = discord.utils.get(guild.roles, name='Event Organizer')
        tournament_role = await guild.create_role(name=f"{tournament['name']}")
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False)
        }
        
        tournament_category = await guild.create_category(
            f"{tournament['name']}", 
            overwrites=overwrites
        )
        await self.bot.dh.add_category_to_tournament(tournament['name'], tournament_category.id)
        
        channel_list = []

        event_info = await self.create_channel(guild, tournament_category, 'event-info', 'read_only')
        event_updates = await self.create_channel(guild, tournament_category, 'event-updates', 'read_only')
        stage_list = await self.create_channel(guild, tournament_category, 'stagelist', 'read_only')
        event_chat = await self.create_channel(guild, tournament_category, 'event-chat', 'open')
        questions = await self.create_channel(guild, tournament_category, 'questions', 'open')
        register = await self.create_channel(guild, tournament_category, 'register', 'open')
        organizer_chat = await self.create_channel(guild, tournament_category, 'organizer_chat', 'private')
        
        await self.bot.dh.create_registration_flag(register.id, tournament['name'], tournament['approved_registration'])
        
        if tournament['randomized_stagelist'] == True:
            for i in range(DEFAULT_STAGE_NUMBER):
                stage = await self.bot.dh.get_random_stage()
                message = (
                    f"# {stage['name']}\n"
                    f"Creator: {stage['creator']}\n"
                    f"Code: {stage['code']}\n"
                    f"{stage['imgur']}"
                )
                await stage_list.send(message)
                
        if tournament['format'] == 'Single Elimination':
            pass
        elif tournament['format'] == 'Double elimination':
            pass
            
        
    async def remove_tournament(self, tournament_name):
        guild = self.bot.guilds[0]
        tournament = await self.bot.dh.get_tournament(name=tournament_name)
        category_id = tournament['category_id']
        category = discord.utils.get(guild.categories, id=category_id)
        role = discord.utils.get(guild.roles, name=tournament_name)
        
        if role:
            await role.delete()
        
        for channel in category.channels:
            is_register_channel = await self.bot.dh.get_registration_flag(channel.id)
            if is_register_channel:
                await self.bot.dh.remove_registration_flag(channel.id)
            try:
                await channel.delete()
            except discord.Discordexception as e:
                print(f"Error deleting channel {channel.name}: {e}")
        
        try:
            await category.delete()
        except discord.DiscordException as e:
            print(f"Error deleting category {category.name}: {e}")
            
          
    async def create_channel(self, guild, tournament_category, channel_name, channel_overwrites):
        overwrites = {}
        
        if channel_overwrites == 'read_only':
            overwrites[guild.default_role] = discord.PermissionOverwrite(
                view_channel=False,
                send_messages=False,
                manage_messages=False,
                embed_links=False,
                attach_files=False,
                read_message_history=True,
                add_reactions=True,
                use_external_emojis=True
            )
        elif channel_overwrites == "open":
            overwrites[guild.default_role] = discord.PermissionOverwrite(
                view_channel=False,
                send_messages=True,
                manage_messages=False,
                embed_links=True,
                attach_files=True,
                read_message_history=True,
                add_reactions=True,
                use_external_emojis=True
            )
        elif channel_overwrites == 'private':
            overwrites[guild.default_role] = discord.PermissionOverwrite(
                view_channel=False,
                send_messages=False,
                manage_messages=False,
                embed_links=False,
                attach_files=False,
                read_message_history=False,
                add_reactions=False,
                use_external_emojis=False
            )
        
        new_channel = await guild.create_text_channel(
            f'{channel_name}',
            category=tournament_category,
            overwrites=overwrites
        )
        return new_channel

    async def process_registration(self, message, is_register, is_confirmation=False):
        print('here!')
        channel_id = message.channel.id
        category_id = message.channel.category_id
        user_id = message.author.id
        guild = self.bot.guilds[0]
        
        tournament = await self.bot.dh.get_tournament(category_id=category_id)
        role = discord.utils.get(guild.roles, name=tournament['name'])
        organizer_role = discord.utils.get(guild.roles, name="Moderator")
        member = message.author
        
        if is_register:
            if tournament['approved_registration'] == True and is_confirmation == False:
                await create_reaction_flag(self.bot, message, 'confirm_registration', user_filter=tournament['organizer'])
            else:
                await self.bot.dh.register_player(tournament['name'], user_id)
                await member.add_roles(role)
        else:
            await self.bot.dh.unregister_player(tournament['name'], user_id)
            await member.remove_roles(role)
            
        

        
        
        
       
        
        