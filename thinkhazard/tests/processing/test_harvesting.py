# -*- coding: utf-8 -*-
#
# Copyright (C) 2015-2017 by the GFDRR / World Bank
#
# This file is part of ThinkHazard.
#
# ThinkHazard is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.
#
# ThinkHazard is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along with
# ThinkHazard.  If not, see <http://www.gnu.org/licenses/>.

import unittest
import transaction
from datetime import datetime, timedelta
from mock import Mock, patch, mock_open
import httplib2
import json

from ...models import (
    DBSession,
    FurtherResource,
    HazardSet,
    Layer,
    Region,
    )

from .. import settings
from . import populate_datamart
from ...processing.harvesting import Harvester


def populate():
    DBSession.query(Layer).delete()
    DBSession.query(HazardSet).delete()
    DBSession.query(Region).delete()
    populate_datamart()
    transaction.commit()


date_str = datetime.utcnow().isoformat()


layers_defaults = {
    "id": 1,
    "csw_type": 'dataset',
    "title": "test layer",
    "data_update_date": date_str,
    "detail_url": 'www.test.com',
    "download_url": 'test.tif',
    "srid": "EPSG:4326"
}
layer_defaults = layers_defaults
layer_defaults.update({
    "calculation_method_quality": 5,
    "hazard_period": 10,
    "hazard_unit": 'm',
    "hazard_set": 'TEST_GLOBAL',
    "hazard_type": 'river_flood',
    "metadata_update_date": date_str,
    "owner": {
        "organization": ''
    },
    "scientific_quality": 5
})


def layers(values=[{}]):
    layers = []
    for value in values:
        layer = layers_defaults.copy()
        layer.update(value)
        layers.append(layer)
    return layers


def layer(value={}):
    layer = layer_defaults.copy()
    layer.update(value)
    return layer


@patch('thinkhazard.processing.harvesting.open', mock_open())
class TestHarvesting(unittest.TestCase):

    def setUp(self):  # NOQA
        populate()

    @patch.object(Harvester, 'do_execute')
    def test_cli(self, mock):
        '''Test harvester cli'''
        Harvester.run(['harvest', '--config_uri', 'tests.ini'])
        mock.assert_called_with(hazard_type=None)

    @patch.object(Harvester, 'fetch', return_value=[])
    def test_force(self, fetch_mock):
        '''Test harvester in force mode'''
        Harvester().execute(settings, force=True)

    @patch.object(Harvester, 'fetch', return_value=[{
        "id": 1,
        "name_en": u"Test region",
        "level": 3
    }])
    def test_valid_region(self, fetch_mock):
        '''Valid region must be added to database'''
        fetch_mock
        harvester = Harvester()
        harvester.settings = settings

        harvester.harvest_regions()

        self.assertEqual(DBSession.query(Region).count(), 2)

    @patch.object(Harvester, 'fetch', return_value=layers())
    @patch.object(httplib2.Http, 'request', return_value=(
        Mock(status=200),
        json.dumps(layer())
    ))
    def test_valid_layer(self, request_mock, fetch_mock):
        '''Valid layer must be added to database'''
        harvester = Harvester()
        harvester.settings = settings

        harvester.harvest_layers()

        self.assertEqual(DBSession.query(Layer).count(), 1)

    @patch.object(Harvester, 'fetch', return_value=[{
        "id": 1,
        "title": u"Test document",
        "supplemental_information": ''
    }])
    @patch.object(httplib2.Http, 'request', return_value=(
        Mock(status=200),
        json.dumps({
            "id": 1,
            "csw_type": 'document',
            "hazard_type": 'earthquake',
            "regions": [],
            "supplemental_information": '',
            "title": u"Test document"
        })))
    def test_valid_document(self, request_mock, fetch_mock):
        '''Valid document must be added to database'''
        harvester = Harvester()
        harvester.settings = settings

        harvester.harvest_documents()

        self.assertEqual(DBSession.query(FurtherResource).count(), 1)

    @patch.object(Harvester, 'fetch', return_value=layers())
    @patch.object(httplib2.Http, 'request', side_effect=[
        (Mock(status=200), json.dumps(layer({
            "data_update_date": (datetime.utcnow() - timedelta(days=1)).
            isoformat()
        }))),
        (Mock(status=200), json.dumps(layer({
            "data_update_date": datetime.utcnow().isoformat()
        })))
    ])
    def test_data_update_date_change(self, request_mock, fetch_mock):
        '''New data_update_date must reset hazarset.complete and processed'''
        harvester = Harvester()
        harvester.settings = settings
        harvester.harvest_layers()

        hazardset = DBSession.query(HazardSet).one()
        hazardset.complete = True
        hazardset.processed = datetime.now()

        harvester.harvest_layers()

        hazardset = DBSession.query(HazardSet).one()
        self.assertEqual(hazardset.complete, False)
        self.assertEqual(hazardset.processed, None)

    @patch.object(Harvester, 'fetch', return_value=layers())
    @patch.object(httplib2.Http, 'request', side_effect=[
        (Mock(status=200), json.dumps(layer({
            "metadata_update_date": (datetime.utcnow() - timedelta(days=1)).
            isoformat()
        }))),
        (Mock(status=200), json.dumps(layer({
            "metadata_update_date": datetime.utcnow().isoformat()
        })))
    ])
    def test_metadata_update_date_change(self, request_mock, fetch_mock):
        '''New metadata_update_date must reset hazarset.complete'''
        harvester = Harvester()
        harvester.settings = settings
        harvester.harvest_layers()

        hazardset = DBSession.query(HazardSet).one()
        hazardset.complete = True
        hazardset.processed = datetime.now()

        harvester.harvest_layers()

        hazardset = DBSession.query(HazardSet).one()
        self.assertEqual(hazardset.complete, False)

    @patch.object(Harvester, 'fetch', return_value=layers())
    @patch.object(httplib2.Http, 'request', side_effect=[
        (Mock(status=200), json.dumps(layer({
            "calculation_method_quality": 1
        }))),
        (Mock(status=200), json.dumps(layer({
            "calculation_method_quality": 2
        })))
    ])
    def test_calculation_method_quality_change(self, request_mock, fetch_mock):
        '''New calculation_method_quality must reset hazarset.complete'''
        harvester = Harvester()
        harvester.settings = settings
        harvester.harvest_layers()

        hazardset = DBSession.query(HazardSet).one()
        hazardset.complete = True
        hazardset.processed = datetime.now()

        harvester.harvest_layers()

        hazardset = DBSession.query(HazardSet).one()
        self.assertEqual(hazardset.complete, False)

    @patch.object(Harvester, 'fetch', return_value=layers())
    @patch.object(httplib2.Http, 'request', side_effect=[
        (Mock(status=200), json.dumps(layer({
            "scientific_quality": 1
        }))),
        (Mock(status=200), json.dumps(layer({
            "scientific_quality": 2
        })))
    ])
    def test_scientific_quality_change(self, request_mock, fetch_mock):
        '''New scientific_quality must reset hazarset.complete'''
        harvester = Harvester()
        harvester.settings = settings
        harvester.harvest_layers()

        hazardset = DBSession.query(HazardSet).one()
        hazardset.complete = True
        hazardset.processed = datetime.now()

        harvester.harvest_layers()

        hazardset = DBSession.query(HazardSet).one()
        self.assertEqual(hazardset.complete, False)

    @patch.object(httplib2.Http, 'request', side_effect=[
        (Mock(status=200), json.dumps(layer({
            "typename": 'hazard:adm2_fu_raster_v3'
        }))),
        (Mock(status=500), json.dumps({
            "error_message": "Some error."
        })),
    ])
    def test_layers_api_500(self, request_mock):
        '''Geonode API status 500 must not corrupt data'''
        harvester = Harvester()
        harvester.settings = settings

        harvester.harvest_layer(layers()[0])

        with self.assertRaises(Exception) as cm:
            harvester.harvest_layer(layers()[0])

        self.assertEqual(
            cm.exception.message,
            u'Geonode returned status 500: {"error_message": "Some error."}')

        layer = DBSession.query(Layer).one()
        self.assertEqual(layer.typename, 'hazard:adm2_fu_raster_v3')
