import discord

DEFAULT_STAGE_NUMBER = 5

STAFF_PERMISSIONS = discord.PermissionOverwrite(
    view_channel=True,
    send_messages=True,
    manage_messages=True,
    embed_links=True,
    attach_files=True,
    read_message_history=True,
    add_reactions=True,
    use_external_emojis=True
)

CHANNEL_PERMISSIONS = {
    'event-info': 'read_only',
    'event-updates': 'read_only',
    'stagelist': 'read_only',
    'event-chat': 'open',
    'questions': 'open',
    'register': 'read_only',
    'organizer-chat': 'private',
    'bot-control': 'private',
    'check-in': 'read_only',
    'match-calling': 'private',
    'active-matches': 'private',
    'registration-approval': 'private',
}

NONDEFAULT_CHANNELS = [
    'register',
    'check-in',
    'match-calling',
    'active-matches',
    'registration-approval'
]

async def create_channel(guild, tournament_category, hide_channel, channel_name, channel_overwrites, organizer_role=None):
    overwrites = {}
    view_channel = False
    if organizer_role:
        overwrites[organizer_role] = STAFF_PERMISSIONS
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