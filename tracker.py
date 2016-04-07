import os
import time

import webapp2
from google.appengine.api import memcache, taskqueue
from google.appengine.ext import deferred
from google.appengine.ext import ndb
from webapp2_extras import routes

from models import Campaign, Platform

PLATFORMS = ("android", "ios", "wp")
try:
    TRACKER_COUNTER_UPDATE_INTERVAL_LENGTH = int(os.environ.get("TRACKER_COUNTER_UPDATE_INTERVAL_LENGTH", 1))
except:
    TRACKER_COUNTER_UPDATE_INTERVAL_LENGTH = 1


def get_interval_index():
    """Get the index of the interval from the UNIX epoch time. Interval length is defined by the
    TRACKER_COUNTER_UPDATE_INTERVAL_LENGTH.
    """
    return int(time.time() / TRACKER_COUNTER_UPDATE_INTERVAL_LENGTH)


class ClickHandler(webapp2.RedirectHandler):
    def get(self, campaign_id, platform_name):
        """
        Handles incoming clicks for given campaign_id and platform_name.
        If click is valid then user is redirected to url defined in the campaign
        and statistic about this click is saved. All invalid clicks (e.g. for non
        existing campaigns, platforms) users are redirected to http://outfit7.com.
        """
        # cast campaign_id, type checking is done through route definition
        try:
            campaign_id = int(campaign_id)
        except ValueError:
            return webapp2.redirect("http://outfit7.com", permanent=True)

        platform_id = "%d-%s" % (campaign_id, platform_name)
        platform = Platform.get_by_id(platform_id)
        if platform:
            memcache.incr(platform_id, 1, namespace="counters", initial_value=0)
            try:
                deferred.defer(Platform.increment, platform_id, _countdown=TRACKER_COUNTER_UPDATE_INTERVAL_LENGTH,
                               _name="%s-%d" % (platform_id, get_interval_index()))
            except (taskqueue.TaskAlreadyExistsError, taskqueue.TombstonedTaskError), e:
                pass
            # TODO: optimize with async operations
            campaign = Campaign.get_by_id(campaign_id)
            return webapp2.redirect(campaign.link.encode("utf8"))
        else:
            return webapp2.redirect("http://outfit7.com", permanent=True)


app = ndb.toplevel(webapp2.WSGIApplication([
    routes.PathPrefixRoute('/api', [
        webapp2.Route(r'/campaign/<campaign_id>/platform/<platform_name>', ClickHandler),
    ])
], debug=False))
