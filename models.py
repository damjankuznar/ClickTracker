import os
import random
from google.appengine.ext import ndb

__author__ = 'damjan'


class Campaign(ndb.Model):
    name = ndb.StringProperty()
    link = ndb.StringProperty()
    create_date = ndb.DateTimeProperty(auto_now=True)
    update_date = ndb.DateTimeProperty()


# TODO: implement sharding https://cloud.google.com/appengine/articles/sharding_counters
class Platform(ndb.Model):
    name = ndb.StringProperty()
    counter = ndb.IntegerProperty(default=0)
    campaign = ndb.KeyProperty(kind=Campaign)
    group_id = ndb.StringProperty()

    number_of_shards = int(os.environ.get("TRACKER_SHARD_NUMBER", "1"))

    @staticmethod
    def get_random_shard_number():
        return random.randint(0, Platform.number_of_shards - 1)
