from google.appengine.api import memcache
from google.appengine.ext import ndb


class Campaign(ndb.Model):
    name = ndb.StringProperty()
    link = ndb.StringProperty()
    create_date = ndb.DateTimeProperty(auto_now=True)
    update_date = ndb.DateTimeProperty()


class Platform(ndb.Model):
    name = ndb.StringProperty()
    counter = ndb.IntegerProperty(default=0)
    campaign = ndb.KeyProperty(kind=Campaign)

    @classmethod
    def increment(cls, platform_id):  #
        platform = cls.get_by_id(platform_id)
        if platform:
            value = memcache.get(platform.key.id(), namespace="counters")
            memcache.decr(platform.key.id(), delta=value, namespace="counters")
            platform.counter += value
            platform.put()
