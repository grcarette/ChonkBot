from utils.errors import *

class StageMethodsMixin:
    async def get_stage(self, code):
        stage = await self.level_api.get_stage_by_code(code)
        return stage

    async def get_stages_from_list(self, stage_codes):
        stages = await self.level_api.get_stages_from_list(stage_codes)
        return stages

    async def get_random_stages(self, number):
        stages = await self.level_api.get_random_stages(number)
        return stages



    
    