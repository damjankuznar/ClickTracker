import base64
from datetime import datetime
import json
import os
import webapp2
from google.appengine.ext.ndb.tasklets import Future
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


def handle_error(request, response, exception):
    """Overriding webapp2 default HTTP error output by returning JSON content type by default.
    :param request: Request instance.
    :param response: Response instance.
    :param exception: Exception instance to be handled.
    """
    response.content_type = 'application/json'
    result = {
        'error': str(exception)
    }
    response.write(json.dumps(result))
    if hasattr(exception, "code"):
        response.set_status(exception.code)
    else:
        response.set_status(500)


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
        self.response.content_type = 'application/json'
        try:
            self.check_auth()
            output = super(AdminHandler, self).dispatch()
            if self.response.status_int == 204:
                # if status code is 204, then no content should be returned
                self.response.content_type = None
                self.response.clear()
            if isinstance(output, basestring):
                self.response.write(output)
            elif output is not None:
                self.response.write(json.dumps(output, default=json_serial, sort_keys=True))
        except TrackerException, e:
            self.response.status_int = e.status_code
            self.response.write(json.dumps({"error": e.message}, default=json_serial, sort_keys=True))

    def check_auth(self):
        basic_auth = self.request.headers.get('Authorization')
        if not basic_auth:
            raise TrackerException("Authorization is required.", status_code=401)
        username, password = "", ""
        try:
            user_info = base64.decodestring(basic_auth[6:])
            username, password = user_info.split(':')
        except Exception, e:
            raise TrackerException("Could not parse HTTP Authorization.", status_code=400)
        # check username and password
        if not (username == os.environ.get("TRACKER_ADMIN_USERNAME", None) and
                        password == os.environ.get("TRACKER_ADMIN_PASSWORD", None)):
            raise TrackerException("Invalid authorization credentials.", status_code=401)

    def get_request_json(self):
        """Gets JSON from request or raises TrackerException if JSON invalid."""
        try:
            campaign_dict = json.loads(self.request.body)
        except:
            raise TrackerException("Could not get a valid JSON from request. Please send request as JSON encoded data "
                                   "and set Content-Type as 'application/json'.", status_code=400)
        return campaign_dict


def validate_campaign_dict(campaign_dict, all_required=True):
    valid_keys = {"name", "link", "platforms"}
    errors = []
    dict_keys = set(campaign_dict.keys())
    if all_required:
        # get a list of missing keys
        for missing_key in valid_keys.difference(dict_keys):
            errors.append("Missing parameter '%s'." % missing_key)
    # get a list of invalid keys
    for invalid_key in dict_keys.difference(valid_keys):
        errors.append("Invalid parameter '%s'." % invalid_key)

    # check if platforms are valid
    if "platforms" in campaign_dict:
        if isinstance(campaign_dict["platforms"], list):
            for invalid_platform in set(campaign_dict["platforms"]).difference(set(PLATFORMS)):
                errors.append("Platforms parameter contains invalid platform '%s'." % invalid_platform)
        else:
            errors.append("Platforms parameter must be a list of platform names.")
    # raise exception if any errors were detected
    if errors:
        raise TrackerException("Invalid request. %s" % " ".join(errors), status_code=400)


class CampaignCollectionHandler(AdminHandler):
    def get(self):
        """List all existing campaigns."""

        @ndb.tasklet
        def callback(campaign):
            platforms = yield Platform.query(Platform.campaign == campaign.key,
                                             projection=[Platform.name, Platform.counter]).order(
                Platform.name).fetch_async(3)
            raise ndb.Return(campaign_to_dict(campaign, platforms=platforms))

        query = Campaign.query()
        output = query.map(callback)
        return output

    @ndb.toplevel
    def post(self):
        """Create a new campaign."""
        campaign_dict = self.get_request_json()
        validate_campaign_dict(campaign_dict)
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
            platform = Platform(name=platform_name, counter=0, campaign=campaign.key,
                                id="%d-%s" % (campaign_id, platform_name))
            platforms.append(platform)
        ndb.put_multi_async(platforms)
        # prepare response representation of the created campaign
        output = campaign_to_dict(campaign, platforms=platforms)
        # set the appropriate response headers
        self.response.location = self.uri_for("campaign-detail", campaign_id=campaign_id)
        self.response.status_int = 201
        return output


class CampaignHandler(AdminHandler):
    def get(self, campaign_id):
        """
        Display information about the existing campaign.
        :param campaign_id: ID of the campaign.
        """
        campaign_id = int(campaign_id)
        campaign = Campaign.get_by_id(campaign_id)
        if campaign:
            return campaign_to_dict(campaign)
        else:
            raise TrackerException("Campaign with id %s does not exist." % campaign_id, status_code=204)

    def delete(self, campaign_id):
        """Delete the existing campaign."""
        campaign_id = int(campaign_id)
        campaign = Campaign.get_by_id(campaign_id)

        if campaign:
            # delete the campaign first, so that updates are not possible
            futures = [campaign.key.delete_async()]
            # delete all platforms that correspond to the campaign
            futures.extend(ndb.delete_multi_async([platform.key for platform in
                                                   Platform.query(Platform.campaign == campaign.key).fetch(3)]))
            Future.wait_all(futures)
        else:
            # the campaign does not exist, just send 204
            self.response.status_int = 204

    def put(self, campaign_id):
        """Update the existing campaign."""
        campaign_id = int(campaign_id)
        future = Campaign.get_by_id_async(campaign_id)
        campaign_dict = self.get_request_json()
        validate_campaign_dict(campaign_dict, all_required=False)

        campaign = future.get_result()

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
            # construct platforms for campaign
            for platform_name in platforms_list:
                if platform_name not in existing_platforms_list:
                    platform = Platform(name=platform_name, counter=0, campaign=campaign.key,
                                        id="%d-%s" % (campaign_id, platform_name))
                    platforms_to_store.append(platform)
                else:
                    platform = existing_platforms_list[platform_name]
                platforms.append(platform)
        else:
            # no changes to platforms field, just copy
            for platform in existing_platforms_list.values():
                platforms.append(platform)

        # update the rest of the fields
        for field_name in campaign_dict:
            setattr(campaign, field_name, campaign_dict[field_name])
        campaign.update_date = datetime.now()

        @ndb.transactional_async(xg=True)
        def _update():
            """Do the update in transaction"""
            ndb.put_multi_async(platforms_to_store)
            campaign.put_async()

        future = _update()

        output = campaign_to_dict(campaign, platforms=platforms)
        # explicitly do the json conversion here, while we may be waiting for the _update to finish
        output = json.dumps(output, default=json_serial, sort_keys=True)
        future.get_result()
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
    fetch_platforms = fetch_platforms and platforms is None
    output = campaign.to_dict()

    if fetch_platforms:
        query = Platform.query(Platform.campaign == campaign.key,
                               projection=[Platform.name, Platform.counter]).order(Platform.name).fetch(3)
        output["platform_counters"] = {platform.name: platform.counter for platform in query}
    elif platforms is not None:
        output["platform_counters"] = {platform.name: platform.counter for platform in platforms}
    output["id"] = campaign.key.id()

    return output


class PlatformCampaignsHandler(AdminHandler):
    def get(self, platform_name):
        """List all existing campaigns available on a given platform."""

        @ndb.tasklet
        def callback(platform):
            campaign, platforms = yield platform.campaign.get_async(), \
                                        Platform.query(Platform.campaign == platform.campaign,
                                                       projection=[Platform.name, Platform.counter]).order(
                                            Platform.name).fetch_async(3)
            raise ndb.Return(campaign_to_dict(campaign, platforms=platforms))

        query = Platform.query(Platform.name == platform_name, projection=[Platform.campaign])
        output = query.map(callback)
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

        @ndb.tasklet
        def callback(platform):
            campaign, platforms = yield platform.campaign.get_async(), \
                                        Platform.query(Platform.campaign == platform.campaign,
                                                       projection=[Platform.name, Platform.counter]).order(
                                            Platform.name).fetch_async(3)
            raise ndb.Return(campaign_to_dict(campaign, platforms=platforms))

        return clicks_sum


app = webapp2.WSGIApplication([
    routes.PathPrefixRoute('/api/admin', [
        webapp2.Route(r'/campaign', CampaignCollectionHandler),
        webapp2.Route(r'/campaign/<campaign_id:\d+>/platform/<platform_name>', CampaignClicksHandler),
        webapp2.Route(r'/campaign/<campaign_id:\d+>', CampaignHandler, name="campaign-detail"),
        webapp2.Route(r'/platform/<platform_name>/campaigns', PlatformCampaignsHandler),
        webapp2.Route(r'/platform/<platform_name>/clicks', PlatformClicksHandler),
    ])
], debug=False)
app.error_handlers[405] = handle_error
app.error_handlers[404] = handle_error
app.error_handlers[400] = handle_error
# app.error_handlers[500] = handle_error
