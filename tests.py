# -*- coding: utf-8 -*-
import json
import os
import random
import unittest
from copy import deepcopy

import time
import webtest
from google.appengine.datastore import datastore_stub_util
from google.appengine.ext import testbed
from google.appengine.ext.deferred import deferred

from admin import app as admin_app
from tracker import app as tracker_app


class TrackerTest(unittest.TestCase):
    ADMIN_HEADERS = {
        "Content-type": "application/json",
        "Authorization": "Basic dHJhY2tlcjp0cmFja2Vy"
    }
    CAMPAIGN_SAMPLE = {
        "name": "Campaign name",
        "link": "http://google.com",
        "platforms": ["ios", "android", "wp"]
    }

    def setUp(self):
        self.tracker_app = webtest.TestApp(tracker_app)
        self.admin_app = webtest.TestApp(admin_app)
        self.testbed = testbed.Testbed()
        self.testbed.activate()
        self.testbed.init_datastore_v3_stub()
        self.testbed.init_memcache_stub()

        self.testbed.init_taskqueue_stub(
            root_path=os.path.join(os.path.dirname(__file__), 'resources'))
        self.taskqueue_stub = self.testbed.get_stub(
            testbed.TASKQUEUE_SERVICE_NAME)

        self.testbed.setup_env(
            TRACKER_ADMIN_USERNAME='tracker',
            TRACKER_ADMIN_PASSWORD='tracker',
            TRACKER_COUNTER_UPDATE_INTERVAL_LENGTH="10",
            overwrite=True)

    def tearDown(self):
        self.testbed.deactivate()

    def _check_if_default_redirect(self, response):
        self.assertEqual(response.status_int, 301)
        self.assertEqual(response.headers["Location"], "http://outfit7.com")

    def test_illegal_urls(self):
        response = self.tracker_app.get('/api/campaign/abc/platform/android')
        self._check_if_default_redirect(response)
        response = self.tracker_app.get('/api/campaign/99999999999999999999999999999999999999/platform/android')
        self._check_if_default_redirect(response)
        response = self.tracker_app.get('/api/campaign/čćšđž/platform/android')
        self._check_if_default_redirect(response)
        response = self.tracker_app.get('/api/campaign/sad/platform/orei')
        self._check_if_default_redirect(response)

    def test_illegal_http_method(self):
        response = self.tracker_app.post('/api/campaign/1/platform/android', expect_errors=True)
        self.assertEqual(response.status_int, 405)
        response = self.tracker_app.delete('/api/campaign/1/platform/android', expect_errors=True)
        self.assertEqual(response.status_int, 405)
        response = self.tracker_app.put('/api/campaign/1/platform/android', expect_errors=True)
        self.assertEqual(response.status_int, 405)

    def test_create_campaign_and_track_click(self):
        # create new campaign
        response = self.admin_app.post("/api/admin/campaign", params=json.dumps(self.CAMPAIGN_SAMPLE),
                                       headers=self.ADMIN_HEADERS)
        self.assertEqual(response.status_int, 201)
        self.assertIn("Location", response.headers)
        campaign_url = response.headers["Location"]
        campaign = json.loads(response.body)
        # check if response contains all necessary data
        self.assertEqual({"id", "name", "link", "create_date", "update_date", "platform_counters"},
                         set(campaign.keys()))
        # check if counters are 0
        for platform in campaign["platform_counters"]:
            self.assertEqual(campaign["platform_counters"][platform], 0)
        self.assertIsNone(campaign["update_date"])

        # get new campaign details
        response = self.admin_app.get(campaign_url, headers=self.ADMIN_HEADERS)
        self.assertEqual(response.status_int, 200)
        self.assertEqual(response.content_type, "application/json")
        campaign = json.loads(response.body)
        # check if counters are 0
        for platform in campaign["platform_counters"]:
            self.assertEqual(campaign["platform_counters"][platform], 0)

        # generate a user click
        response = self.tracker_app.get('/api/campaign/%d/platform/android' % campaign["id"])
        self.assertEqual(response.status_int, 302)
        self.assertIn("Location", response.headers)
        self.assertNotEqual(response.headers["Location"], "http://outfit7.com")

        # run the background task to store the click in Datastore
        [deferred.run(task.payload) for task in self.taskqueue_stub.get_filtered_tasks()]

        # check if click was stored properly
        response = self.admin_app.get("/api/admin/campaign/%d/platform/android" % campaign["id"],
                                      headers=self.ADMIN_HEADERS)
        data = json.loads(response.body)
        self.assertEqual(data["counter"], 1)

    def test_invalid_create_campaign(self):
        def check_missing_parameter(parameter):
            campaign_dict = deepcopy(self.CAMPAIGN_SAMPLE)
            del campaign_dict[parameter]
            response = self.admin_app.post("/api/admin/campaign", params=json.dumps(campaign_dict),
                                           headers=self.ADMIN_HEADERS, expect_errors=True)
            self.assertEqual(response.status_int, 400)
            self.assertIn("error", json.loads(response.body))

        map(check_missing_parameter, ["name", "link", "platforms"])

        campaign_dict = deepcopy(self.CAMPAIGN_SAMPLE)
        campaign_dict["id"] = 123
        response = self.admin_app.post("/api/admin/campaign", params=json.dumps(campaign_dict),
                                       headers=self.ADMIN_HEADERS, expect_errors=True)
        self.assertEqual(response.status_int, 400)
        self.assertIn("error", json.loads(response.body))

        campaign_dict = deepcopy(self.CAMPAIGN_SAMPLE)
        campaign_dict["platforms"] = "foo bar"
        response = self.admin_app.post("/api/admin/campaign", params=json.dumps(campaign_dict),
                                       headers=self.ADMIN_HEADERS, expect_errors=True)
        self.assertEqual(response.status_int, 400)
        self.assertIn("error", json.loads(response.body))

        campaign_dict = deepcopy(self.CAMPAIGN_SAMPLE)
        campaign_dict["platforms"] = ["foo", "bar", "android"]
        response = self.admin_app.post("/api/admin/campaign", params=json.dumps(campaign_dict),
                                       headers=self.ADMIN_HEADERS, expect_errors=True)
        self.assertEqual(response.status_int, 400)
        self.assertIn("error", json.loads(response.body))

    def test_update_campaign(self):
        self.policy = datastore_stub_util.PseudoRandomHRConsistencyPolicy(probability=0)
        self.testbed.init_datastore_v3_stub(consistency_policy=self.policy)
        # create new campaign
        response = self.admin_app.post("/api/admin/campaign", params=json.dumps(self.CAMPAIGN_SAMPLE),
                                       headers=self.ADMIN_HEADERS)
        campaign = json.loads(response.body)
        campaign_id = campaign["id"]
        campaign_url = response.headers["Location"]

        # simulate a user click
        response = self.tracker_app.get('/api/campaign/%d/platform/android' % campaign_id)
        # run the background task to store the click in Datastore
        [deferred.run(task.payload) for task in self.taskqueue_stub.get_filtered_tasks()]

        campaign_new = deepcopy(self.CAMPAIGN_SAMPLE)
        campaign_new["name"] = "new name"
        response = self.admin_app.put(campaign_url, params=json.dumps(self.CAMPAIGN_SAMPLE),
                                      headers=self.ADMIN_HEADERS)
        
        campaign_updated = json.loads(response.body)
        # check if update resets counter (it should not)
        self.assertEqual(campaign_updated["platform_counters"]["android"], 1)
        # check if update_date is not null any more
        self.assertIsNotNone(campaign_updated["update_date"])

    def test_invalid_update_campaign(self):
        self.policy = datastore_stub_util.PseudoRandomHRConsistencyPolicy(probability=0)
        self.testbed.init_datastore_v3_stub(consistency_policy=self.policy)
        # create new campaign
        response = self.admin_app.post("/api/admin/campaign", params=json.dumps(self.CAMPAIGN_SAMPLE),
                                       headers=self.ADMIN_HEADERS)
        campaign = json.loads(response.body)
        campaign_id = campaign["id"]
        campaign_url = response.headers["Location"]

        # simulate a user click
        self.tracker_app.get('/api/campaign/%d/platform/android' % campaign_id)
        # run the background task to store the click in Datastore
        [deferred.run(task.payload) for task in self.taskqueue_stub.get_filtered_tasks()]

        def check_missing_parameter(parameter):
            campaign_dict = deepcopy(self.CAMPAIGN_SAMPLE)
            del campaign_dict[parameter]
            response = self.admin_app.put(campaign_url, params=json.dumps(campaign_dict),
                                          headers=self.ADMIN_HEADERS)
            self.assertEqual(response.status_int, 200)

        map(check_missing_parameter, ["name", "link", "platforms"])

        campaign_update = {"platforms": ["android"]}
        response = self.admin_app.put(campaign_url, params=json.dumps(campaign_update),
                                      headers=self.ADMIN_HEADERS)
        campaign_updated = json.loads(response.body)
        self.assertEqual(response.status_int, 200)
        self.assertEqual({"id", "name", "link", "create_date", "update_date", "platform_counters"},
                         set(campaign_updated.keys()))
        self.assertEqual(["android"], campaign_updated["platform_counters"].keys())

    def test_platform_clicks(self):
        # generate some campaigns
        campaign_ids = []
        for i in range(10):
            response = self.admin_app.post("/api/admin/campaign", params=json.dumps(self.CAMPAIGN_SAMPLE),
                                           headers=self.ADMIN_HEADERS)
            campaign = json.loads(response.body)
            campaign_ids.append(campaign["id"])

        # make 10 clicks to android platform and randomly selected campaigns
        for i in range(10):
            self.tracker_app.get('/api/campaign/%d/platform/android' % random.sample(campaign_ids, 1)[0])
        # run the background task to store the clicks in Datastore
        [deferred.run(task.payload) for task in self.taskqueue_stub.get_filtered_tasks()]

        response = self.admin_app.get("/api/admin/platform/android/clicks", headers=self.ADMIN_HEADERS)
        results = json.loads(response.body)
        self.assertEqual(results, 10)

    def test_platform_campaigns(self):
        # generate some campaigns
        campaign_ids = []
        for i in range(10):
            response = self.admin_app.post("/api/admin/campaign", params=json.dumps(self.CAMPAIGN_SAMPLE),
                                           headers=self.ADMIN_HEADERS)
            campaign = json.loads(response.body)
            campaign_ids.append(campaign["id"])

        response = self.admin_app.get("/api/admin/platform/android/campaigns", headers=self.ADMIN_HEADERS)
        results = json.loads(response.body)
        self.assertEqual(len(results), 10)

    def test_delete_campaign(self):
        # create new campaign
        response = self.admin_app.post("/api/admin/campaign", params=json.dumps(self.CAMPAIGN_SAMPLE),
                                       headers=self.ADMIN_HEADERS)
        campaign = json.loads(response.body)
        campaign_id = campaign["id"]

        # delete the campaign
        response = self.admin_app.delete("/api/admin/campaign/%d" % campaign_id, headers=self.ADMIN_HEADERS)
        self.assertEqual(response.status_int, 200)

        # delete non-existent campaign
        response = self.admin_app.delete("/api/admin/campaign/999", headers=self.ADMIN_HEADERS, expect_errors=True)
        self.assertEqual(response.status_int, 204)
