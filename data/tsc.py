from bson import ObjectId

class TSCDataMethodsMixin:
    pass

    async def add_time(self, time, user_id):
        code = await self.get_current_code()
        query = {
            'members': user_id
        }
        team_doc = await self.tsc_collection.find_one(query)
        if not team_doc:
            return False
        
        score = {
            'time': float(time),
            'team': team_doc['_id'],
            'code': code
        }

        await self.time_collection.insert_one(score)
        return True
        
    async def register_team(self, team):
        query = {
            'members': {
                '$in': team
            }
        }
        team_exists = await self.tsc_collection.find_one(query)
        if team_exists:
            return False
        else:
            team = {
                'members': team
            }
            await self.tsc_collection.insert_one(team)
            team = await self.tsc_collection.find_one(query)
            return team
        
    async def unregister_team(self, user_id):
        query = {
            'members': {
                '$in': [user_id]
            }
        }
        result = await self.tsc_collection.delete_one(query)
        if result.deleted_count == 0:
            return False
        return True
    
    async def get_current_code(self):
        tsc_doc = await self.tsc_collection.find_one({"tsc": True})
        if not tsc_doc or "current_round" not in tsc_doc or "codes" not in tsc_doc:
            print('rah')
            return []

        current_round = tsc_doc["current_round"]
        codes = tsc_doc["codes"]
        
        if current_round >= len(codes) or current_round < 1:
            print('h')
            return []

        code = codes[current_round - 1] 
        print(code)
        return code

    async def get_best_times_by_team(self):
        # Get the current code
        current_code = await self.get_current_code()
        
        pipeline = [
            # Match only documents with the current code
            {
                "$match": {
                    "code": current_code
                }
            },
            # Group times by team, finding the minimum time for each
            {
                "$group": {
                    "_id": "$team",
                    "lowest_time": {"$min": "$time"},
                    "code": {"$first": "$code"}
                }
            },
            # Look up the team details to get member information
            {
                "$lookup": {
                    "from": self.tsc_collection.name,
                    "localField": "_id",
                    "foreignField": "_id",
                    "as": "team_info"
                }
            },
            # Unwind the team_info array (should have only one element per team)
            {
                "$unwind": "$team_info"
            },
            # Project the fields we want in our final output
            {
                "$project": {
                    "_id": 0,
                    "team": "$team_info.members",
                    "time": "$lowest_time",
                    "code": "$code"
                }
            }
        ]
        
        # Execute the pipeline asynchronously
        cursor = self.time_collection.aggregate(pipeline)
        results = await cursor.to_list(length=None)
        
        # Format the results as requested
        best_times = {}
        for result in results:
            best_times[str(result["team"])] = {
                "time": result["time"],
                "team": result["team"]
            }
        
        return best_times

    async def next_tsc_round(self):
        query = {
            'tsc': True
        }
        update = {
            "$inc": {"current_round": 1} 
        }

        result = await self.tsc_collection.update_one(query, update)

        if result.modified_count == 1:
            return True 
        else:
            return False  
        
    async def get_current_round(self):
        query = {
            'tsc': True
        }
        data = await self.tsc_collection.find_one(query)
        return data['current_round']
        