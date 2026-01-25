from utils.errors import *

class StageMethodsMixin:
    async def get_stage(self, code):
        stage = await self.level_api.get_stage_by_code(code)
        return stage

    async def get_random_stages(self, number):
        stages = await self.level_api.get_random_stages(number)
        return stages



    
    