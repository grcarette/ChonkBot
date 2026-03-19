# tournaments/format_handlers.py

class BaseFormatHandler:
    def __init__(self, tm):
        self.tm = tm
        self.dh = tm.bot.dh

    async def on_result(self, result, lobby):
        raise NotImplementedError


class DEFormatHandler(BaseFormatHandler):
    async def on_result(self, result, lobby):
        tournament = await self.tm.get_tournament()
        winner_user_id = str(result['winner_id'])
        winner_id = tournament['entrants'][winner_user_id]

        await self.tm.ch.report_match(
            tournament['challonge_data']['url'],
            result['match_id'],
            winner_id,
            result['is_dq'],
        )
        status = await self.tm.ch.check_tournament_status(
            tournament['challonge_data']['id']
        )
        await self.tm.close_prereqs(lobby)
        if status == 'awaiting_review':
            await self.tm.prompt_end_tournament()
        else:
            await self.tm.call_matches()


class SwissFormatHandler(BaseFormatHandler):
    async def on_result(self, result, lobby):
        tournament = await self.tm.get_tournament()
        swiss_event = await self.dh.get_swiss_event_by_tournament(tournament['_id'])

        if swiss_event:
            await self.dh.swiss_record_result(
                swiss_event['_id'],
                result['match_id'],
                result['winner_id'],
                result['loser_id'],
            )
            if not self.tm.debug and not result['is_dq']:
                api_result = await self.tm.bot.uchranked_api.report_match(
                    player1_id=result['winner_id'],
                    player2_id=result['loser_id'],
                    score="1-0",
                )
                if not api_result.get('success'):
                    print(f"UCH Ranked API error: {api_result.get('error')}")

            if self.tm.swiss_manager:
                await self.tm.swiss_manager.on_match_complete(
                    result['match_id'],
                    result['winner_id'],
                    result['loser_id'],
                )

def make_format_handler(tm):
    if tm.tournament.get('format') == 'swiss':
        return SwissFormatHandler(tm)
    return DEFormatHandler(tm)