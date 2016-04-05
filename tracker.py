from google.appengine.ext import ndb

import webapp2
from webapp2_extras import routes

from models import Campaign, Platform

__author__ = 'damjan'
__version__ = (1, 0)

PLATFORMS = ("android", "ios", "wp")


class ClickHandler(webapp2.RedirectHandler):
    # TODO: this should maybe be a POST method
    # TODO: restrict not needed HTTP methods
    # TODO: implement memcached caching
    def get(self, campaign_id, platform_name):
        # cast campaign_id, type checking is done through route definition
        try:
            campaign_id = int(campaign_id)
        except ValueError:
            return webapp2.redirect("http://outfit7.com", permanent=True)

        @ndb.transactional()
        def __increment():
            platform = Platform.get_by_id("%d-%s-%d" % (campaign_id, platform_name, Platform.get_random_shard_number()))
            if platform:
                platform.counter += 1
                platform.put()
                return True
            else:
                return False

        if __increment():
            campaign = Campaign.get_by_id(campaign_id)
            return webapp2.redirect(campaign.link.encode("utf8"))
        else:
            return webapp2.redirect("http://outfit7.com", permanent=True)


app = webapp2.WSGIApplication([
    routes.PathPrefixRoute('/api', [
        webapp2.Route(r'/campaign/<campaign_id:\d+>/platform/<platform_name>', ClickHandler),
    ])
], debug=True)
