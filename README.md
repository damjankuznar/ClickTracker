Click Tracker API
=========

REST API backend for tracking user campaign clicks and redirecting them
to appropriate links.


## Running locally
To run the backend locally you must first install the Google App Engine SDK for
Python. See the official installation instructions [here](https://cloud.google.com/appengine/downloads#Google_App_Engine_SDK_for_Python).
The you can run the backend using the following command:
```bash
cd <path_to_project_folder>
/usr/bin/python2.7 <path_to_gae_sdk>/dev_appserver.py --host localhost .
```
Here is a list of few backend API calls using `curl`. For complete reference see
the __API reference__ section
```bash
echo "create a campaign"
curl -X POST -v -H "Authorization: Basic dHJhY2tlcjp0cmFja2Vy" \
-H "Content-type: application/json" \
-d '{"name": "Campaign name", "link": "http://campaign_link.com", "platforms": ["android", "ios"]}' \
http://localhost:8080/api/admin/campaign

echo "generate a click (copy the campaign id from the output above)"
curl -X GET -v http://localhost:8080/api/campaign/6323566249246720/platform/ios

echo "get campaign details"
curl -X GET -v -H "Authorization: Basic dHJhY2tlcjp0cmFja2Vy" \
-H "Content-type: application/json" \ http://localhost:8080/api/admin/campaign/6323566249246720
```

## Deploying to Google App Engine
Deployment to Google App Engine is performed using the `appcfg.py` script that
is provided with the SDK. To deploy it, use the following command:
```bash
cd <path_to_project_folder>
/usr/bin/python2.7 <path_to_gae_sdk>/appcfg.py -A <YOUR_PROJECT_ID> update app.yaml
/usr/bin/python2.7 <path_to_gae_sdk>/appcfg.py -A <YOUR_PROJECT_ID> update_indexes .
```
You need to provide your project id that you can obtain from the [Google Cloud
Platform Console](https://console.cloud.google.com/).

Demo backend deployment is available here: http://click-tracker-1268.appspot.com

## Running tests
Unit tests are provided with the project. Make sure you have a Python package `webtest` installed. You can install it by running `sudo pip install webtest`.
To run the tests simply invoke the supplied script:
```bash
cd <path_to_project_folder>
/usr/bin/python2.7 test_runner.py <path_to_gae_sdk> .
```

## Settings
Settings for the backend are applied through the use of environment variables in
file `app.yaml`. You can set the username and password for the private API calls
and counter update interval (see section __Assumptions__ for details).

## API Reference

### Public endpoint

#### GET `/api/campaign/<campaign_id>/platform/<platform_name>`
Handles incoming clicks for given campaign_id and platform_name. If click is valid then user is redirected to url defined in the campaign and statistic about this click is saved. All invalid clicks (e.g. for non existing campaigns, platforms) users are redirected to http://outfit7.com.

### Private endpoints
All access to private endpoints is restricted with HTTP Basic Authorization. All calls therefore need the `Authorization: Basic <credentials>` header to be set.

#### GET `/api/admin/campaign`
List all existing campaigns.

#### POST `/api/admin/campaign`
Create a new campaign. The campaign data must be JSON encoded, Content-Type set to 'application/json' and have the following form:
```javascript
{
    "name": "Name of the campaign",
    "link": "Link to where the user will be redirected",
    "platforms": ["android", "ios", "wp"]
}
```
The `platforms` parameter lists on which platforms this campaign will be active. Possible values are __android__, __ios__ and __wp__.

#### GET `/campaign/<campaign_id>`
Get information about the existing campaign.

#### UPDATE `/campaign/<campaign_id>`
Update the existing campaign. Data must be provided the same way as for the creation of a new campaign, however, parameters that are not being updated can be omitted.

#### DELETE `/campaign/<campaign_id>`
Delete the existing campaign.

#### GET `/campaign/<campaign_id>/platform/<platform_name>`
Retrieves the number of clicks for given campaign on the given platform.

#### GET `/platform/<platform_name>/campaigns`
List all existing campaigns available on a given platform.

#### GET `/platform/<platform_name>/clicks`
Retrieve the number of clicks on the given platform.

## Assumptions
To circumvent the Google App Engine Datastore limits on the number of updates to
entites (limit of 1 update per second) memcache was employed to temporarily
store the counter delta values (number of clicks since the last update to the Datastore) and stored into the Datastore at predefined intervals (every platform counter is permanently updated on every *N* seconds, where *N* is configurable through the environment variable `TRACKER_COUNTER_UPDATE_INTERVAL_LENGTH`, see `app.yaml`).
The assumption is that occasional loss (due to memcache) of *N* seconds worth of clicks is not critical. Memcache also incurs *N* seconds of delay to the click statistics. However, memcache has some benefits over implementation using sharded counters, such as the cost of read/write operations and speed.
