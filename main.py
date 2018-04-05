#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER
#
# Copyright (c) 2018 Juniper Networks, Inc.
# All rights reserved.
#
# Use is subject to license terms.
#
# Licensed under the Apache License, Version 2.0 (the ?License?); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at http://www.apache.org/licenses/LICENSE-2.0.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


import os.path
import cherrypy
import hashlib
import datetime
import yaml

from jnpr.junos.utils.config import Config
from jnpr.junos import Device
from data.frt import FlowRoutesTable


class MyDev(object):

    def __init__(self):

        self.dev_user = None
        self.dev_ip = None
        self.dev_pw = None
        self.age_out_interval = None
        self.flow_active = dict()
        self.flow_config = dict()

    def addNewFlowRoute(self, flowData=None):

        # env = Environment(autoescape=False,
        #                  loader=FileSystemLoader('./template'), trim_blocks=False, lstrip_blocks=False)
        # template = env.get_template('set-flow-route.conf')

        with Device(host=self.dev_ip, user=self.dev_user, password=self.dev_pw) as dev:
            cu = Config(dev)
            cu.lock()
            cu.load(template_path='template/set-flow-route.conf', template_vars=flowData, merge=True)
            cu.commit()
            cu.unlock()

        self.flow_config[flowData['flowRouteName']] = {'dstPrefix': flowData['dstPrefix'],
                                                       'srcPrefix': flowData['srcPrefix'],
                                                       'protocol': flowData['protocol'], 'dstPort': flowData['dstPort'],
                                                       'srcPort': flowData['srcPort'], 'action': flowData['action']}

    def modFlowRoute(self, flowData=None):

        with Device(host=self.dev_ip, user=self.dev_user, password=self.dev_pw) as dev:
            cu = Config(dev)
            cu.lock()
            cu.load(template_path='template/mod-flow-route.conf', template_vars=flowData)
            cu.commit()
            cu.unlock()

        self.flow_config[flowData['flowRouteName']] = {'dstPrefix': flowData['dstPrefix'],
                                                       'srcPrefix': flowData['srcPrefix'],
                                                       'protocol': flowData['protocol'], 'dstPort': flowData['dstPort'],
                                                       'srcPort': flowData['srcPort'], 'action': flowData['action']}

    def delFlowRoute(self, flowRoute=None):

        with Device(host=self.dev_ip, user=self.dev_user, password=self.dev_pw) as dev:
            cu = Config(dev)
            cu.lock()
            cu.load(template_path='template/delete-flow-route.conf', template_vars=flowRoute, merge=True)
            cu.commit()
            cu.unlock()

        self.flow_config.pop(flowRoute['flowRouteName'], None)

    def getActiveFlowRoutes(self):

        with Device(host=self.dev_ip, user=self.dev_user, password=self.dev_pw) as dev:

            # data = dev.rpc.get_config(filter_xml='routing-options/flow/route/name')
            frt = FlowRoutesTable(dev)
            frt.get()

            for flow in frt:

                destination = flow.destination.split(',')

                for index, item in enumerate(destination):
                    _item = item.split('=')
                    destination[index] = _item[1] if len(_item) > 1 else _item[0]

                hash_object = hashlib.sha512(b'{0}'.format(str(destination)))
                hex_dig = hash_object.hexdigest()

                _age = dict()

                if ':' not in flow.age:
                    _age['current'] = datetime.datetime.strptime(flow.age, '%S').time()
                elif len(flow.age.split(':')) == 2:
                    _age['current'] = datetime.datetime.strptime(flow.age, '%M:%S').time()
                elif len(flow.age.split(':')) == 3:
                    _age['current'] = datetime.datetime.strptime(flow.age, '%H:%M:%S').time()
                else:
                    'error in time format'

                if hex_dig not in self.flow_active:

                    self.flow_active[hex_dig] = {'term': flow.term, 'destination': destination,
                                                 'action': flow.tsi.split(':')[1].strip() if flow.tsi else flow.action,
                                                 'age': _age['current'].strftime("%H:%M:%S"),
                                                 'status': 'new'}
                else:

                    if 'term:N/A' in flow['term']:
                        self.flow_active.pop(hex_dig, None)

                    if _age['current'] > datetime.datetime.strptime(str(self.age_out_interval), '%H:%M:%S').time():
                        self.flow_active[hex_dig]['status'] = 'old'

                    self.flow_active[hex_dig].update({'term': flow.term, 'destination': destination,
                                                      'action': flow.tsi.split(':')[
                                                          1].strip() if flow.tsi else flow.action,
                                                      'age': _age['current'].strftime("%H:%M:%S")})

        return self.flow_active

    def load_flow_config_data(self):

        with Device(host=self.dev_ip, user=self.dev_user, password=self.dev_pw) as dev:
            data = dev.rpc.get_config(options={'format': 'json'})

            if 'route' in data['configuration']['routing-options']['flow']:

                for route in data['configuration']['routing-options']['flow']['route']:
                    _action = dict()

                    for key, value in route['then'].iteritems():

                        if value[0]:
                            _action[key] = {'value': value}
                        else:
                            _action[key] = {'value': None}

                    self.flow_config[route['name']] = {'dstPrefix': route['match']['destination'],
                                                       'srcPrefix': route['match']['source'],
                                                       'protocol': route['match']['protocol'],
                                                       'dstPort': route['match']['destination-port'],
                                                       'srcPort': route['match']['source-port'], 'action': _action}

                return self.flow_config

            else:
                return None

    def save_settings(self, dev_user=None, dev_ip=None, dev_pw=None, age_out_interval=None):

        self.dev_user = dev_user
        self.dev_ip = dev_ip
        self.dev_pw = dev_pw
        self.age_out_interval = age_out_interval

        with open('ui/config.yml', 'w') as fp:
            config = {'dev_user': self.dev_user, 'dev_ip': self.dev_ip, 'dev_pw': self.dev_pw,
                      'age_out_interval': self.age_out_interval}
            yaml.safe_dump(config, fp, default_flow_style=False)

    def load_settings(self):

        with open('ui/config.yml', 'r') as fp:
            _config = fp.read()
            config = yaml.safe_load(_config)
            self.dev_user = config['dev_user']
            self.dev_ip = config['dev_ip']
            self.dev_pw = config['dev_pw']
            self.age_out_interval = config['age_out_interval']


class BGPFlow(object):

    @cherrypy.expose
    def index(self):
        return open('ui/index.html', 'r')


@cherrypy.expose
class BGPFlowWS(object):

    def __init__(self, my_dev=None):
        self.my_dev = my_dev

    @cherrypy.tools.json_out()
    @cherrypy.tools.json_in()
    def GET(self, action=None):

        if action == 'active':
            froutes = self.my_dev.getActiveFlowRoutes()
            return True, froutes

        else:
            return False, 'Action unknown'

    @cherrypy.tools.json_out()
    @cherrypy.tools.json_in()
    def POST(self, action=None):

        if action == 'add':

            input_json = cherrypy.request.json
            self.my_dev.addNewFlowRoute(flowData=input_json)

            return True, 'Added new Flow Route'

        elif action == 'save':

            input_json = cherrypy.request.json
            self.my_dev.save_settings(dev_user=input_json['user'], dev_pw=input_json['password'],
                                      dev_ip=input_json['ip'], age_out_interval=input_json['age_out_interval'])
            return True, 'Saved settings'

        elif action == 'mod':
            input_json = cherrypy.request.json
            self.my_dev.modFlowRoute(flowData=input_json)
            return True, 'Modified flow route'

        elif action == 'del':
            input_json = cherrypy.request.json
            self.my_dev.delFlowRoute(flowRoute=input_json)

            return True, 'Deleted Flow Route'

        else:
            return False, 'Action not defined'


@cherrypy.expose
class DataTable(object):

    def __init__(self, my_dev=None):
        self.my_dev = my_dev

    @cherrypy.tools.json_out()
    def POST(self):
        froutes = self.my_dev.load_flow_config_data()
        return True, froutes


if __name__ == '__main__':
    cherrypy.config.update({'log.screen': False,
                            'log.access_file': '',
                            'log.error_file': ''})
    conf = {
        '/': {
            'tools.sessions.on': True,
            'tools.staticdir.root': os.path.abspath(os.getcwd()),
            'tools.staticdir.on': True,
            'tools.staticdir.dir': 'ui'
        },
        '/api': {
            'request.dispatch': cherrypy.dispatch.MethodDispatcher(),
            'tools.response_headers.on': True,
            'tools.response_headers.headers': [('Content-Type', 'text/plain')],
        },
        '/dt': {
            'request.dispatch': cherrypy.dispatch.MethodDispatcher(),
            'tools.response_headers.on': True,
            'tools.response_headers.headers': [('Content-Type', 'text/plain')],
        },
    }

    my_dev = MyDev()
    my_dev.load_settings()
    webapp = BGPFlow()
    webapp.api = BGPFlowWS(my_dev=my_dev)
    webapp.dt = DataTable(my_dev=my_dev)
    cherrypy.quickstart(webapp, '/', conf)