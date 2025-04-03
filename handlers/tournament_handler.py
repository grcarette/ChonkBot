import discord
from discord.ext import commands

from utils.reaction_utils import create_reaction_flag
from utils.reaction_flags import TOURNAMENT_CONFIGURATION
from utils.emojis import NUMBER_EMOJIS, INDICATOR_EMOJIS

from ui.bot_control import BotControlView
from ui.register_control import RegisterControlView

DEFAULT_STAGE_NUMBER = 5
CHANNEL_PERMISSIONS = {
    'event-info': 'read_only',
    'event-updates': 'read_only',
    'stagelist': 'read_only',
    'event-chat': 'open',
    'questions': 'open',
    'register': 'open',
    'organizer-chat': 'private',
    'bot-control': 'private',
}


class TournamentHandler():
    def __init__(self, bot):
        self.bot = bot
    
    async def set_up_tournament(self, tournament):
        guild = self.bot.guilds[0]
        await self.bot.dh.create_tournament(tournament)
        await self.add_stages_tournament(tournament)
        
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
        
        channel_dict = {}
        
        for channel in CHANNEL_PERMISSIONS:
            channel_dict[f'{channel}'] = await self.create_channel(
                guild=guild, 
                tournament_category=tournament_category, 
                hide_channel=True, 
                channel_name=f'{channel}', 
                channel_overwrites=CHANNEL_PERMISSIONS[f'{channel}']
            )
        
        await self.bot.dh.create_registration_flag(channel_dict['register'].id, tournament['name'], tournament['approved_registration'])
                   
        await self.post_stages(tournament['name'], channel_dict['stagelist'])  
        if tournament['format'] == 'Single Elimination':
            pass
        elif tournament['format'] == 'Double elimination':
            pass
        users = [tournament['organizer']]
        tournament = await self.bot.dh.get_tournament(name=tournament['name'])
        
        await self.add_register_control(tournament, channel_dict['register'])
        await self.add_bot_control(channel_dict['bot-control'])
        
    async def add_register_control(self, tournament, channel):
        view = RegisterControlView(self.bot)
        embed = discord.Embed(
            title=f"Register for {tournament['name']}",
            color=discord.Color.green()
        )
        await channel.send(embed=embed, view=view)
        
    async def add_bot_control(self, channel):
        view= BotControlView(self.bot)
        embed = discord.Embed(
            title="Tournament Controls",
            color=discord.Color.green()
        )
        await channel.send(embed=embed, view=view)
        
    async def post_stages(self, tournament_name, channel):
        tournament = await self.bot.dh.get_tournament(name=tournament_name)
        for stage_code in tournament['stagelist']:
            stage = await self.bot.dh.get_stage(code=stage_code)
            message = (
                f"# {stage['name']}\n"
                f"Creator: {stage['creator']}\n"
                f"Code: {stage['code']}\n"
                f"{stage['imgur']}"
            )
            await channel.send(message)
        
    async def add_stages_tournament(self, tournament):       
        if tournament['randomized_stagelist'] == True:
            stages = await self.bot.dh.get_random_stages(DEFAULT_STAGE_NUMBER)
            await self.bot.dh.add_stages_to_tournament(tournament['name'], stages)

    async def remove_tournament(self, category_id):
        guild = self.bot.guilds[0]
        tournament = await self.bot.dh.get_tournament(category_id=category_id)
        category_id = tournament['category_id']
        category = discord.utils.get(guild.categories, id=category_id)
        role = discord.utils.get(guild.roles, name=tournament['name'])
        
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
            
        await self.bot.dh.delete_tournament('t')
            
          
    async def create_channel(self, guild, tournament_category, hide_channel, channel_name, channel_overwrites):
        overwrites = {}
        view_channel = False
        if channel_overwrites == 'read_only':
            if not hide_channel:
                view_channel = True
            overwrites[guild.default_role] = discord.PermissionOverwrite(
                view_channel=view_channel,
                send_messages=False,
                manage_messages=False,
                embed_links=False,
                attach_files=False,
                read_message_history=True,
                add_reactions=True,
                use_external_emojis=True
            )
        elif channel_overwrites == "open":
            if not hide_channel:
                view_channel = True
            overwrites[guild.default_role] = discord.PermissionOverwrite(
                view_channel=view_channel,
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
                view_channel=view_channel,
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
    
    async def toggle_reveal_channels(self, category_id):
        guild = self.bot.guilds[0]
        category = discord.utils.get(guild.categories, id=category_id)
        for channel in category.channels:
            permissions = CHANNEL_PERMISSIONS[channel.name]
            if permissions != 'private':
                overwrite = channel.overwrites_for(guild.default_role)
                overwrite.view_channel = not overwrite.view_channel
                await channel.set_permissions(guild.default_role, overwrite=overwrite)

    async def process_registration(self, message, is_register, is_confirmation=False):
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
            
        

        
        
        
       
        
        