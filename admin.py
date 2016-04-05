import base64
from datetime import datetime
import json
import os

import webapp2
from webapp2_extras import routes
from google.appengine.ext import ndb

from models import Campaign, Platform

__author__ = 'damjan'
__version__ = (1, 0)

# List of possible platforms
PLATFORMS = ("android", "ios", "wp")


class TrackerException(Exception):
    """Class for raising Click Tracker API related expections."""

    def __init__(self, msg, status_code=500):
        super(TrackerException, self).__init__(msg)
        self.status_code = status_code


# TODO: remove
class StatsHandler(webapp2.RequestHandler):
    def get(self):
        self.response.write("\n".join(str(c) for c in Campaign.query().fetch(100)))
        self.response.write("\n\n")
        self.response.write("\n".join(str(c) for c in Platform.query().fetch(100)))


def handle_error(request, response, exception):
    """Overriding webapp2 default HTTP error output by returning JSON content type by default.
    :param request: Request instance.
    :param response: Response instance.
    :param exception: Exception instance to be handled.
    """
    response.headers.add_header('Content-Type', 'application/json')
    result = {
        'error': exception.explanation,
    }
    response.write(json.dumps(result))
    # TODO: remove
    response.write("\n")
    response.set_status(exception.code)


def json_serial(obj):
    """JSON serializer for datetime objects."""
    if isinstance(obj, datetime):
        serial = obj.isoformat()
        return serial
    raise TypeError("Type not serializable")


class AdminHandler(webapp2.RequestHandler):
    def dispatch(self):
        """Overrides default dispatch by setting the default HTTP Content-type to JSON, performs user authorization
        checking and caches any TrackerException during the dispatch and convert it into meaninful response."""
        self.response.headers['Content-Type'] = 'application/json'
        try:
            # TODO: enable auth
            # self.check_auth()
            output = super(AdminHandler, self).dispatch()
            if isinstance(output, basestring):
                self.response.write(output)
            elif output is not None:
                self.response.write(json.dumps(output, default=json_serial, sort_keys=True))
        except TrackerException, e:
            self.response.status_int = e.status_code
            self.response.write(json.dumps({"error": e.message}, default=json_serial, sort_keys=True))
        # TODO: remove this
        self.response.write("\n")

    def check_auth(self):
        basic_auth = self.request.headers.get('Authorization')
        if not basic_auth:
            raise TrackerException("Authorization is required.", status_code=401)
        username, password = "", ""
        try:
            user_info = base64.decodestring(basic_auth[6:])
            username, password = user_info.split(':')
            # check username and password
        except Exception, e:
            raise TrackerException("Could not parse HTTP Authorization.", status_code=400)
        if not (username == os.environ.get("TRACKER_ADMIN_USERNAME", None) and
                        password == os.environ.get("TRACKER_ADMIN_PASSWORD", None)):
            raise TrackerException("Invalid authorization credentials.", status_code=401)

    def get_request_json(self):
        """Gets JSON from request or raises TrackerException if JSON invalid."""
        try:
            print self.request.body
            campaign_dict = json.loads(self.request.body)
        except:
            raise TrackerException("Could not get a valid JSON from request. Please send request as JSON encoded data "
                                   "and set Content-Type as 'application/json'.", status_code=400)
        return campaign_dict


class CampaignCollectionHandler(AdminHandler):
    def get(self):
        """List all existing campaigns."""
        return [campaign_to_dict(campaign) for campaign in Campaign.query()]

    # TODO: test for malformed inputs
    def post(self):
        """Create a new campaign."""
        campaign_dict = self.get_request_json()
        campaign_dict["id"] if "id" in campaign_dict else None
        # get a list of platforms
        platforms_list = campaign_dict["platforms"]
        del campaign_dict["platforms"]
        # construct and store a new campaign
        campaign = Campaign(**campaign_dict)
        campaign.put()
        campaign_id = campaign.key.id()
        # construct and store platforms for campaign
        platforms = []
        for platform_name in platforms_list:
            for shard_number in range(Platform.number_of_shards):
                platform = Platform(name=platform_name, counter=0, campaign=campaign.key,
                                    group_id="%d-%s" % (campaign_id, platform_name),
                                    id="%d-%s-%d" % (campaign_id, platform_name, shard_number))
                platform.put()
                # generate dict representation of platform for response
                platform = platform.to_dict()
                del platform["campaign"]
                platforms.append(platform)
        # prepare response representation of the created campaing
        output = campaign.to_dict()
        output["platforms"] = platforms
        output["id"] = campaign_id
        # set the appropriate response headers
        self.response.headers["Location"] = self.uri_for("campaign-detail", campaign_id=campaign_id)
        self.response.status_int = 201
        return output


class CampaignHandler(AdminHandler):
    def get(self, campaign_id):
        """Display information about the existing campaign."""
        campaign_id = int(campaign_id)
        campaign = Campaign.get_by_id(campaign_id)
        if campaign:
            output = campaign.to_dict()
            query = Platform.query(Platform.campaign == campaign.key)
            platforms = [platform.to_dict() for platform in
                         query.fetch(3, projection=[Platform.name, Platform.counter])]
            output["id"] = campaign.key.id()
            output["platforms"] = platforms
            return output
        else:
            raise TrackerException("Campaign with id %s does not exist." % campaign_id, status_code=204)

    def delete(self, campaign_id):
        """Delete the existing campaign."""
        campaign_id = int(campaign_id)
        campaign = Campaign.get_by_id(campaign_id)

        if campaign:
            # detele the campaign first, so that updates are not possible
            campaign.key.delete()
            # delete all platforms that correspond to the campaign
            [platform.key.delete() for platform in Platform.query(Platform.campaign == campaign.key).fetch(3)]
        else:
            # TODO: report error or just set to response 204 (No Content)
            self.response.status_int = 204
            raise TrackerException("Campaign with id %s does not exist." % campaign_id, status_code=204)

    def put(self, campaign_id):
        """Update the existing campaign."""
        campaign_id = int(campaign_id)
        campaign_dict = self.get_request_json()
        campaign_dict["id"] if "id" in campaign_dict else None
        campaign = Campaign.get_by_id(campaign_id)

        platforms = []
        # get a list of existing campaign platforms
        existing_platforms_list = {platform.name: platform for platform in
                                   Platform.query(Platform.campaign == campaign.key).fetch(3)}

        # special processing for platforms field
        platforms_to_store = []
        if "platforms" in campaign_dict:
            # get a list of platforms from the request
            platforms_list = campaign_dict["platforms"]
            del campaign_dict["platforms"]
            # construct and store platforms for campaign
            for platform_name in platforms_list:
                if platform_name not in existing_platforms_list:
                    platform = Platform(name=platform_name, counter=0, campaign=campaign.key,
                                        id="%d-%s" % (campaign_id, platform_name))
                    # platform.put()
                    platforms_to_store.append(platform)
                else:
                    platform = existing_platforms_list[platform_name]
                # generate dict representation of platform for response
                platform = platform.to_dict()
                del platform["campaign"]
                platforms.append(platform)
        else:
            # no changes to platforms field, just copy
            for platform in existing_platforms_list.values():
                platform = platform.to_dict()
                del platform["campaign"]
                platforms.append(platform)

        # update the rest of the fields
        for field_name in campaign_dict:
            setattr(campaign, field_name, campaign_dict[field_name])
        campaign.update_date = datetime.now()

        @ndb.transactional(xg=True)
        def _update():
            """Do the update in transaction"""
            [__platform.put() for __platform in platforms_to_store]
            campaign.put()

        _update()

        # TODO: make a function to serialize the campaign and platforms into output
        output = campaign.to_dict()
        output["platforms"] = platforms
        output["id"] = campaign_id
        return output


def delete_keys(dict_object, keys):
    """
    Remove keys from dict like object.
    :param dict_object: Dict-like object.
    :param keys: Keys to remove.
    :return: Dict without removed keys.
    """
    for key in keys:
        try:
            del dict_object[key]
        except:
            pass
    return dict_object


def platform_to_dict(platform):
    """
    Transform Platform instance into dictionary that is suitable for JSON serialization display to end-user.
    :param platform: Platform instance.
    :return: Dictionary
    """
    return delete_keys(platform.to_dict(), ["campaign", "group_id"])


def campaign_to_dict(campaign, platforms=None, fetch_platforms=True):
    """
    Transform Campaign instance into dictionary that is suitable for JSON serialization display to end-user. If
    platforms parameter is specified it appends the campaign information about enabled platforms. If parameter 
    fetch_platforms is True then the platforms data is fetched from the Datastore. If platforms is specified then 
    fetch_platforms is ignored.
    :param campaign: Campaign instance.
    :param platforms: List of Platform instances.
    :param fetch_platforms: Boolean indicating whether to fetch platforms data from the Datastore.
    :return: Dictionary
    """
    output = campaign.to_dict()
    output["id"] = campaign.key.id()
    if platforms is None and fetch_platforms:
        platforms = [platform for platform in
                     Platform.query(Platform.campaign == campaign.key, 
                                    projection=[Platform.name, Platform.counter])]
        

    output["platforms"] = [platform_to_dict(platform) for platform in platforms]
    return output


class PlatformCampaignsHandler(AdminHandler):
    def get(self, platform_name):
        """List all existing campaigns available on a given platform."""
        campaigns = [platform.campaign.get() for platform in
                     Platform.query(Platform.name == platform_name, projection=[Platform.campaign])]
        output = [campaign_to_dict(campaign) for campaign in campaigns]
        return output


class CampaignClicksHandler(AdminHandler):
    def get(self, campaign_id, platform_name):
        """Retrieves the number of clicks for given campaign on the given platform."""
        campaign_id = int(campaign_id)
        platform = Platform.get_by_id("%d-%s" % (campaign_id, platform_name))
        return platform_to_dict(platform)


class PlatformClicksHandler(AdminHandler):
    def get(self, platform_name):
        """Retrieve the number of clicks on the given platform."""
        clicks_sum = sum([platform.counter for platform in
                          Platform.query(Platform.name == platform_name, projection=[Platform.counter])])
        return clicks_sum


# TODO: add gzip middleware
app = webapp2.WSGIApplication([
    routes.PathPrefixRoute('/api/admin', [
        webapp2.Route(r'/stats', StatsHandler),
        webapp2.Route(r'/campaign', CampaignCollectionHandler),
        webapp2.Route(r'/campaign/<campaign_id:\d+>/platform/<platform_name>', CampaignClicksHandler),
        webapp2.Route(r'/campaign/<campaign_id:\d+>', CampaignHandler, name="campaign-detail"),
        webapp2.Route(r'/platform/<platform_name>/campaigns', PlatformCampaignsHandler),
        webapp2.Route(r'/platform/<platform_name>/clicks', PlatformClicksHandler),
    ])
], debug=True)
# TODO: disable debug
# TODO: more auth credential into configuraion file
app.error_handlers[405] = handle_error
app.error_handlers[404] = handle_error
app.error_handlers[400] = handle_error
