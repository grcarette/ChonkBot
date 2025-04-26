import discord

LEADERBOARD_CHANNEL_ID = 1365354885855580172

class TSCHandler:
    def __init__(self, bot):
        self.bot = bot
        self.leaderboard = None
        
    
    
    async def post_time(self, kwargs):
        time = kwargs.get('time')
        player_id = kwargs.get('player_id')
        await self.bot.dh.add_time(time, player_id)
        await self.update_leaderboard()
        
    async def register_team(self, team):
        result = await self.bot.dh.register_team(team)
        return result
        
    async def unregister_team(self, user_id):
        result = await self.bot.dh.unregister_team(user_id)
        return result
    
    async def update_leaderboard(self):
        best_times_dict = await self.bot.dh.get_best_times_by_team()
        
        if self.leaderboard == None:
            self.leaderboard = discord.utils.get(self.bot.guild.channels, id=LEADERBOARD_CHANNEL_ID)
            
        await self.leaderboard.purge(limit=None)

        sorted_entries = sorted(best_times_dict.values(), key=lambda x: x["time"])
        
        embed_lines = []
        for i, entry in enumerate(sorted_entries, start=1):
            members = []
            for member in entry["team"]:
                user = discord.utils.get(self.bot.guild.members, id=member)
                members.append(user.display_name)
            time = round(entry["time"], 3)
            embed_lines.append(f"**#{i}**: {', '.join(members)} — `{time}`s")

        embed_text = "\n".join(embed_lines)
        
        current_round = await self.bot.dh.get_current_round()

        await self.leaderboard.send(f"🏁 **Round {current_round} Leaderboard** 🏁\n\n{embed_text}")
        
    async def start_next_round(self):
        await self.bot.dh.next_tsc_round()