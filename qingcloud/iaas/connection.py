# =========================================================================
# Copyright 2012-present Yunify, Inc.
# -------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========================================================================
import random
import sys
import time
import uuid

from qingcloud.iaas.actions.alarm_policy import AlarmPolicy
from qingcloud.iaas.actions.nic import NicAction

from qingcloud.conn.auth import QuerySignatureAuthHandler
from qingcloud.conn.connection import HttpConnection, HTTPRequest
from qingcloud.iaas.actions.s2 import S2Action
from qingcloud.misc.json_tool import json_load, json_dump
from qingcloud.misc.utils import filter_out_none
from . import constants as const
from .consolidator import RequestChecker
from .monitor import MonitorProcessor
from .errors import InvalidAction


class APIConnection(HttpConnection):
    """ Public connection to qingcloud service
    """
    req_checker = RequestChecker()

    def __init__(self, qy_access_key_id=None, qy_secret_access_key=None, zone=None,
                 host="api.qingcloud.com", port=443, protocol="https",
                 pool=None, expires=None,
                 retry_time=2, http_socket_timeout=60, debug=False,
                 credential_proxy_host="254.254.254.254", credential_proxy_port=80):
        """
        @param qy_access_key_id - the access key id
        @param qy_secret_access_key - the secret access key
        @param zone - the zone id to access
        @param host - the host to make the connection to
        @param port - the port to use when connect to host
        @param protocol - the protocol to access to web server, "http" or "https"
        @param pool - the connection pool
        @param retry_time - the retry_time when message send fail
        @param token -
        @param credential_proxy -
        """
        # Set default zone
        self.zone = zone
        # Set retry times
        self.retry_time = retry_time

        super(APIConnection, self).__init__(
            qy_access_key_id, qy_secret_access_key, host, port, protocol,
            pool, expires, http_socket_timeout, debug, credential_proxy_host, credential_proxy_port)

        # TODO: check credential version
        if self.qy_access_key_id:
            self._auth_handler = QuerySignatureAuthHandler(self.host,
                                                           self.qy_access_key_id, self.qy_secret_access_key)

        # other apis
        # TODO: seperate functions in this class into each function class
        self.actions = [
            NicAction(self),
            AlarmPolicy(self),
            S2Action(self),
        ]

    def send_request(self, action, body, url="/iaas/", verb="GET"):
        """ Send request
        """
        request = body
        request['action'] = action
        request.setdefault('zone', self.zone)
        if self.debug:
            print(json_dump(request))
            sys.stdout.flush()
        if self.expires:
            request['expires'] = self.expires

        retry_time = 0
        while retry_time < self.retry_time:
            # Use binary exponential backoff to desynchronize client requests
            next_sleep = random.random() * (2 ** retry_time)
            try:
                response = self.send(verb, url, request)
                if response.status == 200:
                    resp_str = response.read()
                    if type(resp_str) != str:
                        resp_str = resp_str.decode()
                    if self.debug:
                        print(resp_str)
                        sys.stdout.flush()
                    if resp_str and json_load(resp_str).get("ret_code") == 5000 and retry_time < self.retry_time - 1:
                        self._get_conn(self.host, self.port)
                        time.sleep(next_sleep)
                        retry_time += 1
                        continue
                    if resp_str and json_load(resp_str).get("ret_code") == 2001 and retry_time < self.retry_time - 1:
                        self.refresh_token()
                        time.sleep(next_sleep)
                        retry_time += 1
                        continue
                    return json_load(resp_str) if resp_str else ""
            except:
                if retry_time < self.retry_time - 1:
                    self._get_conn(self.host, self.port)
                else:
                    raise

            time.sleep(next_sleep)
            retry_time += 1

    def _gen_req_id(self):
        return uuid.uuid4().hex

    def build_http_request(self, verb, url, base_params, auth_path=None,
                           headers=None, host=None, data=""):
        params = {}
        for key, values in base_params.items():
            if values is None:
                continue
            if isinstance(values, list):
                for i in range(1, len(values) + 1):
                    if isinstance(values[i - 1], dict):
                        for sk, sv in values[i - 1].items():
                            if isinstance(sv, dict) or isinstance(sv, list):
                                sv = json_dump(sv)
                            params['%s.%d.%s' % (key, i, sk)] = sv
                    else:
                        params['%s.%d' % (key, i)] = values[i - 1]
            else:
                params[key] = values

        # add req_id
        params.setdefault('req_id', self._gen_req_id())

        return HTTPRequest(verb, self.protocol, headers, self.host, self.port,
                           url, params)

    def describe_notification_center_user_posts(self,
                                                post_type=None,
                                                status=None,
                                                limit=None,
                                                offset=None,
                                                **ignore):
        """ Describe posts in notification center

        @param post_type: specify the type of post, valid values: failures, products
        @param status: filter by status: new, read
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_NOTIFICATION_CENTER_USER_POSTS
        valid_keys = ['post_type', 'status', 'offset', 'limit']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             integer_params=["offset", "limit"],
                                             list_params=["post_type", "status"]):
            return None

        return self.send_request(action, body)

    def describe_zones(self):
        """ Describe zones
        """
        action = const.ACTION_DESCRIBE_ZONES
        body = {}
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             ):
            return None

        return self.send_request(action, body)

    def describe_jobs(self, jobs=None,
                      status=None,
                      job_action=None,
                      offset=None,
                      limit=None,
                      **ignore):
        """ Describe jobs.
        @param jobs: the IDs of job you want to describe.
        @param status: valid values include pending, working, failed, successful.
        @param job_action: the action of job you want to describe.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_JOBS
        valid_keys = ['jobs', 'status', 'job_action', 'offset', 'limit']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 "offset", "limit"],
                                             list_params=["jobs"]
                                             ):
            return None

        return self.send_request(action, body)

    def describe_images(self, images=None,
                        tags=None,
                        os_family=None,
                        processor_type=None,
                        status=None,
                        visibility=None,
                        provider=None,
                        verbose=0,
                        search_word=None,
                        owner=None,
                        offset=None,
                        limit=None,
                        **ignore):
        """ Describe images filtered by condition.
        @param images: an array including IDs of the images you want to list.
                       No ID specified means list all.
        @param tags: the array of IDs of tags.
        @param os_family: os family, windows/debian/centos/ubuntu.
        @param processor_type: supported processor types are `64bit` and `32bit`.
        @param status: valid values include pending, available, deleted, ceased.
        @param visibility: who can see and use this image. Valid values include public, private.
        @param provider: who provide this image, self, system.
        @param verbose: the number to specify the verbose level,
                        larger the number, the more detailed information will be returned.
        @param search_word: the search word.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """

        action = const.ACTION_DESCRIBE_IMAGES
        valid_keys = ['images', 'os_family', 'processor_type', 'status', 'visibility',
                      'provider', 'verbose', 'search_word', 'offset', 'limit', 'owner',
                      'tags']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 "offset", "limit", "verbose"],
                                             list_params=["images", "tags"]
                                             ):
            return None

        return self.send_request(action, body)

    def capture_instance(self, instance,
                         image_name="",
                         **ignore):
        """ Capture an instance and make it available as an image for reuse.
        @param instance: ID of the instance you want to capture.
        @param image_name: short name of the image.
        """
        action = const.ACTION_CAPTURE_INSTANCE
        valid_keys = ['instance', 'image_name']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['instance'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def delete_images(self, images,
                      **ignore):
        """ Delete one or more images whose provider is `self`.
        @param images: ID of the images you want to delete.
        """
        action = const.ACTION_DELETE_IMAGES
        body = {'images': images}
        if not self.req_checker.check_params(body,
                                             required_params=['images'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def modify_image_attributes(self, image,
                                image_name=None,
                                description=None,
                                **ignore):
        """ Modify image attributes.
        @param image: the ID of image whose attributes you want to modify.
        @param image_name: Name of the image. It's a short name for the image
                           that more meaningful than image id.
        @param description: The detailed description of the image.
        """
        action = const.ACTION_MODIFY_IMAGE_ATTRIBUTES
        valid_keys = ['image', 'image_name', 'description']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['image'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def describe_instances(self, instances=None,
                           image_id=None,
                           instance_type=None,
                           status=None,
                           owner=None,
                           search_word=None,
                           verbose=0,
                           offset=None,
                           limit=None,
                           tags=None,
                           **ignore):
        """ Describe instances filtered by conditions
        @param instances : the array of IDs of instances
        @param image_id : ID of the image which is used to launch this instance.
        @param instance_type: The instance type.
                              See: https://docs.qingcloud.com/api/common/includes/instance_type.html
        @param status : Status of the instance, including pending, running, stopped, terminated.
        @param verbose: the number to specify the verbose level, larger the number, the more detailed information will be returned.
        @param search_word: the combined search column.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        @param tags : the array of IDs of tags.
        """
        action = const.ACTION_DESCRIBE_INSTANCES
        valid_keys = ['instances', 'image_id', 'instance_type', 'status',
                      'search_word', 'verbose', 'offset', 'limit', 'tags', 'owner']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'offset', 'limit', 'verbose'],
                                             list_params=[
                                                 'instances', 'status', 'tags']
                                             ):
            return None

        return self.send_request(action, body)

    def run_instances(self, image_id,
                      instance_type=None,
                      cpu=None,
                      memory=None,
                      count=1,
                      instance_name="",
                      vxnets=None,
                      security_group=None,
                      login_mode=None,
                      login_keypair=None,
                      login_passwd=None,
                      need_newsid=False,
                      volumes=None,
                      need_userdata=0,
                      userdata_type=None,
                      userdata_value=None,
                      userdata_path=None,
                      instance_class=None,
                      hostname=None,
                      target_user=None,
                      nic_mqueue=0,
                      cpu_max=None,
                      mem_max=None,
                      **ignore):
        """ Create one or more instances.
        @param image_id : ID of the image you want to use, "img-12345"
        @param instance_type: What kind of instance you want to launch.
                              See: https://docs.qingcloud.com/api/common/includes/instance_type.html
        @param cpu: cpu core number.
        @param memory: memory size in MB.
        @param instance_name: a meaningful short name of instance.
        @param count : The number of instances to launch, default 1.
        @param vxnets : The IDs of vxnets the instance will join.
        @param security_group: The ID of security group that will apply to instance.
        @param login_mode: ssh login mode, "keypair" or "passwd"
        @param login_keypair: login keypair id
        @param login_passwd: login passwd
        @param need_newsid: Whether to generate new SID for the instance (True) or not
                            (False). Only valid for Windows instance; Silently ignored
                            for Linux instance.
        @param volumes: the IDs of volumes you want to attach to newly created instance,
                        parameter only affected when count = 1.
        @param need_userdata: Whether to enable userdata feature. 1 for enable, 0 for disable.
        @param userdata_type: valid type is either 'plain' or 'tar'
        @param userdata_value: base64 encoded string for type 'plain'; attachment id for type 'tar'
        @param userdata_path: path of metadata and userdata.string file to be stored
        @param instance_class: 0 is performance; 1 is high performance
        @param target_user: ID of user who will own this resource, should be one of your sub-accounts
        @param nic_mqueue: enable NIC multi-queue
        @param cpu_max: max cpu core number.
        @param mem_max: max memory size in MB.
        """
        action = const.ACTION_RUN_INSTANCES
        valid_keys = ['image_id', 'instance_type', 'cpu', 'memory', 'count',
                      'instance_name', 'vxnets', 'security_group', 'login_mode',
                      'login_keypair', 'login_passwd', 'need_newsid',
                      'volumes', 'need_userdata', 'userdata_type',
                      'userdata_value', 'userdata_path', 'instance_class',
                      'hostname', 'target_user', 'nic_mqueue', 'cpu_max', 'mem_max',
                      ]
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['image_id'],
                                             integer_params=['count', 'cpu', 'memory', 'need_newsid',
                                                             'need_userdata', 'instance_class',
                                                             'nic_mqueue', 'cpu_max', 'mem_max'],
                                             list_params=['volumes']
                                             ):
            return None

        return self.send_request(action, body)

    def run_instances_by_configuration(self, launch_configuration,
                                       instance_name='',
                                       count=1,
                                       volumes=None,
                                       **ignore):
        """ Run one or more instances by launch configuration.
        @param launch_configuration: ID of launch configuration you want to use
        @param instance_name: a meaningful short name of instance.
        @param count : The number of instances to launch, default 1.
        @param volumes: the ids of volumes will be attached.
        """
        action = const.ACTION_RUN_INSTANCES_BY_CONFIGURATION
        valid_keys = ['launch_configuration', 'instance_name', 'count', 'volumes']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'launch_configuration'],
                                             integer_params=['count'],
                                             list_params=['volumes']
                                             ):
            return None

        return self.send_request(action, body)

    def terminate_instances(self, instances,
                            **ignore):
        """ Terminate one or more instances.
        @param instances : An array including IDs of the instances you want to terminate.
        """
        action = const.ACTION_TERMINATE_INSTANCES
        body = {'instances': instances}
        if not self.req_checker.check_params(body,
                                             required_params=['instances'],
                                             integer_params=[],
                                             list_params=['instances']
                                             ):
            return None

        return self.send_request(action, body)

    def stop_instances(self, instances,
                       force=False,
                       **ignore):
        """ Stop one or more instances.
        @param instances : An array including IDs of the instances you want to stop.
        @param force: False for gracefully shutdown and True for forcibly shutdown.
        """
        action = const.ACTION_STOP_INSTANCES
        body = {'instances': instances, 'force': int(force)}
        if not self.req_checker.check_params(body,
                                             required_params=['instances'],
                                             integer_params=['force'],
                                             list_params=['instances']
                                             ):
            return None

        return self.send_request(action, body)

    def restart_instances(self, instances,
                          **ignore):
        """ Restart one or more instances.
        @param instances : An array including IDs of the instances you want to restart.
        """

        action = const.ACTION_RESTART_INSTANCES
        body = {'instances': instances}
        if not self.req_checker.check_params(body,
                                             required_params=['instances'],
                                             integer_params=[],
                                             list_params=['instances']
                                             ):
            return None

        return self.send_request(action, body)

    def start_instances(self, instances,
                        **ignore):
        """ Start one or more instances.
        @param instances : An array including IDs of the instances you want to start.
        """
        action = const.ACTION_START_INSTANCES
        body = {'instances': instances}
        if not self.req_checker.check_params(body,
                                             required_params=['instances'],
                                             integer_params=[],
                                             list_params=['instances']
                                             ):
            return None

        return self.send_request(action, body)

    def reset_instances(self, instances,
                        login_mode=None,
                        login_passwd=None,
                        login_keypair=None,
                        need_newsid=False,
                        **ignore):
        """ Reset one or monre instances to its initial state.
        @param login_mode: login mode, only supported for linux instance, valid values are "keypair", "passwd".
        param login_passwd: if login_mode is "passwd", should be specified.
        @param login_keypair: if login_mode is "keypair", should be specified.
        @param instances : an array of instance ids you want to reset.
        @param need_newsid: Whether to generate new SID for the instance (True) or not
                            (False). Only valid for Windows instance; Silently ignored
                            for Linux instance.
        """
        action = const.ACTION_RESET_INSTANCES
        valid_keys = ['instances', 'login_mode',
                      'login_passwd', 'login_keypair', 'need_newsid']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['instances'],
                                             integer_params=['need_newsid'],
                                             list_params=['instances']
                                             ):
            return None

        return self.send_request(action, body)

    def resize_instances(self, instances,
                         instance_type=None,
                         cpu=None,
                         memory=None,
                         **ignore):
        """ Resize one or more instances
        @param instances: the IDs of the instances you want to resize.
        @param instance_type: defined by qingcloud.
                              See: https://docs.qingcloud.com/api/common/includes/instance_type.html
        @param cpu: cpu core number.
        @param memory: memory size in MB.
        """
        action = const.ACTION_RESIZE_INSTANCES
        valid_keys = ['instances', 'instance_type', 'cpu', 'memory']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['instances'],
                                             integer_params=['cpu', 'memory'],
                                             list_params=['instances']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_instance_attributes(self, instance,
                                   instance_name=None,
                                   description=None,
                                   nic_mqueue=None,
                                   **ignore):
        """ Modify instance attributes.
        @param instance:  the ID of instance whose attributes you want to modify.
        @param instance_name: Name of the instance. It's a short name for the instance
                              that more meaningful than instance id.
        @param nic_mqueue: Enable or disable multiqueue.
        @param description: The detailed description of the resource.
        """
        action = const.ACTION_MODIFY_INSTANCE_ATTRIBUTES
        valid_keys = ['instance', 'instance_name', 'description', 'nic_mqueue']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['instance'],
                                             integer_params=['nic_mqueue'],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def upload_userdata(self, attachment_content,
                        attachment_name=None,
                        **ignore):
        """ Action:UploadUserDataAttachment
        @param attachment_content: base64 encoded string
        @param attachment_name: file name
        """
        action = const.ACTION_UPLOAD_USERDATA_ATTACHMENT
        valid_keys = ['attachment_content', 'attachment_name']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'attachment_content'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body, verb='POST')

    def describe_volumes(self, volumes=None,
                         volume_type=None,
                         instance_id=None,
                         status=None,
                         owner=None,
                         search_word=None,
                         verbose=0,
                         offset=None,
                         limit=None,
                         tags=None,
                         **ignore):
        """ Describe volumes filtered by conditions
        @param volumes : the array of IDs of volumes.
        @param volume_type : the type of volume, 0 is high performance, 1 is high capacity
        @param instance_id: ID of the instance that volume is currently attached to, if has.
        @param status: pending, available, in-use, deleted.
        @param search_word: the combined search column.
        @param verbose: the number to specify the verbose level, larger the number, the more detailed information will be returned.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        @param tags : the array of IDs of tags.
        """
        valid_keys = ['volumes', 'instance_id', 'status', 'search_word',
                      'volume_type', 'verbose', 'offset', 'limit', 'tags', 'owner']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'offset', 'limit', 'verbose'],
                                             list_params=[
                                                 'volumes', 'status', 'tags']
                                             ):
            return None
        return self.send_request(const.ACTION_DESCRIBE_VOLUMES, body)

    def create_volumes(self, size,
                       volume_name="",
                       volume_type=0,
                       count=1,
                       target_user=None,
                       **ignore):
        """ Create one or more volumes.
        @param size : the size of each volume. Unit is GB.
        @param volume_name : the short name of volume
        @param volume_type : the type of volume, 0 is high performance, 1 is high capacity
        @param count : the number of volumes to create.
        @param target_user: ID of user who will own this resource, should be one of your sub-accounts
        """
        action = const.ACTION_CREATE_VOLUMES
        valid_keys = ['size', 'volume_name', 'volume_type', 'count', 'target_user']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['size'],
                                             integer_params=['size', 'count'],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def delete_volumes(self, volumes,
                       **ignore):
        """ Delete one or more volumes.
        @param volumes : An array including IDs of the volumes you want to delete.
        """
        action = const.ACTION_DELETE_VOLUMES
        body = {'volumes': volumes}
        if not self.req_checker.check_params(body,
                                             required_params=['volumes'],
                                             integer_params=[],
                                             list_params=['volumes']
                                             ):
            return None

        return self.send_request(action, body)

    def attach_volumes(self, volumes,
                       instance,
                       **ignore):
        """ Attach one or more volumes to same instance
        @param volumes : an array including IDs of the volumes you want to attach.
        @param instance : the ID of instance the volumes will be attached to.
        """
        action = const.ACTION_ATTACH_VOLUMES
        valid_keys = ['volumes', 'instance']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'volumes', 'instance'],
                                             integer_params=[],
                                             list_params=['volumes']
                                             ):
            return None

        return self.send_request(action, body)

    def detach_volumes(self, volumes,
                       instance,
                       **ignore):
        """ Detach one or more volumes from same instance.
        @param volumes : An array including IDs of the volumes you want to attach.
        @param instance : the ID of instance the volumes will be detached from.
        """

        action = const.ACTION_DETACH_VOLUMES
        valid_keys = ['volumes', 'instance']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'volumes', 'instance'],
                                             integer_params=[],
                                             list_params=['volumes']
                                             ):
            return None

        return self.send_request(action, body)

    def resize_volumes(self, volumes,
                       size,
                       **ignore):
        """ Extend one or more volumes' size.
        @param volumes: The IDs of the volumes you want to resize.
        @param size : The new larger size of the volumes, unit is GB
        """
        action = const.ACTION_RESIZE_VOLUMES
        valid_keys = ['volumes', 'size']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'volumes', 'size'],
                                             integer_params=['size'],
                                             list_params=['volumes']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_volume_attributes(self, volume,
                                 volume_name=None,
                                 description=None,
                                 **ignore):
        """ Modify volume attributes.
        @param volume:  the ID of volume whose attributes you want to modify.
        @param volume_name: Name of the volume. It's a short name for
                            the volume that more meaningful than volume id.
        @param description: The detailed description of the resource.
        """
        action = const.ACTION_MODIFY_VOLUME_ATTRIBUTES
        valid_keys = ['volume', 'volume_name', 'description']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['volume'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def describe_key_pairs(self, keypairs=None,
                           encrypt_method=None,
                           search_word=None,
                           owner=None,
                           verbose=0,
                           offset=None,
                           limit=None,
                           tags=None,
                           **ignore):
        """ Describe key-pairs filtered by condition
        @param keypairs: IDs of the keypairs you want to describe.
        @param encrypt_method: encrypt method.
        @param verbose: the number to specify the verbose level, larger the number, the more detailed information will be returned.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        @param tags : the array of IDs of tags.
        """
        action = const.ACTION_DESCRIBE_KEY_PAIRS
        valid_keys = ['keypairs', 'encrypt_method', 'search_word', 'verbose',
                      'offset', 'limit', 'tags', 'owner']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'offset', 'limit', 'verbose'],
                                             list_params=['keypairs', 'tags']
                                             ):
            return None

        return self.send_request(action, body)

    def attach_keypairs(self, keypairs,
                        instances,
                        **ignore):
        """ Attach one or more keypairs to instances.
        @param keypairs: IDs of the keypairs you want to attach to instance .
        @param instances: IDs of the instances the keypairs will be attached to.
        """
        action = const.ACTION_ATTACH_KEY_PAIRS
        valid_keys = ['keypairs', 'instances']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'keypairs', 'instances'],
                                             integer_params=[],
                                             list_params=[
                                                 'keypairs', 'instances']
                                             ):
            return None

        return self.send_request(action, body)

    def detach_keypairs(self, keypairs,
                        instances,
                        **ignore):
        """ Detach one or more keypairs from instances.
        @param keypairs: IDs of the keypairs you want to detach from instance .
        @param instances: IDs of the instances the keypairs will be detached from.
        """
        action = const.ACTION_DETACH_KEY_PAIRS
        valid_keys = ['keypairs', 'instances']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 "keypairs", "instances"],
                                             integer_params=[],
                                             list_params=[
                                                 "keypairs", "instances"]
                                             ):
            return None

        return self.send_request(action, body)

    def create_keypair(self, keypair_name,
                       mode='system',
                       encrypt_method="ssh-rsa",
                       public_key=None,
                       target_user=None,
                       **ignore):
        """ Create a keypair.
        @param keypair_name: the name of the keypair you want to create.
        @param mode: the keypair creation mode, "system" or "user".
        @param encrypt_method: the encrypt method, supported methods "ssh-rsa", "ssh-dss".
        @param public_key: provide your public key. (need "user" mode)
        @param target_user: ID of user who will own this resource, should be one of your sub-accounts
        """
        action = const.ACTION_CREATE_KEY_PAIR
        valid_keys = ['keypair_name', 'mode', 'encrypt_method', 'public_key', 'target_user']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['keypair_name'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def delete_keypairs(self, keypairs,
                        **ignore):
        """ Delete one or more keypairs.
        @param keypairs: IDs of the keypairs you want to delete.
        """
        action = const.ACTION_DELETE_KEY_PAIRS
        body = {'keypairs': keypairs}
        if not self.req_checker.check_params(body,
                                             required_params=['keypairs'],
                                             integer_params=[],
                                             list_params=['keypairs']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_keypair_attributes(self, keypair,
                                  keypair_name=None,
                                  description=None,
                                  **ignore):
        """ Modify keypair attributes.
        @param keypair: the ID of keypair you want to modify its attributes.
        @param keypair_name: the new name of keypair.
        @param description: The detailed description of the resource.
        """
        action = const.ACTION_MODIFY_KEYPAIR_ATTRIBUTES
        valid_keys = ['keypair', 'keypair_name', 'description']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['keypair'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def describe_security_groups(self, security_groups=None,
                                 security_group_name=None,
                                 search_word=None,
                                 owner=None,
                                 verbose=0,
                                 offset=None,
                                 limit=None,
                                 tags=None,
                                 **ignore):
        """ Describe security groups filtered by condition
        @param security_groups: IDs of the security groups you want to describe.
        @param security_group_name: the name of the security group.
        @param verbose: the number to specify the verbose level, larger the number, the more detailed information will be returned.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        @param tags : the array of IDs of tags.
        """
        action = const.ACTION_DESCRIBE_SECURITY_GROUPS
        valid_keys = ['security_groups', 'security_group_name', 'search_word',
                      'verbose', 'offset', 'limit', 'tags', 'owner']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'offset', 'limit', 'verbose'],
                                             list_params=[
                                                 'security_groups', 'tags']
                                             ):
            return None

        return self.send_request(action, body)

    def create_security_group(self, security_group_name, target_user=None,
                              **ignore):
        """ Create a new security group without any rule.
        @param security_group_name: the name of the security group you want to create.
        @param target_user: ID of user who will own this resource, should be one of your sub-accounts
        """
        action = const.ACTION_CREATE_SECURITY_GROUP
        body = {'security_group_name': security_group_name}
        if target_user:
            body['target_user'] = target_user
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'security_group_name'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def modify_security_group_attributes(self, security_group,
                                         security_group_name=None,
                                         description=None,
                                         **ignore):
        """ Modify security group attributes.
        @param security_group: the ID of the security group whose content you
                               want to update.
        @param security_group_name: the new group name you want to update.
        @param description: The detailed description of the resource.
        """
        action = const.ACTION_MODIFY_SECURITY_GROUP_ATTRIBUTES
        valid_keys = ['security_group', 'security_group_name', 'description']
        body = filter_out_none(locals(), valid_keys)
        body['security_group'] = security_group
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'security_group'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        if not self.req_checker.check_sg_rules(body.get('rules', [])):
            return None

        return self.send_request(action, body)

    def apply_security_group(self, security_group,
                             instances=None,
                             target_user=None,
                             **ignore):
        """ Apply a security group with current rules.
            If `instances` specified, apply the security group to them,
            or will affect all instances that has applied this security group.
        @param security_group: the ID of the security group that you
                               want to apply to instances.
        @param instances: the IDs of the instances you want to apply the security group.
        @param target_user: ID of user who will own this resource, should be one of your sub-accounts
        """
        action = const.ACTION_APPLY_SECURITY_GROUP
        valid_keys = ['security_group', 'instances', 'target_user']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'security_group'],
                                             integer_params=[],
                                             list_params=['instances']
                                             ):
            return None
        return self.send_request(action, body)

    def remove_security_group(self,
                             instances,
                             **ignore):
        """ Remove security group from instances.
        @param instances: the IDs of the instances you want to remove the security group.
        """
        action = const.ACTION_REMOVE_SECURITY_GROUP
        valid_keys = ['instances']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'instances'],
                                             integer_params=[],
                                             list_params=['instances']
                                             ):
            return None
        return self.send_request(action, body)

    def delete_security_groups(self, security_groups,
                               **ignore):
        """ Delete one or more security groups.
        @param security_groups: the IDs of the security groups you want to delete.
        """
        action = const.ACTION_DELETE_SECURITY_GROUPS
        body = {'security_groups': security_groups}
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'security_groups'],
                                             integer_params=[],
                                             list_params=['security_groups']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_security_group_rules(self, security_group=None,
                                      security_group_rules=None,
                                      direction=None,
                                      offset=None,
                                      limit=None,
                                      **ignore):
        """ Describe security group rules filtered by condition.
        @param security_group: the ID of the security group whose rules you want to describe.
        @param security_group_rules: the IDs of the security group rules you want to describe.
        @param direction: 0 for inbound; 1 for outbound
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_SECURITY_GROUP_RULES
        valid_keys = ['security_group', 'security_group_rules', 'direction',
                      'offset', 'limit']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'direction', 'offset', 'limit'],
                                             list_params=[
                                                 'security_group_rules']
                                             ):
            return None

        return self.send_request(action, body)

    def add_security_group_rules(self, security_group,
                                 rules,
                                 target_user=None,
                                 **ignore):
        """ Add rules to security group.
        @param security_group: the ID of the security group whose rules you
                               want to add.
        @param rules: a list of rules you want to add,
                      can be created by SecurityGroupRuleFactory.
        @param target_user: ID of user who will own this resource, should be one of your sub-accounts
        """
        action = const.ACTION_ADD_SECURITY_GROUP_RULES
        valid_keys = ['security_group', 'rules', 'target_user']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'security_group', 'rules'],
                                             integer_params=[],
                                             list_params=['rules']
                                             ):
            return None

        if not self.req_checker.check_sg_rules(body.get('rules', [])):
            return None

        return self.send_request(action, body)

    def delete_security_group_rules(self, security_group_rules,
                                    **ignore):
        """ Delete one or more security group rules.
        @param security_group_rules: the IDs of rules you want to delete.
        """
        action = const.ACTION_DELETE_SECURITY_GROUP_RULES
        body = {'security_group_rules': security_group_rules}
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'security_group_rules'],
                                             integer_params=[],
                                             list_params=[
                                                 'security_group_rules']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_security_group_rule_attributes(self, security_group_rule,
                                              priority=None,
                                              security_group_rule_name=None,
                                              rule_action=None,
                                              direction=None,
                                              protocol=None,
                                              val1=None,
                                              val2=None,
                                              val3=None,
                                              **ignore):
        """ Modify security group rule attributes.
        @param security_group_rule: the ID of the security group rule whose attributes you
                                    want to update.
        @param priority: priority [0 - 100].
        @param security_group_rule_name: name of the rule.
        @param rule_action: "accept" or "drop".
        @param direction: 0 for inbound; 1 for outbound.
        @param protocol: supported protocols are "icmp", "tcp", "udp", "gre".
        @param val1: for "icmp" protocol, this field is "icmp type";
                     for "tcp/udp", it's "start port", empty means all.
        @param val2: for "icmp" protocol, this field is "icmp code";
                     for "tcp/udp", it's "end port", empty means all.
        @param val3: ip network, e.g "1.2.3.0/24"
        """
        action = const.ACTION_MODIFY_SECURITY_GROUP_RULE_ATTRIBUTES
        valid_keys = ['security_group_rule', 'priority', 'security_group_rule_name',
                      'rule_action', 'direction', 'protocol', 'val1', 'val2', 'val3']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'security_group_rule'],
                                             integer_params=['priority'],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def describe_security_group_ipsets(self,
                                       security_group_ipsets=None,
                                       ipset_type=None,
                                       security_group_ipset_name=None,
                                       offset=None,
                                       limit=None,
                                       **ignore):
        """ Describe security group ipsets filtered by condition.
        @param security_group_ipsets: the ID of the security group ipsets.
        @param ipset_type: 0 for ip; 1 for port
        @param security_group_ipset_name: filter by name
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_SECURITY_GROUP_IPSETS
        valid_keys = ['security_group_ipsets', 'ipset_type',
                      'security_group_ipset_name',
                      'offset', 'limit']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'ipset_type', 'offset', 'limit'],
                                             list_params=[
                                                 'security_group_rules']
                                             ):
            return None

        return self.send_request(action, body)

    def create_security_group_ipset(self,
                                    ipset_type, val,
                                    security_group_ipset_name=None,
                                    target_user=None,
                                    **ignore):
        """ Create security group ipset.
        @param ipset_type: 0 for ip; 1 for port
        @param val: such as 192.168.1.0/24 or 10000-15000
        @param security_group_ipset_name: the name of the security group ipsets
        @param target_user: ID of user who will own this resource, should be one of your sub-accounts
        """
        action = const.ACTION_CREATE_SECURITY_GROUP_IPSET
        valid_keys = ['security_group_ipset_name', 'ipset_type', 'val', 'target_user']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'ipset_type', 'val'],
                                             integer_params=['ipset_type'],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def delete_security_group_ipsets(self,
                                     security_group_ipsets,
                                     **ignore):
        """ Delete one or more security group ipsets.
        @param security_group_ipsets: the IDs of ipsets you want to delete.
        """
        action = const.ACTION_DELETE_SECURITY_GROUP_IPSETS
        body = {'security_group_ipsets': security_group_ipsets}
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'security_group_ipsets'],
                                             integer_params=[],
                                             list_params=[
                                                 'security_group_ipsets']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_security_group_ipset_attributes(self,
                                               security_group_ipset,
                                               security_group_ipset_name=None,
                                               description=None,
                                               val=None,
                                               **ignore):
        """ Modify security group ipset attributes.
        @param security_group_ipset: the ID of the security group ipset whose attributes you
                                    want to update.
        @param security_group_ipset_name: name of the ipset.
        @param description: The detailed description of the resource.
        @param val1: for "ip", this field is like:  192.168.1.0/24
                     for "port", this field is like: 10000-15000
        """
        action = const.ACTION_MODIFY_SECURITY_GROUP_IPSET_ATTRIBUTES
        valid_keys = ['security_group_ipset', 'security_group_ipset_name',
                      'description', 'val']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'security_group_ipset'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def describe_vxnets(self, vxnets=None,
                        search_word=None,
                        verbose=0,
                        owner=None,
                        limit=None,
                        offset=None,
                        tags=None,
                        vxnet_type=None,
                        mode=None,
                        **ignore):
        """ Describe vxnets filtered by condition.
        @param vxnets: the IDs of vxnets you want to describe.
        @param verbose: the number to specify the verbose level, larger the number, the more detailed information will be returned.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        @param tags : the array of IDs of tags.
        @param vxnet_type: the vxnet of type you want to describe.
        @param mode: the vxnet mode. 0: gre+ovs, 1: vxlan+bridge.
        """
        action = const.ACTION_DESCRIBE_VXNETS
        valid_keys = ['vxnets', 'search_word', 'verbose', 'limit', 'offset',
                      'tags', 'vxnet_type', 'owner', 'mode']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'limit', 'offset', 'verbose',
                                                 'vxnet_type', 'mode',
                                             ],
                                             list_params=['vxnets', 'tags']
                                             ):
            return None

        return self.send_request(action, body)

    def create_vxnets(self, vxnet_name=None,
                      vxnet_type=const.VXNET_TYPE_MANAGED,
                      count=1,
                      mode=0,
                      **ignore):
        """ Create one or more vxnets.
        @param vxnet_name: the name of vxnet you want to create.
        @param vxnet_type: vxnet type: unmanaged or managed.
        @param count : the number of vxnet you want to create.
        @param mode: the vxnet mode. 0: gre+ovs, 1: vxlan+bridge.
        """
        action = const.ACTION_CREATE_VXNETS
        valid_keys = ['vxnet_name', 'vxnet_type', 'count', 'mode']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['vxnet_type'],
                                             integer_params=[
                                                 'vxnet_type', 'count', 'mode',
                                             ],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def join_vxnet(self, vxnet,
                   instances,
                   **ignore):
        """ One or more instances join the vxnet.
        @param vxnet : the id of vxnet you want the instances to join.
        @param instances : the IDs of instances that will join vxnet.
        """

        action = const.ACTION_JOIN_VXNET
        valid_keys = ['vxnet', 'instances']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'vxnet', 'instances'],
                                             integer_params=[],
                                             list_params=['instances']
                                             ):
            return None

        return self.send_request(action, body)

    def leave_vxnet(self, vxnet,
                    instances,
                    **ignore):
        """ One or more instances leave the vxnet.
        @param vxnet : The id of vxnet that the instances will leave.
        @param instances : the IDs of instances that will leave vxnet.
        """
        action = const.ACTION_LEAVE_VXNET
        valid_keys = ['vxnet', 'instances']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'vxnet', 'instances'],
                                             integer_params=[],
                                             list_params=['instances']
                                             ):
            return None

        return self.send_request(action, body)

    def delete_vxnets(self, vxnets,
                      **ignore):
        """ Delete one or more vxnets.
        @param vxnets: the IDs of vxnets you want to delete.
        """
        action = const.ACTION_DELETE_VXNETS
        body = {'vxnets': vxnets}
        if not self.req_checker.check_params(body,
                                             required_params=['vxnets'],
                                             integer_params=[],
                                             list_params=['vxnets']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_vxnet_attributes(self, vxnet,
                                vxnet_name=None,
                                description=None,
                                **ignore):
        """ Modify vxnet attributes
        @param vxnet: the ID of vxnet you want to modify its attributes.
        @param vxnet_name: the new name of vxnet.
        @param description: The detailed description of the resource.
        """
        action = const.ACTION_MODIFY_VXNET_ATTRIBUTES
        valid_keys = ['vxnet', 'vxnet_name', 'description']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['vxnet'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def describe_vxnet_instances(self, vxnet,
                                 instances=None,
                                 image=None,
                                 instance_type=None,
                                 status=None,
                                 limit=None,
                                 offset=None,
                                 **ignore):
        """ Describe instances in vxnet.
        @param vxnet: the ID of vxnet whose instances you want to describe.
        @param image: filter by image ID.
        @param instances: filter by instance ID.
        @param instance_type: filter by instance type
                              See: https://docs.qingcloud.com/api/common/includes/instance_type.html
        @param status: filter by status
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_VXNET_INSTANCES
        valid_keys = ['vxnet', 'instances', 'image', 'instance_type', 'status',
                      'limit', 'offset']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['vxnet'],
                                             integer_params=[
                                                 'limit', 'offset'],
                                             list_params=['instances']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_routers(self, routers=None,
                         vxnet=None,
                         status=None,
                         verbose=0,
                         owner=None,
                         search_word=None,
                         limit=None,
                         offset=None,
                         tags=None,
                         **ignore):
        """ Describe routers filtered by condition.
        @param routers: the IDs of the routers you want to describe.
        @param vxnet: the ID of vxnet you want to describe.
        @param verbose: the number to specify the verbose level, larger the number, the more detailed information will be returned.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        @param tags : the array of IDs of tags.
        """
        action = const.ACTION_DESCRIBE_ROUTERS
        valid_keys = ['routers', 'vxnet', 'status', 'verbose', 'search_word',
                      'limit', 'offset', 'tags', 'owner']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'limit', 'offset', 'verbose'],
                                             list_params=['routers', 'tags']
                                             ):
            return None

        return self.send_request(action, body)

    def create_routers(self, count=1,
                       router_name=None,
                       security_group=None,
                       vpc_network=None,
                       router_type=None,
                       **ignore):
        """ Create one or more routers.
        @param router_name: the name of the router.
        @param security_group: the ID of the security_group you want to apply to router.
        @param count: the count of router you want to create.
        @param vpc_network: VPC IP addresses range, currently support "192.168.0.0/16" or "172.16.0.0/16", required in zone pek3a.
        @param router_type: 0 - Medium, 1 - Small, 2 - large, 3 - extra-large (default is 1).
        """
        action = const.ACTION_CREATE_ROUTERS
        valid_keys = ['count', 'router_name', 'security_group', 'vpc_network', 'router_type']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=['count'],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def delete_routers(self, routers,
                       **ignore):
        """ Delete one or more routers.
        @param routers: the IDs of routers you want to delete.
        """
        action = const.ACTION_DELETE_ROUTERS
        body = {'routers': routers}
        if not self.req_checker.check_params(body,
                                             required_params=['routers'],
                                             integer_params=[],
                                             list_params=['routers']
                                             ):
            return None

        return self.send_request(action, body)

    def update_routers(self, routers,
                       **ignore):
        """ Update one or more routers.
        @param routers: the IDs of routers you want to update.
        """
        action = const.ACTION_UPDATE_ROUTERS
        body = {'routers': routers}
        if not self.req_checker.check_params(body,
                                             required_params=['routers'],
                                             integer_params=[],
                                             list_params=['routers']
                                             ):
            return None

        return self.send_request(action, body)

    def poweroff_routers(self, routers,
                         **ignore):
        """ Poweroff one or more routers.
        @param routers: the IDs of routers you want to poweroff.
        """
        action = const.ACTION_POWEROFF_ROUTERS
        body = {'routers': routers}
        if not self.req_checker.check_params(body,
                                             required_params=['routers'],
                                             integer_params=[],
                                             list_params=['routers']
                                             ):
            return None

        return self.send_request(action, body)

    def poweron_routers(self, routers,
                        **ignore):
        """ Poweron one or more routers.
        @param routers: the IDs of routers you want to poweron.
        """
        action = const.ACTION_POWERON_ROUTERS
        body = {'routers': routers}
        if not self.req_checker.check_params(body,
                                             required_params=['routers'],
                                             integer_params=[],
                                             list_params=['routers']
                                             ):
            return None

        return self.send_request(action, body)

    def join_router(self, vxnet,
                    router,
                    ip_network,
                    manager_ip=None,
                    dyn_ip_start=None,
                    dyn_ip_end=None,
                    features=1,
                    **ignore):
        """ Connect vxnet to router.
        @param vxnet: the ID of vxnet that will join the router.
        @param router: the ID of the router the vxnet will join.
        @param ip_network: the ip network in CSI format.
        @param manager_ip: can be provided if DHCP feature is enabled.
        @param dyn_ip_start: starting IP that allocated from DHCP server.
        @param dyn_ip_end: ending IP that allocated from DHCP server.
        @param features: the feature the vxnet will enable in the router.
                         1 - dhcp server.
        """
        action = const.ACTION_JOIN_ROUTER
        valid_keys = ['vxnet', 'router', 'ip_network', 'manager_ip',
                      'dyn_ip_start', 'dyn_ip_end', 'features']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'vxnet', 'router', 'ip_network'],
                                             integer_params=['features'],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def leave_router(self, router,
                     vxnets,
                     **ignore):
        """ Disconnect vxnets from router.
        @param vxnets: the IDs of vxnets that will leave the router.
        @param router: the ID of the router the vxnet will leave.
        """
        action = const.ACTION_LEAVE_ROUTER
        valid_keys = ['router', 'vxnets']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'vxnets', 'router'],
                                             integer_params=[],
                                             list_params=['vxnets']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_router_attributes(self, router,
                                 vxnet=None,
                                 eip=None,
                                 security_group=None,
                                 router_name=None,
                                 description=None,
                                 features=None,
                                 dyn_ip_start=None,
                                 dyn_ip_end=None,
                                 **ignore):
        """ Modify router attributes.
        @param router: the ID of router you want to modify its attributes.
        @param vxnet: the ID of vxnet whose feature you want to modify.
        @param eip: the eip.
        @param security_group: the ID of the security_group you want to apply to router.
        @param router_name: the name of the router.
        @param description: the description of the router.
        @param features: the features of vxnet you want to re-define. 1: enable DHCP; 0: disable DHCP
        @param dyn_ip_start: starting IP that allocated from DHCP server
        @param dyn_ip_end: ending IP that allocated from DHCP server
        """
        action = const.ACTION_MODIFY_ROUTER_ATTRIBUTES
        valid_keys = ['router', 'vxnet', 'eip', 'security_group', 'features',
                      'router_name', 'description', 'dyn_ip_start', 'dyn_ip_end']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['router'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def describe_router_vxnets(self, router=None,
                               vxnet=None,
                               limit=None,
                               offset=None,
                               **ignore):
        """ Describe vxnets in router.
        @param router: filter by router ID.
        @param vxnet: filter by vxnet ID.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_ROUTER_VXNETS
        valid_keys = ['router', 'vxnet', 'limit', 'offset']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'limit', 'offset'],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def modify_router_static_attributes(self, router_static,
                                        router_static_name=None,
                                        val1=None,
                                        val2=None,
                                        val3=None,
                                        val4=None,
                                        val5=None,
                                        val6=None,
                                        disabled=None,
                                        **ignore):
        """ Modify router static attributes.
        @param router_static: the ID of router static you want to modify its attributes.
        @param val1 - val6: please see the doc. https://docs.qingcloud.com/api/router/modify_router_static_attributes.html
        @param disabled: disable the static when this is 1, or 0 to enable it.
        """
        action = const.ACTION_MODIFY_ROUTER_STATIC_ATTRIBUTES
        valid_keys = ['router_static', 'router_static_name', 'disabled',
                      'val1', 'val2', 'val3', 'val4', 'val5', 'val6']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['router_static'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def describe_router_statics(self, router_statics=None,
                                router=None,
                                vxnet=None,
                                static_type=None,
                                limit=None,
                                offset=None,
                                **ignore):
        """ Describe router statics filtered by condition.
        @param router_statics: the IDs of the router statics you want to describe.
        @param router: filter by router ID.
        @param vxnet: filter by vxnet ID.
        @param static_type: defined in `RouterStaticFactory`.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_ROUTER_STATICS
        valid_keys = ['router_statics', 'router', 'vxnet', 'static_type',
                      'limit', 'offset']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'limit', 'offset', 'static_type'],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def add_router_statics(self, router,
                           statics,
                           **ignore):
        """ Add statics to router.
        @param router: the ID of the router whose statics you want to add.
        @param statics: a list of statics you want to add,
                        can be created by RouterStaticFactory.
        """
        action = const.ACTION_ADD_ROUTER_STATICS
        valid_keys = ['router', 'statics']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'router', 'statics'],
                                             integer_params=[],
                                             list_params=['statics']
                                             ):
            return None

        if not self.req_checker.check_router_statics(body.get('statics', [])):
            return None

        return self.send_request(action, body)

    def delete_router_statics(self, router_statics,
                              **ignore):
        """ Delete one or more router statics.
        @param router_statics: the IDs of router statics you want to delete.
        """
        action = const.ACTION_DELETE_ROUTER_STATICS
        body = {'router_statics': router_statics}
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'router_statics'],
                                             integer_params=[],
                                             list_params=['router_statics']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_router_static_entry_attributes(self,
                                              router_static_entry,
                                              router_static_entry_name=None,
                                              val1=None,
                                              val2=None,
                                              **ignore):
        """ Modify router static entry attributes.
        @param router_static_entry: the ID of router static entry you want to modify.
        @param router_static_entry_name: the new name of router static entry.
        @param val1 - val2: please see the doc. https://docs.qingcloud.com/api/router/modify_router_static_entry_attributes.html
        """
        action = const.ACTION_MODIFY_ROUTER_STATIC_ENTRY_ATTRIBUTES
        valid_keys = ['router_static_entry', 'router_static_entry_name',
                      'val1', 'val2']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'router_static_entry'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def describe_router_static_entries(self,
                                       router_static_entries=None,
                                       router_static=None,
                                       limit=None,
                                       offset=None,
                                       **ignore):
        """ Describe router static entries filtered by condition.
        @param router_static_entries: the IDs of the router static entries you want to describe.
        @param router_static: filter by router static ID.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_ROUTER_STATIC_ENTRIES
        valid_keys = ['router_static_entries', 'router_static',
                      'limit', 'offset']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'limit', 'offset'],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def add_router_static_entries(self,
                                  router_static,
                                  entries,
                                  **ignore):
        """ Add entries to router static.
        @param router_static: the ID of the router static you want to add.
        @param entries: a list of entries you want to add.
        """
        action = const.ACTION_ADD_ROUTER_STATIC_ENTRIES
        valid_keys = ['router_static', 'entries']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'router_static', 'entries'],
                                             integer_params=[],
                                             list_params=['entries']
                                             ):
            return None

        return self.send_request(action, body)

    def delete_router_static_entries(self,
                                     router_static_entries,
                                     **ignore):
        """ Delete one or more router static entries.
        @param router_static_entries: the IDs of router static entries you want to delete.
        """
        action = const.ACTION_DELETE_ROUTER_STATIC_ENTRIES
        body = {'router_static_entries': router_static_entries}
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'router_static_entries'],
                                             integer_params=[],
                                             list_params=[
                                                 'router_static_entries']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_eips(self, eips=None,
                      status=None,
                      instance_id=None,
                      search_word=None,
                      owner=None,
                      offset=None,
                      limit=None,
                      tags=None,
                      **ignore):
        """ Describe eips filtered by condition.
        @param eips: IDs of the eip you want describe.
        @param status: filter eips by status
        @param instance_id: filter eips by instance.
        @param search_word: search word column.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        @param tags : the array of IDs of tags.
        """
        action = const.ACTION_DESCRIBE_EIPS
        valid_keys = ['eips', 'status', 'instance_id', 'search_word',
                      'offset', 'limit', 'tags', 'owner']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'offset', 'limit'],
                                             list_params=[
                                                 'status', 'eips', 'tags']
                                             ):
            return None

        return self.send_request(action, body)

    def associate_eip(self, eip,
                      instance,
                      **ignore):
        """ Associate an eip on an instance.
        @param eip: The id of eip you want to associate with instance.
        @param instance: the id of instance you want to associate eip.
        """
        action = const.ACTION_ASSOCIATE_EIP
        body = {'eip': eip, 'instance': instance}
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'eip', 'instance'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def dissociate_eips(self, eips,
                        **ignore):
        """ Dissociate one or more eips.
        @param eips: The ids of eips you want to dissociate with instance.
        """
        action = const.ACTION_DISSOCIATE_EIPS
        body = {'eips': eips}
        if not self.req_checker.check_params(body,
                                             required_params=['eips'],
                                             integer_params=[],
                                             list_params=['eips']
                                             ):
            return None

        return self.send_request(action, body)

    def allocate_eips(self, bandwidth,
                      billing_mode=const.EIP_BILLING_MODE_BANDWIDTH,
                      count=1,
                      need_icp=0,
                      eip_name='',
                      target_user=None,
                      associate_mode=0,
                      **ignore):
        """ Allocate one or more eips.
        @param count: the number of eips you want to allocate.
        @param bandwidth: the bandwidth of the eip in Mbps.
        @param need_icp: 0 - no need, 1 - need
        @param eip_name : the short name of eip
        @param target_user: ID of user who will own this resource, should be one of your sub-accounts
        @param associate_mode: 0 - associate ip addr to virtual gateway, 1 - associate ip addr to vm
        """
        action = const.ACTION_ALLOCATE_EIPS
        valid_keys = ['bandwidth', 'billing_mode',
                      'count', 'need_icp', 'eip_name',
                      'target_user', 'associate_mode']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['bandwidth'],
                                             integer_params=['bandwidth', 'count',
                                                             'need_icp', 'associate_mode'],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def release_eips(self, eips,
                     force=0,
                     **ignore):
        """ Release one or more eips.
        @param eips : The ids of eips that you want to release
        @param force : Whether to force release the eip that needs icp codes.
        """
        action = const.ACTION_RELEASE_EIPS
        body = {'eips': eips, 'force': int(force != 0)}
        if not self.req_checker.check_params(body,
                                             required_params=['eips'],
                                             integer_params=['force'],
                                             list_params=['eips']
                                             ):
            return None

        return self.send_request(action, body)

    def change_eips_bandwidth(self, eips,
                              bandwidth,
                              **ignore):
        """ Change one or more eips bandwidth.
        @param eips: The IDs of the eips whose bandwidth you want to change.
        @param bandwidth: the new bandwidth of the eip in MB.
        """
        action = const.ACTION_CHANGE_EIPS_BANDWIDTH
        body = {'eips': eips, 'bandwidth': bandwidth}
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'eips', 'bandwidth'],
                                             integer_params=['bandwidth'],
                                             list_params=['eips']
                                             ):
            return None

        return self.send_request(action, body)

    def change_eips_billing_mode(self, eips,
                                 billing_mode,
                                 **ignore):
        """ Change one or more eips billing mode.
        @param eips: The IDs of the eips whose billing mode you want to change.
        @param billing_mode: the new billing mode, "bandwidth" or "traffic".
        """
        action = const.ACTION_CHANGE_EIPS_BILLING_MODE
        body = {'eips': eips, 'billing_mode': billing_mode}
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'eips', 'billing_mode'],
                                             list_params=['eips']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_eip_attributes(self, eip,
                              eip_name=None,
                              description=None,
                              **ignore):
        """ Modify eip attributes.
            If you want to modify eip's bandwidth, use `change_eips_bandwidth`.
        @param eip : the ID of eip that you want to modify
        @param eip_name : the name of eip
        @param description : the eip description
        """
        action = const.ACTION_MODIFY_EIP_ATTRIBUTES
        valid_keys = ['eip', 'eip_name', 'description']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['eip'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def describe_loadbalancers(self, loadbalancers=None,
                               status=None,
                               verbose=0,
                               owner=None,
                               search_word=None,
                               offset=None,
                               limit=None,
                               tags=None,
                               **ignore):
        """ Describe loadbalancers filtered by condition.
        @param loadbalancers : the array of load balancer IDs.
        @param status: pending, active, stopped, deleted, suspended, ceased
        @param verbose: the number to specify the verbose level, larger the number, the more detailed information will be returned.
        @param search_word: search word column.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        @param tags : the array of IDs of tags.
        """
        action = const.ACTION_DESCRIBE_LOADBALANCERS
        valid_keys = ['loadbalancers', 'status', 'verbose', 'search_word',
                      'offset', 'limit', 'tags', 'owner']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'offset', 'limit'],
                                             list_params=[
                                                 'loadbalancers', 'status', 'tags']
                                             ):
            return None

        return self.send_request(action, body)

    def create_loadbalancer(self,
                            eips=None,
                            loadbalancer_name=None,
                            security_group=None,
                            node_count=None,
                            loadbalancer_type=const.LB_TYPE_MAXCONN_5k,
                            vxnet=None,
                            private_ip=None,
                            target_user=None,
                            **ignore):
        """ Create new load balancer.
        @param eips: the IDs of the eips that will be associated to load balancer.
        @param loadbalancer_name: the name of the loadbalancer.
        @param security_group: the id of the security_group you want to apply to loadbalancer,
                               use `default security` group as default.
        @param target_user: ID of user who will own this resource, should be one of your sub-accounts
        """
        action = const.ACTION_CREATE_LOADBALANCER
        valid_keys = ['eips', 'loadbalancer_name', 'loadbalancer_type',
                      'security_group', 'node_count', 'vxnet', 'private_ip',
                      'target_user',
                      ]
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=['node_count'],
                                             list_params=['eips']
                                             ):
            return None

        return self.send_request(action, body)

    def delete_loadbalancers(self, loadbalancers,
                             **ignore):
        """ Delete one or more load balancers.
        @param loadbalancers: the IDs of load balancers you want to delete.
        """
        action = const.ACTION_DELETE_LOADBALANCERS
        body = {'loadbalancers': loadbalancers}
        if not self.req_checker.check_params(body,
                                             required_params=['loadbalancers'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def stop_loadbalancers(self, loadbalancers,
                           **ignore):
        """ Stop one or more load balancers.
        @param loadbalancers: the array of load balancer IDs.
        """
        action = const.ACTION_STOP_LOADBALANCERS
        body = {'loadbalancers': loadbalancers}
        if not self.req_checker.check_params(body,
                                             required_params=['loadbalancers'],
                                             integer_params=[],
                                             list_params=['loadbalancers']
                                             ):
            return None

        return self.send_request(action, body)

    def start_loadbalancers(self, loadbalancers,
                            **ignore):
        """ Start one or more load balancers.
        @param loadbalancers: the array of load balancer IDs.
        """
        action = const.ACTION_START_LOADBALANCERS
        body = {'loadbalancers': loadbalancers}
        if not self.req_checker.check_params(body,
                                             required_params=['loadbalancers'],
                                             integer_params=[],
                                             list_params=['loadbalancers']
                                             ):
            return None

        return self.send_request(action, body)

    def update_loadbalancers(self, loadbalancers, target_user=None,
                             **ignore):
        """ Update one or more load balancers.
        @param loadbalancers: the array of load balancer IDs.
        @param target_user: ID of user who will own this resource, should be one of your sub-accounts
        """
        action = const.ACTION_UPDATE_LOADBALANCERS
        body = {'loadbalancers': loadbalancers}
        if target_user:
            body['target_user'] = target_user
        if not self.req_checker.check_params(body,
                                             required_params=['loadbalancers'],
                                             integer_params=[],
                                             list_params=['loadbalancers']
                                             ):
            return None

        return self.send_request(action, body)

    def associate_eips_to_loadbalancer(self, loadbalancer,
                                       eips,
                                       **ignore):
        """ Associate one or more eips to load balancer.
        @param loadbalancer: the ID of load balancer.
        @param eips: the array of eip IDs.
        """
        action = const.ACTION_ASSOCIATE_EIPS_TO_LOADBALANCER
        body = {'loadbalancer': loadbalancer, 'eips': eips}
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'loadbalancer', 'eips'],
                                             integer_params=[],
                                             list_params=['eips']
                                             ):
            return None

        return self.send_request(action, body)

    def dissociate_eips_from_loadbalancer(self, loadbalancer,
                                          eips,
                                          **ignore):
        """ Dissociate one or more eips from load balancer.
        @param loadbalancer: the ID of load balancer.
        @param eips: the array of eip IDs.
        """
        action = const.ACTION_DISSOCIATE_EIPS_FROM_LOADBALANCER
        body = {'loadbalancer': loadbalancer, 'eips': eips}
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'loadbalancer', 'eips'],
                                             integer_params=[],
                                             list_params=['eips']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_loadbalancer_attributes(self, loadbalancer,
                                       security_group=None,
                                       loadbalancer_name=None,
                                       description=None,
                                       **ignore):
        """ Modify load balancer attributes.
        @param loadbalancer: the ID of loadbalancer you want to modify.
        @param security_group: the ID of the security_group.
        @param loadbalancer_name: the name of the loadbalancer.
        @param description: the description of the loadbalancer.
        """
        action = const.ACTION_MODIFY_LOADBALANCER_ATTRIBUTES
        valid_keys = ['loadbalancer', 'security_group', 'loadbalancer_name',
                      'description']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['loadbalancer'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def describe_loadbalancer_listeners(self, loadbalancer_listeners=None,
                                        loadbalancer=None,
                                        verbose=0,
                                        limit=None,
                                        offset=None,
                                        **ignore):
        """ Describe load balancer listeners by filter condition.
        @param loadbalancer_listeners: filter by load balancer listener IDs.
        @param loadbalancer: filter by loadbalancer ID.
        @param verbose: the number to specify the verbose level, larger the number, the more detailed information will be returned.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_LOADBALANCER_LISTENERS
        valid_keys = ['loadbalancer_listeners', 'loadbalancer', 'verbose',
                      'limit', 'offset']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'verbose', 'limit', 'offset'],
                                             list_params=[
                                                 'loadbalancer_listeners']
                                             ):
            return None

        return self.send_request(action, body)

    def add_listeners_to_loadbalancer(self, loadbalancer,
                                      listeners,
                                      target_user=None,
                                      **ignore):
        """ Add listeners to load balancer.
        @param loadbalancer: The ID of loadbalancer.
        @param listeners: the listeners to add.
        @param target_user: ID of user who will own this resource, should be one of your sub-accounts
        """
        action = const.ACTION_ADD_LOADBALANCER_LISTENERS
        valid_keys = ['listeners', 'loadbalancer', 'target_user']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'loadbalancer', 'listeners'],
                                             integer_params=[],
                                             list_params=['listeners']
                                             ):
            return None

        self.req_checker.check_lb_listeners(listeners)

        return self.send_request(action, body)

    def delete_loadbalancer_listeners(self, loadbalancer_listeners,
                                      **ignore):
        """ Delete load balancer listeners.
        @param loadbalancer_listeners: the array of listener IDs.
        """
        action = const.ACTION_DELETE_LOADBALANCER_LISTENERS
        body = {'loadbalancer_listeners': loadbalancer_listeners}
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[],
                                             list_params=[
                                                 'loadbalancer_listeners']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_loadbalancer_backends(self, loadbalancer_backends=None,
                                       loadbalancer_listener=None,
                                       loadbalancer=None,
                                       verbose=0,
                                       limit=None,
                                       offset=None,
                                       **ignore):
        """ Describe load balancer backends.
        @param loadbalancer_backends: filter by load balancer backends ID.
        @param loadbalancer_listener: filter by load balancer listener ID.
        @param loadbalancer: filter by load balancer ID.
        @param verbose: the number to specify the verbose level, larger the number, the more detailed information will be returned.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_LOADBALANCER_BACKENDS
        valid_keys = ['loadbalancer_backends', 'loadbalancer_listener',
                      'loadbalancer', 'verbose', 'limit', 'offset']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'verbose', 'limit', 'offset'],
                                             list_params=[
                                                 'loadbalancer_backends']
                                             ):
            return None

        return self.send_request(action, body)

    def add_backends_to_listener(self, loadbalancer_listener,
                                 backends,
                                 target_user=None,
                                 **ignore):
        """ Add one or more backends to load balancer listener.
        @param loadbalancer_listener: the ID of load balancer listener
        @param backends: the load balancer backends to add
        @param target_user: ID of user who will own this resource, should be one of your sub-accounts
        """
        action = const.ACTION_ADD_LOADBALANCER_BACKENDS
        body = {'loadbalancer_listener': loadbalancer_listener,
                'backends': backends}
        if target_user:
            body['target_user'] = target_user
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'loadbalancer_listener', 'backends'],
                                             integer_params=[],
                                             list_params=['backends']
                                             ):
            return None

        self.req_checker.check_lb_backends(backends)

        return self.send_request(action, body)

    def delete_loadbalancer_backends(self, loadbalancer_backends,
                                     **ignore):
        """ Delete load balancer backends.
        @param loadbalancer_backends: the array of backends IDs.
        """
        action = const.ACTION_DELETE_LOADBALANCER_BACKENDS
        body = {'loadbalancer_backends': loadbalancer_backends}
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'loadbalancer_backends'],
                                             integer_params=[],
                                             list_params=[
                                                 'loadbalancer_backends']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_loadbalancer_backend_attributes(self, loadbalancer_backend,
                                               loadbalancer_backend_name=None,
                                               port=None,
                                               weight=None,
                                               disabled=None,
                                               **ignore):
        """ Modify load balancer backend attributes.
        @param loadbalancer_backend: the ID of backend.
        @param loadbalancer_backend_name: the name of the backend.
        @param port: backend server listen port.
        @param weight: backend server weight, valid range is from 1 to 100.
        """
        action = const.ACTION_MODIFY_LOADBALANCER_BACKEND_ATTRIBUTES
        valid_keys = ['loadbalancer_backend', 'loadbalancer_backend_name',
                      'port', 'weight', 'disabled']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'loadbalancer_backend'],
                                             integer_params=[
                                                 'port', 'weight', 'disabled'],
                                             list_params=[]
                                             ):
            return None

        if 'port' in body:
            self.req_checker.check_lb_backend_port(body['port'])
        if 'weight' in body:
            self.req_checker.check_lb_backend_weight(body['weight'])

        return self.send_request(action, body)

    def modify_loadbalancer_listener_attributes(self, loadbalancer_listener,
                                                loadbalancer_listener_name=None,
                                                balance_mode=None,
                                                forwardfor=None,
                                                healthy_check_method=None,
                                                healthy_check_option=None,
                                                session_sticky=None,
                                                **ignore):
        """ Modify load balancer listener attributes
        @param loadbalancer_listener: the ID of listener.
        @param loadbalancer_listener_name: the name of the listener.
        @param balance_mode: defined in constants.py,
                             BALANCE_ROUNDROBIN, BALANCE_LEASTCONN
        @param forwardfor: extra http headers, represented as bitwise flag defined in constants.py,
                           HEADER_QC_LB_IP, HEADER_QC_LB_ID and HEADER_X_FORWARD_FOR.
                           Example: if you need X-Forwarded-For and QC-LB-IP in http header,
                           then forwardfor should be HEADER_X_FORWARD_FOR | HEADER_QC_LB_IP.
        @param description: the description of the listener.
        """
        action = const.ACTION_MODIFY_LOADBALANCER_LISTENER_ATTRIBUTES
        valid_keys = ['loadbalancer_listener', 'loadbalancer_listener_name',
                      'balance_mode', 'forwardfor', 'healthy_check_method',
                      'healthy_check_option', 'session_sticky']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'loadbalancer_listener'],
                                             integer_params=['forwardfor'],
                                             list_params=[]
                                             ):
            return None

        if 'healthy_check_method' in body:
            self.req_checker.check_lb_listener_healthy_check_method(
                body['healthy_check_method'])
        if 'healthy_check_option' in body:
            self.req_checker.check_lb_listener_healthy_check_option(
                body['healthy_check_option'])

        return self.send_request(action, body)

    def create_loadbalancer_policy(self, loadbalancer_policy_name=None,
                                   operator=None,
                                   **ignore):
        """ Create loadbalancer policy
        @param loadbalancer_name: the name of policy.
        @param operator: operation for policy, value is 'and','or'.
                         default is 'or'
        """
        action = const.ACTION_CREATE_LOADBALANCER_POLICY
        valid_keys = ['loadbalancer_policy_name', 'operator']
        body = filter_out_none(locals(), valid_keys)

        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def describe_loadbalancer_policies(self, loadbalancer_policies=None,
                                       verbose=0,
                                       offset=None,
                                       limit=None,
                                       **ignore):
        """  Describe load balancer policies.
        @param loadbalancer_policies: filter by load balancer policy ID.
        @param verbose: the number to specify the verbose level, larger the number, the more detailed information will be returned.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """

        action = const.ACTION_DESCRIBE_LOADBALANCER_POLICIES
        valid_keys = ['loadbalancer_policies',
                      'verbose', 'offset', 'limit']
        body = filter_out_none(locals(), valid_keys)

        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=['offset', 'limit'],
                                             list_params=['loadbalancer_policies']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_loadbalancer_policy_attributes(self,
                                              loadbalancer_policy=None,
                                              loadbalancer_policy_name=None,
                                              operator=None,
                                              **ignore):
        """ Modify load balancer policy attributes
        @param loadbalancer_policy: the ID of policy.
        @param loadbalancer_policy_name: the name of policy.
        @param operator: operation for policy, value is 'and','or'.
        :return:
        """

        action = const.ACTION_MODIFY_LOADBALANCER_POLICY_ATTRIBUTES
        valid_keys = ['loadbalancer_policy', 'loadbalancer_policy_name', 'operator']
        body = filter_out_none(locals(), valid_keys)

        if not self.req_checker.check_params(body,
                                             required_params=['loadbalancer_policy'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def apply_loadbalancer_policy(self, loadbalancer_policy=None, **ignore):
        """ apply load balancer policy change
        @param loadbalancer_policy:  the ID of policy.
        """
        action = const.ACTION_APPLY_LOADBALANCER_POLICY
        valid_keys = ['loadbalancer_policy']
        body = filter_out_none(locals(), valid_keys)

        if not self.req_checker.check_params(body,
                                             required_params=['loadbalancer_policy'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def delete_loadbalancer_policies(self, loadbalancer_policies,
                                    **ignore):
        """ Delete load balancer policies.
        @param loadbalancer_policies: the array of policies IDs.
        """
        action = const.ACTION_DELETE_LOADBALANCER_POLICIES
        body = {'loadbalancer_policies': loadbalancer_policies}
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'loadbalancer_policies'],
                                             integer_params=[],
                                             list_params=[
                                                 'loadbalancer_policies']
                                             ):
            return None

        return self.send_request(action, body)

    def add_loadbalancer_policy_rules(self, loadbalancer_policy,
                                      rules, **ignore):
        """ Add one or more rules to load balancer policy.
        @param loadbalancer_policy: the ID of load balancer policy
        @param rules: the load balancer policy rules to add
        """
        action = const.ACTION_ADD_LOADBALANCER_POLICY_RULES
        body = {'loadbalancer_policy': loadbalancer_policy,
                'rules': rules}
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'loadbalancer_policy', 'rules'],
                                             integer_params=[],
                                             list_params=['rules']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_loadbalancer_policy_rules(self, loadbalancer_policy_rules=None,
                                           loadbalancer_policy=None,
                                           offset=None,
                                           limit=None,
                                           **ignore):
        """  Describe load balancer policy rules.
        @param loadbalancer_policy_rules: filter by load balancer rules ID.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """

        action = const.ACTION_DESCRIBE_LOADBALANCER_POLICY_RULES
        valid_keys = ['loadbalancer_policy_rules', 'loadbalancer_policy',
                      'offset', 'limit']
        body = filter_out_none(locals(), valid_keys)

        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=['offset', 'limit'],
                                             list_params=['loadbalancer_policy_rules']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_loadbalancer_policy_rule_attributes(self,
                                                   loadbalancer_policy_rule=None,
                                                   loadbalancer_policy_rule_name=None,
                                                   val=None,
                                                   **ignore):
        """ Modify load balancer policy rule attributes
        @param loadbalancer_policy: the ID of rule.
        @param loadbalancer_policy_name: the name of policy.
        @param val: rule new value.
        :return:
        """

        action = const.ACTION_MODIFY_LOADBALANCER_POLICY_RULE_ATTRIBUTES
        valid_keys = ['loadbalancer_policy_rule', 'loadbalancer_policy_rule_name', 'val']
        body = filter_out_none(locals(), valid_keys)

        if not self.req_checker.check_params(body,
                                             required_params=['loadbalancer_policy_rule'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def delete_loadbalancer_policy_rules(self, loadbalancer_policy_rules,
                                         **ignore):
        """ Delete load balancer policy rules.
        @param loadbalancer_policy_rules: the array of policy rule IDs.
        """
        action = const.ACTION_DELETE_LOADBALANCER_POLICY_RULES
        body = {'loadbalancer_policy_rules': loadbalancer_policy_rules}
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'loadbalancer_policy_rules'],
                                             integer_params=[],
                                             list_params=[
                                                 'loadbalancer_policy_rules']
                                             ):
            return None

        return self.send_request(action, body)

    def create_server_certificate(self, server_certificate_name=None,
                                  certificate_content=None,
                                  private_key=None,
                                  **ignore):
        """ Create server certificate
        @param server_certificate_name: the name of server certificate
        @param certificate_content: the name of server certificate
        @param private_key: the private key of server certificate
        """
        action = const.ACTION_CREATE_SERVER_CERTIFICATE
        body = {'server_certificate_name': server_certificate_name,
                'certificate_content': certificate_content,
                'private_key': private_key}
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'certificate_content', 'private_key'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body, verb='POST')

    def describe_server_certificates(self, server_certificates=None,
                                     search_word=None,
                                     verbose=0,
                                     offset=None,
                                     limit=None,
                                     **ignore):
        """  Describe server certificates.
        @param server_certificates: filter by server certificates ID.
        @param search_word: filter by server certificates name.
        @param verbose: the number to specify the verbose level,
                        larger the number, the more detailed information will be returned.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """

        action = const.ACTION_DESCRIBE_SERVER_CERTIFICATES
        valid_keys = ['server_certificates', 'search_word',
                      'verbose', 'offset', 'limit']
        body = filter_out_none(locals(), valid_keys)

        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=['verbose', 'offset', 'limit'],
                                             list_params=['server_certificates']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_server_certificate_attributes(self,
                                             server_certificate=None,
                                             server_certificate_name=None,
                                             description=None,
                                             **ignore):
        """ Modify server certificate attributes
        @param server_certificate: the ID of server certificate.
        @param server_certificate_name: server certificate new name.
        @param description: server certificate new description.
        :return:
        """

        action = const.ACTION_MODIFY_SERVER_CERTIFICATE_ATTRIBUTES
        valid_keys = ['server_certificate', 'server_certificate_name', 'description']
        body = filter_out_none(locals(), valid_keys)

        if not self.req_checker.check_params(body,
                                             required_params=['server_certificate'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def delete_server_certificates(self, server_certificates,
                                   **ignore):
        """ Delete server certificates.
        @param server_certificates: the array of policy rule IDs.
        """
        action = const.ACTION_DELETE_SERVER_CERTIFICATES
        body = {'server_certificates': server_certificates}
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'server_certificates'],
                                             integer_params=[],
                                             list_params=[
                                                 'server_certificates']
                                             ):
            return None

        return self.send_request(action, body)

    def get_monitoring_data(self, resource,
                            meters,
                            step,
                            start_time,
                            end_time,
                            decompress=False,
                            **ignore):
        """ Get resource monitoring data.
        @param resource: the ID of resource, can be instance_id, volume_id, eip_id or router_id.
        @param meters: list of metering types you want to get.
                       If resource is instance, meter can be "cpu", "disk-os", "memory",
                       "disk-%s" % attached_volume_id, "if-%s" % vxnet_mac_address.
                       If resource is volume, meter should be "disk-%s" % volume_id.
                       If resource is eip, meter should be "traffic".
                       If resource is router, meter can be "vxnet-0" and joint vxnet ID.
        @param step: The metering time step, valid steps: "5m", "15m", "30m", "1h", "2h", "1d".
        @param start_time: the starting UTC time, in the format YYYY-MM-DDThh:mm:ssZ.
        @param end_time: the ending UTC time, in the format YYYY-MM-DDThh:mm:ssZ.
        """
        action = const.ACTION_GET_MONITOR
        valid_keys = ['resource', 'meters', 'step', 'start_time', 'end_time']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'resource', 'meters', 'step', 'start_time', 'end_time'],
                                             integer_params=[],
                                             datetime_params=[
                                                 'start_time', 'end_time'],
                                             list_params=['meters']
                                             ):
            return None

        resp = self.send_request(action, body)
        if resp and resp.get('meter_set') and decompress:
            p = MonitorProcessor(resp['meter_set'], start_time, end_time, step)
            resp['meter_set'] = p.decompress_monitoring_data()
        return resp

    def get_loadbalancer_monitoring_data(self, resource,
                                         meters,
                                         step,
                                         start_time,
                                         end_time,
                                         decompress=False,
                                         **ignore):
        """ Get load balancer monitoring data.
        @param resource: the ID of resource, can be loadbalancer_id, listener_id or backend_id.
        @param meters: list of metering types you want to get, valid values: request, traffic.
        @param step: The metering time step, valid steps: "5m", "15m", "30m", "1h", "2h", "1d".
        @param start_time: the starting UTC time, in the format YYYY-MM-DDThh:mm:ssZ.
        @param end_time: the ending UTC time, in the format YYYY-MM-DDThh:mm:ssZ.
        """
        action = const.ACTION_GET_LOADBALANCER_MONITOR
        valid_keys = ['resource', 'meters', 'step', 'start_time', 'end_time']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'resource', 'meters', 'step', 'start_time', 'end_time'],
                                             integer_params=[],
                                             datetime_params=[
                                                 'start_time', 'end_time'],
                                             list_params=['meters']
                                             ):
            return None

        resp = self.send_request(action, body)
        if resp and resp.get('meter_set') and decompress:
            p = MonitorProcessor(resp['meter_set'], start_time, end_time, step)
            resp['meter_set'] = p.decompress_lb_monitoring_data()
        return resp

    def describe_snapshots(self, snapshots=None,
                           resource_id=None,
                           snapshot_type=None,
                           root_id=None,
                           owner=None,
                           status=None,
                           verbose=0,
                           search_word=None,
                           offset=None,
                           limit=None,
                           tags=None,
                           **ignore):
        """ Describe snapshots filtered by condition.
        @param snapshots: an array including IDs of the snapshots you want to list.
                          No ID specified means list all.
        @param resource_id: filter by resource ID.
        @param snapshot_type: filter by snapshot type. 0: incremantal snapshot, 1: full snapshot.
        @param root_id: filter by snapshot root ID.
        @param status: valid values include pending, available, suspended, deleted, ceased.
        @param verbose: the number to specify the verbose level,
                        larger the number, the more detailed information will be returned.
        @param search_word: the search word.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        @param tags : the array of IDs of tags.
        """
        action = const.ACTION_DESCRIBE_SNAPSHOTS
        valid_keys = ['snapshots', 'resource_id', 'snapshot_type', 'root_id', 'status',
                      'verbose', 'search_word', 'offset', 'limit', 'tags', 'owner']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 "offset", "limit", "verbose", "snapshot_type"],
                                             list_params=["snapshots", "tags"]
                                             ):
            return None

        return self.send_request(action, body)

    def create_snapshots(self, resources,
                         snapshot_name=None,
                         is_full=0,
                         **ignore):
        """ Create snapshots.
        @param resources: the IDs of resources you want to create snapshot for, the supported resource types are instance/volume.
        @param snapshot_name: the name of the snapshot.
        @param is_full: whether to create a full snapshot. 0: determined by the system. 1: should create full snapshot.
        """
        action = const.ACTION_CREATE_SNAPSHOTS
        valid_keys = ['resources', 'snapshot_name', 'is_full']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=["resources"],
                                             integer_params=["is_full"],
                                             list_params=["resources"]
                                             ):
            return None

        return self.send_request(action, body)

    def delete_snapshots(self, snapshots,
                         **ignore):
        """ Delete snapshots.
        @param snapshots: the IDs of snapshots you want to delete.
        """
        action = const.ACTION_DELETE_SNAPSHOTS
        valid_keys = ['snapshots']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=["snapshots"],
                                             integer_params=[],
                                             list_params=["snapshots"]
                                             ):
            return None

        return self.send_request(action, body)

    def apply_snapshots(self, snapshots,
                        **ignore):
        """ Apply snapshots.
        @param snapshots: the IDs of snapshots you want to apply.
        """
        action = const.ACTION_APPLY_SNAPSHOTS
        valid_keys = ['snapshots']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=["snapshots"],
                                             integer_params=[],
                                             list_params=["snapshots"]
                                             ):
            return None

        return self.send_request(action, body)

    def modify_snapshot_attributes(self, snapshot,
                                   snapshot_name=None,
                                   description=None,
                                   **ignore):
        """ Modify snapshot attributes.
        @param snapshot: the ID of snapshot whose attributes you want to modify.
        @param snapshot_name: the new snapshot name.
        @param description: the new snapshot description.
        """
        action = const.ACTION_MODIFY_SNAPSHOT_ATTRIBUTES
        valid_keys = ['snapshot', 'snapshot_name', 'description']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=["snapshot"],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def capture_instance_from_snapshot(self, snapshot,
                                       image_name=None,
                                       **ignore):
        """ Capture instance from snapshot.
        @param snapshot: the ID of snapshot you want to export as an image, this snapshot should be created from an instance.
        @param image_name: the image name.
        """
        action = const.ACTION_CAPTURE_INSTANCE_FROM_SNAPSHOT
        valid_keys = ['snapshot', 'image_name']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=["snapshot"],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def create_volume_from_snapshot(self, snapshot,
                                    volume_name=None,
                                    **ignore):
        """ Create volume from snapshot.
        @param snapshot: the ID of snapshot you want to export as an volume, this snapshot should be created from a volume.
        @param volume_name: the volume name.
        """
        action = const.ACTION_CREATE_VOLUME_FROM_SNAPSHOT
        valid_keys = ['snapshot', 'volume_name']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=["snapshot"],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def describe_rdbs(self, rdbs=None,
                      rdb_engine=None,
                      status=None,
                      owner=None,
                      verbose=0,
                      search_word=None,
                      offset=None,
                      limit=None,
                      tags=None,
                      **ignore):
        """ Describe rdbs filtered by condition.
        @param rdbs: an array including IDs of the rdbs you want to list.
                     No ID specified means list all.
        @param rdb_engine: filter by rdb engine: mysql, psql.
        @param status: valid values include pending, available, suspended, deleted, ceased.
        @param verbose: the number to specify the verbose level,
                        larger the number, the more detailed information will be returned.
        @param search_word: the search word.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        @param tags : the array of IDs of tags.
        """
        action = const.ACTION_DESCRIBE_RDBS
        valid_keys = ['rdbs', 'rdb_engine', 'status', 'owner',
                      'verbose', 'search_word', 'offset', 'limit', 'tags']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 "offset", "limit", "verbose"],
                                             list_params=["rdbs", "tags"]
                                             ):
            return None

        return self.send_request(action, body)

    def create_rdb(self, vxnet=None,
                   rdb_engine=None,
                   engine_version=None,
                   rdb_username=None,
                   rdb_password=None,
                   rdb_type=None,
                   storage_size=None,
                   rdb_name=None,
                   private_ips=None,
                   description=None,
                   auto_backup_time=None,
                   **ignore):
        """ Create one rdb.
        @param vxnet: vxnet_id.
        @param rdb_engine: set rdb engine: mysql, psql.
        @param engine_version: set rdb version, mysql support 5.5, psql support 9.4.
                               the default is 5.5.
        @param rdb_username: the rdb's username
        @param rdb_password: the rdb's password
        @param rdb_type: defined by qingcloud: 1, 2, 3, 4, 5
        @param storage_size: the size of rdb storage, min 10G, max 1000G
        @param rdb_name: the rdb's name
        @param private_ips: set node's ip, like [{"master":"192.168.100.14","topslave":"192.168.100.17"}]
        @param description: the description of this rdb
        @param auto_backup_time: auto backup time, valid value is [0, 23], any value over 23 means close
                                 autp backup. If skipped, it will choose a value randomly.
        """
        action = const.ACTION_CREATE_RDB
        valid_keys = ['vxnet', 'rdb_engine', 'engine_version', 'rdb_username',
                      'rdb_password', 'rdb_type', 'storage_size', 'rdb_name',
                      'private_ips', 'description', 'auto_backup_time']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['vxnet', 'engine_version', 'rdb_username', 'rdb_password',
                                                              'rdb_type', 'storage_size'],
                                             integer_params=['rdb_type',
                                                             'storage_size', 'auto_backup_time'],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def resize_rdbs(self, rdbs,
                    rdb_type=None,
                    storage_size=None,
                    **ignore):
        """ Resize one or more rdbs.
        @param rdbs: the IDs of the rdbs you want to resize.
        @param rdb_type: defined by qingcloud: 1, 2, 3, 4, 5
        @param cpu: cpu core number.
        @param memory: memory size in MB.
        """
        action = const.ACTION_RESIZE_RDBS
        valid_keys = ['rdbs', 'rdb_type', 'storage_size']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['rdbs'],
                                             integer_params=[
                                                 'rdb_type', 'storage_size'],
                                             list_params=['rdbs']
                                             ):
            return None

        return self.send_request(action, body)

    def start_rdbs(self, rdbs,
                   **ignore):
        """ Start one or more rdbs.
        @param rdbs: the IDs of the rdbs you want to start.
        """
        action = const.ACTION_START_RDBS
        valid_keys = ['rdbs']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['rdbs'],
                                             list_params=['rdbs']
                                             ):
            return None

        return self.send_request(action, body)

    def stop_rdbs(self, rdbs,
                  **ignore):
        """ Stop one or more rdbs.
        @param rdbs: the IDs of the rdbs you want to stop.
        """
        action = const.ACTION_STOP_RDBS
        valid_keys = ['rdbs']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['rdbs'],
                                             list_params=['rdbs']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_mongos(self, mongos=None,
                        status=None,
                        verbose=0,
                        owner=None,
                        search_word=None,
                        offset=None,
                        limit=None,
                        tags=None,
                        **ignore):
        """ Describe mongos filtered by condition.
        @param mongos: an array including IDs of the mongos you want to list.
                     No ID specified means list all.
        @param status: valid values include pending, available, suspended, deleted, ceased.
        @param verbose: the number to specify the verbose level,
                        larger the number, the more detailed information will be returned.
        @param search_word: the search word.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        @param tags : the array of IDs of tags.
        """
        action = const.ACTION_DESCRIBE_MONGOS
        valid_keys = ['mongos', 'status', 'verbose', 'search_word',
                      'offset', 'limit', 'tags', 'owner']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 "offset", "limit", "verbose"],
                                             list_params=["mongos", "tags"]
                                             ):
            return None

        return self.send_request(action, body)

    def resize_mongos(self, mongos,
                      mongo_type=None,
                      storage_size=None,
                      **ignore):
        """ Resize one or more mongos.
        @param mongos: the IDs of the mongos you want to resize.
        @param mongo_type: defined by qingcloud: 1, 2, 3, 4.
                           see: https://docs.qingcloud.com/api/mongo/resize_mongos.html
        @param cpu: cpu core number.
        @param memory: memory size in MB.
        """
        action = const.ACTION_RESIZE_MONGOS
        valid_keys = ['mongos', 'mongo_type', 'storage_size']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['mongos'],
                                             integer_params=[
                                                 'mongo_type', 'storage_size'],
                                             list_params=['mongos']
                                             ):
            return None

        return self.send_request(action, body)

    def start_mongos(self, mongos,
                     **ignore):
        """ Start one or more mongos.
        @param mongos: the IDs of the mongos you want to start.
        """
        action = const.ACTION_START_MONGOS
        valid_keys = ['mongos']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['mongos'],
                                             list_params=['mongos']
                                             ):
            return None

        return self.send_request(action, body)

    def stop_mongos(self, mongos,
                    **ignore):
        """ Stop one or more mongos.
        @param mongos: the IDs of the mongos you want to stop.
        """
        action = const.ACTION_STOP_MONGOS
        valid_keys = ['mongos']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['mongos'],
                                             list_params=['mongos']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_caches(self, caches=None,
                        status=None,
                        verbose=0,
                        owner=None,
                        search_word=None,
                        offset=None,
                        limit=None,
                        tags=None,
                        **ignore):
        """ Describe caches filtered by condition.
        @param caches: an array including IDs of the caches you want to list.
                     No ID specified means list all.
        @param status: valid values include pending, available, suspended, deleted, ceased.
        @param verbose: the number to specify the verbose level,
                        larger the number, the more detailed information will be returned.
        @param search_word: the search word.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        @param tags : the array of IDs of tags.
        """
        action = const.ACTION_DESCRIBE_CACHES
        valid_keys = ['caches', 'status', 'verbose', 'search_word',
                      'offset', 'limit', 'tags', 'owner']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 "offset", "limit", "verbose"],
                                             list_params=["caches", "tags"]
                                             ):
            return None

        return self.send_request(action, body)

    def create_cache(self, vxnet=None,
                     cache_size=None,
                     cache_type=None,
                     node_count=None,
                     cache_name=None,
                     cache_parameter_group=None,
                     private_ips=None,
                     auto_backup_time=None,
                     cache_class=None,
                     **ignore):
        """ Create a cache.
        @param vxnet: the vxnet id that cache added.
        @param cache_size: cache size, unit is GB
        @param cache_type: cache service type, now support redis2.8.17 and memcached1.4.13.
        @param node_count: cache service node number, default set 1.
        @param cache_name: cache service's name
        @param cache_parameter_group: cache service configuration group ID, if not given,
                                      set to default one.
        @param private_ips: the array of private_ips setting, include cache_role and specify private_ips
        @param auto_backup_time: auto backup time, valid value is [0, 23], any value over 23 means close
                                 autp backup. If skipped, it will choose a value randomly.
        @param cache_class: property type set 0 and high property type set 1
        """
        action = const.ACTION_CREATE_CACHE
        valid_keys = ['vxnet', 'cache_size', 'cache_type', 'node_count',
                      'cache_name', 'cache_parameter_group', 'private_ips',
                      'auto_backup_time', 'cache_class']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'vxnet', 'cache_size', 'cache_type'],
                                             integer_params=['cache_size', 'node_count',
                                                             'auto_backup_time', 'cache_class'],
                                             list_params=['private_ips']
                                             ):
            return None

        return self.send_request(action, body)

    def resize_caches(self, caches,
                      cache_size=None,
                      storage_size=None,
                      **ignore):
        """ Resize one or more caches.
        @param caches: the IDs of the caches you want to resize.
        @param cache_size: defined by qingcloud: 1 - 32 GB.
        @param cpu: cpu core number.
        @param memory: memory size in MB.
        """
        action = const.ACTION_RESIZE_CACHES
        valid_keys = ['caches', 'cache_size', 'storage_size']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['caches'],
                                             integer_params=[
                                                 'cache_size', 'storage_size'],
                                             list_params=['caches']
                                             ):
            return None

        return self.send_request(action, body)

    def start_caches(self, caches,
                     **ignore):
        """ Start one or more caches.
        @param caches: the IDs of the caches you want to start.
        """
        action = const.ACTION_START_CACHES
        valid_keys = ['caches']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['caches'],
                                             list_params=['caches']
                                             ):
            return None

        return self.send_request(action, body)

    def stop_caches(self, caches,
                    **ignore):
        """ Stop one or more caches.
        @param caches: the IDs of the caches you want to stop.
        """
        action = const.ACTION_STOP_CACHES
        valid_keys = ['caches']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['caches'],
                                             list_params=['caches']
                                             ):
            return None

        return self.send_request(action, body)

    def create_spark(self, vxnet=None,
                     spark_version=None,
                     enable_hdfs=None,
                     storage_size=None,
                     spark_type=None,
                     node_count=None,
                     spark_name=None,
                     private_ips=None,
                     spark_class=None,
                     description=None,
                     zk_id=None,
                     parameter_group=None,
                     **ignore):
        """ Create a spark cluster.
        @param vxnet: the vxnet id that spark want to join.
        @param spark_version: the version of spark, suck as 1.4.1, 1.5.0, 1.6.0
        @param enabled_hdfs: whether to use hdfs as storage or not
        @param storage_size: storage size, unit is GB
        @param spark_type: cpu-memory size of spark cluster, such as 1:1c2g, 2:2c4g, 3:2c8g, 4:4c8g, 5:8c16g
        @param node_count: spark cluster node number, at least 2 for hdfs enabled.
        @param spark_name: spark cluster's name
        @param private_ips: the array of private_ips setting, include spark_role and specified private_ips
        @param spark_class: high performance is set 0 and super-high 1
        @param zk_id: the zookeeper id which ha-enabled spark will use
        @param parameter_group: the parameter configuration group which will be applied to spark cluster
        """
        action = const.ACTION_CREATE_SPARK
        valid_keys = ['vxnet', 'storage_size', 'spark_type', 'node_count',
                      'spark_name', 'spark_version', 'private_ips',
                      'enable_hdfs', 'spark_class', "description",
                      "zk_id", "parameter_group"]
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=["vxnet", "spark_type",
                                                              "spark_version", "node_count",
                                                              "storage_size", "enable_hdfs"],
                                             integer_params=["node_count", "spark_type",
                                                             "storage_size", "enable_hdfs", "spark_class"],
                                             list_params=['private_ips']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_sparks(self, sparks=None,
                        status=None,
                        verbose=0,
                        owner=None,
                        search_word=None,
                        offset=None,
                        limit=None,
                        tags=None,
                        **ignore):
        """ Describe sparks filtered by condition.
        @param sparks: the array of spark IDs.
        @param status: pending, active, stopped, deleted, suspended, ceased
        @param verbose: the number to specify the verbose level, larger the number, the more detailed information will be returned.
        @param search_word: search word column.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        @param tags : the array of IDs of tags.
        """
        action = const.ACTION_DESCRIBE_SPARKS
        valid_keys = ['sparks', 'status', 'verbose', 'search_word',
                      'offset', 'limit', 'tags', 'owner']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'offset', 'limit'],
                                             list_params=[
                                                 'sparks', 'status', 'tags']
                                             ):
            return None

        return self.send_request(action, body)

    def start_sparks(self, sparks,
                     **ignore):
        """ Start one or more sparks.
        @param sparks: the IDs of the spark you want to start.
        """
        action = const.ACTION_START_SPARKS
        valid_keys = ['sparks']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['sparks'],
                                             list_params=['sparks']
                                             ):
            return None

        return self.send_request(action, body)

    def stop_sparks(self, sparks,
                    **ignore):
        """ Stop one or more sparks.
        @param sparks: the IDs of the spark you want to stop.
        """
        action = const.ACTION_STOP_SPARKS
        valid_keys = ['sparks']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['sparks'],
                                             list_params=['sparks']
                                             ):
            return None

        return self.send_request(action, body)

    def delete_sparks(self, sparks, **ignore):
        '''Delete one or more sparks
        @param sparks: the IDs of the spark you want to stop.
        '''
        action = const.ACTION_DELETE_SPARKS
        valid_keys = ['sparks']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['sparks'],
                                             list_params=['sparks']
                                             ):
            return None

        return self.send_request(action, body)

    def add_spark_nodes(self, spark, node_count, node_name=None, private_ips=None, **params):
        """ Add one or more spark nodes
        """
        action = const.ACTION_ADD_SPARK_NODES
        valid_keys = ['spark', 'node_count', 'node_name', 'private_ips']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'spark', 'node_count'],
                                             integer_params=['node_count'],
                                             list_params=['private_ips']
                                             ):
            return None

        return self.send_request(action, body)

    def delete_spark_nodes(self, spark, spark_nodes):
        """ Delete one or more spark nodes
        """
        action = const.ACTION_DELETE_SPARK_NODES
        valid_keys = ['spark', 'spark_nodes']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'spark', 'spark_nodes'],
                                             list_params=['spark_nodes']):
            return None

        return self.send_request(action, body)

    def describe_hadoops(self, hadoops=None,
                         status=None,
                         verbose=0,
                         owner=None,
                         search_word=None,
                         offset=None,
                         limit=None,
                         tags=None,
                         **ignore):
        """ Describe hadoops filtered by condition.
        @param hadoops: the array of hadoop IDs.
        @param status: pending, active, stopped, deleted, suspended, ceased
        @param verbose: the number to specify the verbose level, larger the number, the more detailed information will be returned.
        @param search_word: search word column.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        @param tags : the array of IDs of tags.
        """
        action = const.ACTION_DESCRIBE_HADOOPS
        valid_keys = ['hadoops', 'status', 'verbose', 'search_word',
                      'offset', 'limit', 'tags', 'owner']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'offset', 'limit'],
                                             list_params=[
                                                 'hadoops', 'status', 'tags']
                                             ):
            return None

        return self.send_request(action, body)

    def start_hadoops(self, hadoops,
                      **ignore):
        """ Start one or more hadoops.
        @param hadoops: the IDs of the hadoop you want to start.
        """
        action = const.ACTION_START_HADOOPS
        valid_keys = ['hadoops']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['hadoops'],
                                             list_params=['hadoops']
                                             ):
            return None

        return self.send_request(action, body)

    def stop_hadoops(self, hadoops,
                     **ignore):
        """ Stop one or more hadoops.
        @param hadoops: the IDs of the hadoop you want to stop.
        """
        action = const.ACTION_STOP_HADOOPS
        valid_keys = ['hadoops']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['hadoops'],
                                             list_params=['hadoops']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_dns_aliases(self, dns_aliases=None,
                             resource_id=None,
                             offset=None,
                             limit=None,
                             **ignore):
        """ Describe dns aliases filtered by condition.
        @param dns_aliases: the array of dns alias IDs.
        @param resource_id: search word column.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_DNS_ALIASES
        valid_keys = ['dns_aliases', 'resource_id', 'offset', 'limit']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'offset', 'limit'],
                                             list_params=['dns_aliases']
                                             ):
            return None

        return self.send_request(action, body)

    def associate_dns_alias(self, prefix,
                            resource,
                            **ignore):
        """ Associate DNS alias.
        @param prefix: the DNS prefix.
        @param resource: The id of resource you want to associate DNS alias with.
        """
        action = const.ACTION_ASSOCIATE_DNS_ALIAS
        valid_keys = ['prefix', 'resource']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'prefix', 'resource'],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)

    def dissociate_dns_aliases(self, dns_aliases,
                               **ignore):
        """ Dissociate DNS aliases.
        @param dns_aliases: The array of dns alias IDs you want to dissociate.
        """
        action = const.ACTION_DISSOCIATE_DNS_ALIASES
        valid_keys = ['dns_aliases']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['dns_aliases'],
                                             list_params=['dns_aliases']
                                             ):
            return None

        return self.send_request(action, body)

    def get_dns_label(self, **ignore):
        """ Get DNS label and domain name in this zone.
        """
        action = const.ACTION_GET_DNS_LABEL
        valid_keys = []
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             ):
            return None

        return self.send_request(action, body)

    def describe_zookeepers(self, zookeepers=None,
                            status=None,
                            verbose=0,
                            search_word=None,
                            owner=None,
                            offset=None,
                            limit=None,
                            tags=None,
                            **ignore):
        """ Describe zookeepers filtered by condition.
        @param zookeepers: the array of zookeeper IDs.
        @param status: pending, active, stopped, deleted, suspended, ceased
        @param verbose: the number to specify the verbose level, larger the number, the more detailed information will be returned.
        @param search_word: search word column.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        @param tags : the array of IDs of tags.
        """
        action = const.ACTION_DESCRIBE_ZOOKEEPERS
        valid_keys = ['zookeepers', 'status', 'verbose', 'search_word',
                      'offset', 'limit', 'tags', 'owner']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'offset', 'limit'],
                                             list_params=['zookeepers', 'tags']
                                             ):
            return None

        return self.send_request(action, body)

    def start_zookeepers(self, zookeepers,
                         **ignore):
        """ Start one or more zookeepers.
        @param zookeepers: the IDs of the zookeeper you want to start.
        """
        action = const.ACTION_START_ZOOKEEPERS
        valid_keys = ['zookeepers']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['zookeepers'],
                                             list_params=['zookeepers']
                                             ):
            return None

        return self.send_request(action, body)

    def stop_zookeepers(self, zookeepers,
                        **ignore):
        """ Stop one or more zookeepers.
        @param zookeepers: the IDs of the zookeeper you want to stop.
        """
        action = const.ACTION_STOP_ZOOKEEPERS
        valid_keys = ['zookeepers']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['zookeepers'],
                                             list_params=['zookeepers']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_elasticsearchs(self, elasticsearchs=None,
                            status=None,
                            verbose=0,
                            search_word=None,
                            owner=None,
                            offset=None,
                            limit=None,
                            tags=None,
                            **ignore):
        """ Describe elasticsearchs filtered by condition.
        @param elasticsearchs: the array of elasticsearchs IDs.
        @param status: pending, active, stopped, deleted, suspended, ceased
        @param verbose: the number to specify the verbose level, larger the number, the more detailed information will be returned.
        @param search_word: search word column.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        @param tags : the array of IDs of tags.
        """
        action = const.ACTION_DESCRIBE_ELASTICSEARCHS
        valid_keys = ['elasticsearchs', 'status', 'verbose', 'search_word',
                      'offset', 'limit', 'tags', 'owner']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'offset', 'limit'],
                                             list_params=['elasticsearchs', 'tags']
                                             ):
            return None

        return self.send_request(action, body)

    def start_elasticsearchs(self, elasticsearchs,
                         **ignore):
        """ Start one or more elasticsearchs.
        @param elasticsearchs: the IDs of the elasticsearch you want to start.
        """
        action = const.ACTION_START_ELASTICSEARCHS
        valid_keys = ['elasticsearchs']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['elasticsearchs'],
                                             list_params=['elasticsearchs']
                                             ):
            return None

        return self.send_request(action, body)

    def stop_elasticsearchs(self, elasticsearchs,
                        **ignore):
        """ Stop one or more elasticsearchs.
        @param elasticsearchs: the IDs of the elasticsearch you want to stop.
        """
        action = const.ACTION_STOP_ELASTICSEARCHS
        valid_keys = ['elasticsearchs']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['elasticsearchs'],
                                             list_params=['elasticsearchs']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_queues(self, queues=None,
                        status=None,
                        verbose=0,
                        owner=None,
                        search_word=None,
                        offset=None,
                        limit=None,
                        tags=None,
                        **ignore):
        """ Describe queues filtered by condition.
        @param queues: the array of queue IDs.
        @param status: pending, active, stopped, deleted, suspended, ceased
        @param verbose: the number to specify the verbose level, larger the number, the more detailed information will be returned.
        @param search_word: search word column.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        @param tags : the array of IDs of tags.
        """
        action = const.ACTION_DESCRIBE_QUEUES
        valid_keys = ['queues', 'status', 'verbose', 'search_word',
                      'offset', 'limit', 'tags', 'owner']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'offset', 'limit'],
                                             list_params=[
                                                 'queues', 'status', 'tags']
                                             ):
            return None

        return self.send_request(action, body)

    def start_queues(self, queues,
                     **ignore):
        """ Start one or more queues.
        @param queues: the IDs of the queue you want to start.
        """
        action = const.ACTION_START_QUEUES
        valid_keys = ['queues']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['queues'],
                                             list_params=['queues']
                                             ):
            return None

        return self.send_request(action, body)

    def stop_queues(self, queues,
                    **ignore):
        """ Stop one or more queues.
        @param queues: the IDs of the queue you want to stop.
        """
        action = const.ACTION_STOP_QUEUES
        valid_keys = ['queues']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['queues'],
                                             list_params=['queues']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_tags(self, tags=None,
                      resources=None,
                      search_word=None,
                      owner=None,
                      verbose=0,
                      offset=None,
                      limit=None,
                      **ignore):
        """ Describe tags filtered by condition
        @param tags: IDs of the tags you want to describe.
        @param resources: IDs of the resources.
        @param verbose: the number to specify the verbose level, larger the number, the more detailed information will be returned.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_TAGS
        valid_keys = ['tags', 'search_word',
                      'verbose', 'offset', 'limit', 'owner', 'resources']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=[
                                                 'offset', 'limit', 'verbose'],
                                             list_params=['tags', 'resources']):
            return None

        return self.send_request(action, body)

    def create_tag(self, tag_name, **ignore):
        """ Create a tag.
        @param tag_name: the name of the tag you want to create.
        """
        action = const.ACTION_CREATE_TAG
        valid_keys = ['tag_name']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body, required_params=['tag_name']):
            return None
        return self.send_request(action, body)

    def delete_tags(self, tags, **ignore):
        """ Delete one or more tags.
        @param tags: IDs of the tags you want to delete.
        """
        action = const.ACTION_DELETE_TAGS
        body = {'tags': tags}
        if not self.req_checker.check_params(body,
                                             required_params=['tags'],
                                             list_params=['tags']):
            return None
        return self.send_request(action, body)

    def modify_tag_attributes(self, tag, tag_name=None, description=None, **ignore):
        """ Modify tag attributes.
        @param tag: the ID of tag you want to modify its attributes.
        @param tag_name: the new name of tag.
        @param description: The detailed description of the resource.
        """
        action = const.ACTION_MODIFY_TAG_ATTRIBUTES
        valid_keys = ['tag', 'tag_name', 'description']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['tag']):
            return None
        return self.send_request(action, body)

    def attach_tags(self, resource_tag_pairs, **ignore):
        """ Attach one or more tags to resources.
        @param resource_tag_pairs: the pair of resource and tag.
                                   it's a list-dict, such as:
                                       [{
                                           'tag_id': 'tag-hp55o9i5',
                                           'resource_type': 'instance',
                                           'resource_id': 'i-5yn6js06'
                                       }]
        """
        action = const.ACTION_ATTACH_TAGS
        valid_keys = ['resource_tag_pairs']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'resource_tag_pairs'],
                                             list_params=['resource_tag_pairs']):
            return None
        for pair in resource_tag_pairs:
            if not isinstance(pair, dict):
                return None
            for key in ['tag_id', 'resource_id', 'resource_type']:
                if key not in pair:
                    return None

        return self.send_request(action, body)

    def detach_tags(self, resource_tag_pairs, **ignore):
        """ Detach one or more tags to resources.
        @param resource_tag_pairs: the pair of resource and tag.
                                   it's a list-dict, such as:
                                       [{
                                           'tag_id': 'tag-hp55o9i5',
                                           'resource_type': 'instance',
                                           'resource_id': 'i-5yn6js06'
                                       }]
        """
        action = const.ACTION_DETACH_TAGS
        valid_keys = ['resource_tag_pairs']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[
                                                 'resource_tag_pairs'],
                                             list_params=['resource_tag_pairs']):
            return None
        for pair in resource_tag_pairs:
            if not isinstance(pair, dict):
                return None
            for key in ['tag_id', 'resource_id', 'resource_type']:
                if key not in pair:
                    return None

        return self.send_request(action, body)

    def __getattr__(self, attr):
        """ Get api functions from each Action class
        """
        for action in self.actions:
            if hasattr(action, attr):
                return getattr(action, attr)

        raise InvalidAction(attr)

    def get_balance(self, **ignore):
        """Get the balance information filtered by conditions.
        """
        action = const.ACTION_GET_BALANCE
        valid_keys = []
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body):
            return None

        return self.send_request(action, body)

    def get_lease_info(self,
                       resource,
                       user=None,
                       **ignore):
        """ Get the lease info filtered by conditions.
        @param resource: the ID of resource.
        @param user : the ID of user.
        """
        action = const.ACTION_GET_LEASE_INFO
        valid_keys = ['resource', 'user']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['resource']):
            return None

        return self.send_request(action, body)

    def describe_alarm_policies(self,
                                alarm_policies=None,
                                alarm_policy_name=None,
                                alarm_policy_type=None,
                                search_word=None,
                                verbose=0,
                                offset=None,
                                limit=None,
                                **ignore):
        """ Describe alarm policies filtered by conditions.
        @param alarm_policies : the array of IDs of alarm_policies.
        @param alarm_policy_name : the name of alarm_policy.
        @param alarm_policy_type : the type of alarm_policy.
                                    See: https://docs.qingcloud.com/api/alarm/describe_alarm_policies.html
        @param search_word: the combined search column.
        @param verbose: the number to specify the verbose level, larger the number, the more detailed information will be returned.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_ALARM_POLICIES
        valid_keys = [
            'alarm_policies', 'alarm_policy_name', 'alarm_policy_type',
            'search_word', 'verbose', 'offset', 'limit'
        ]
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             integer_params=[
                                                 'offset', 'limit', 'verbose'
                                             ],
                                             list_params=['alarm_policies']
                                             ):
            return None

        return self.send_request(action, body)

    def create_alarm_policy(self, alarm_policy_type,
                            period,
                            alarm_policy_name=None,
                            **ignore):
        """ Create an alarm policy.
        @param alarm_policy_type : the type of alarm_policy.
        @param period: the period of alarm_policy. For example: One minute : 1m.
        @param alarm_policy_name: the name of alarm_policy.
        """
        action = const.ACTION_CREATE_ALARM_POLICY
        valid_keys = ['alarm_policy_type', 'period', 'alarm_policy_name']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['alarm_policy_type', 'period']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_alarm_policy_attributes(self, alarm_policy,
                                       alarm_policy_name=None,
                                       period=None,
                                       description=None,
                                       **ignore):
        """ Modify alarm policy attributes.
        @param alarm_policy : the ID of alarm_policy.
        @param alarm_policy_name : the name of alarm_policy.
        @param period: the check period of alarm_policy.
        @param description: the description of alarm_policy.
        """
        action = const.ACTION_MODIFY_ALARM_POLICY_ATTRIBUTES
        valid_keys = ['alarm_policy', 'alarm_policy_name', 'period', 'description']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['alarm_policy']
                                             ):
            return None

        return self.send_request(action, body)

    def delete_alarm_policies(self, alarm_policies,
                              **ignore):
        """ Delete one or more alarm policies.
        @param alarm_policies : the array of IDs of alarm policies.
        """
        action = const.ACTION_DELETE_ALARM_POLICIES
        valid_keys = ['alarm_policies']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['alarm_policies'],
                                             list_params=['alarm_policies']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_alarm_policy_rules(self, alarm_policy=None,
                                    alarm_policy_rules=None,
                                    offset=None,
                                    limit=None,
                                    **ignore):
        """ Describe alarm policy rules filtered by conditions.
        @param alarm_policy : the ID of alarm_policy.
        @param alarm_policy_rules : the array of IDs of alarm policy rules.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_ALARM_POLICY_RULES
        valid_keys = ['alarm_policy', 'alarm_policy_rules', 'offset', 'limit']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             integer_params=['offset', 'limit'],
                                             list_params=['alarm_policy_rules']
                                             ):
            return None

        return self.send_request(action, body)

    def add_alarm_policy_rules(self, alarm_policy,
                               rules,
                               **ignore):
        """ Add rules to alarm policy.
        @param alarm_policy: the ID of the alarm policy whose rules you
                               want to add.
        @param rules: a list of rules you want to add.
        """
        action = const.ACTION_ADD_ALARM_POLICY_RULES
        valid_keys = ['alarm_policy', 'rules']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['alarm_policy', 'rules'],
                                             list_params=['rules']
                                             ):
            return None

        if not self.req_checker.check_sg_rules(body.get('rules', [])):
            return None

        return self.send_request(action, body)

    def modify_alarm_policy_rule_attributes(self, alarm_policy_rule,
                                            condition_type,
                                            thresholds=None,
                                            alarm_policy_rule_name=None,
                                            data_processor=None,
                                            consecutive_periods=None,
                                            **ignore):
        """ Modify alarm policy rule attributes.
        @param alarm_policy_rule: the ID of the alarm policy rule whose content you
                               want to update.
        @param condition_type: gt for greater than, lt for less than.
        @param thresholds: the thresholds of alarm.
        @param alarm_policy_rule_name: the name of the alarm policy rule.
        @param data_processor: raw for use the monitoring data raw value, percent only for IP bandwidth monitoring.
        @param consecutive_periods: during several consecutive inspection periods, the monitoring data reaches the alarm threshold,
                                    then will trigger the alarm behavior.
        """
        action = const.ACTION_MODIFY_ALARM_POLICY_RULE_ATTRIBUTES
        valid_keys = ['alarm_policy_rule', 'condition_type', 'thresholds',
                      'alarm_policy_rule_name', 'data_processor', 'consecutive_periods']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['alarm_policy_rule', 'condition_type']
                                             ):
            return None

        return self.send_request(action, body)

    def delete_alarm_policy_rules(self, alarm_policy_rules,
                                  **ignore):
        """ Delete one or more alarm policy rules.
        @param alarm_policy_rules : the array of IDs of alarm policy rules.
        """
        action = const.ACTION_DELETE_ALARM_POLICY_RULES
        valid_keys = ['alarm_policy_rules']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['alarm_policy_rules'],
                                             list_params=['alarm_policy_rules']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_alarm_policy_actions(self, alarm_policy=None,
                                      alarm_policy_actions=None,
                                      offset=None,
                                      limit=None,
                                      **ignore):
        """ Describe alarm policy actions filtered by conditions.
        @param alarm_policy : the ID of alarm_policy.
        @param alarm_policy_actions : the array of IDs of alarm policy rules.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_ALARM_POLICY_ACTIONS
        valid_keys = ['alarm_policy', 'alarm_policy_actions', 'offset', 'limit']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             integer_params=['offset', 'limit'],
                                             list_params=['alarm_policy_actions']
                                             ):
            return None

        return self.send_request(action, body)

    def add_alarm_policy_actions(self, alarm_policy,
                                 actions,
                                 **ignore):
        """ Add actions to alarm policy.
        @param alarm_policy: the ID of the alarm policy whose actions you
                               want to add.
        @param actions: a list of actions you want to add.
        """
        action = const.ACTION_ADD_ALARM_POLICY_ACTIONS
        valid_keys = ['alarm_policy', 'actions']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['alarm_policy', 'actions'],
                                             list_params=['actions']
                                             ):
            return None

        if not self.req_checker.check_sg_rules(body.get('actions', [])):
            return None

        return self.send_request(action, body)

    def modify_alarm_policy_action_attributes(self, alarm_policy_action,
                                              trigger_action=None,
                                              trigger_status=None,
                                              **ignore):
        """ Modify alarm policy action attributes.
        @param alarm_policy_action: the ID of the alarm policy action whose content you
                                    want to update.
        @param trigger_action: the ID of the trigger action.
        @param trigger_status: when the monitor alarm state becomes 'ok' or 'alarm', the message will be sent to this trigger list.
        """
        action = const.ACTION_MODIFY_ALARM_POLICY_ACTION_ATTRIBUTES
        valid_keys = ['alarm_policy_action', 'trigger_action', 'trigger_status']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['alarm_policy_action']
                                             ):
            return None

        return self.send_request(action, body)

    def delete_alarm_policy_actions(self, alarm_policy_actions,
                                    **ignore):
        """ Delete one or more alarm policy actions.
        @param alarm_policy_actions : the array of IDs of alarm policy actions.
        """
        action = const.ACTION_DELETE_ALARM_POLICY_ACTIONS
        valid_keys = ['alarm_policy_actions']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['alarm_policy_actions'],
                                             list_params=['alarm_policy_actions']
                                             ):
            return None

        return self.send_request(action, body)

    def associate_alarm_policy(self, alarm_policy,
                               resources,
                               related_resource=None,
                               **ignore):
        """ Associate an alarm_policy on one or more resources.
        @param alarm_policy: The id of alarm policy you want to associate with resources.
        @param resources: the id of resources you want to associate alarm policy.
        @param related_resource: when the network load balancer is bound,
                                 related_resource needs to specify a public network IP ID associated with this load balancer.
        """
        action = const.ACTION_ASSOCIATE_ALARM_POLICY
        valid_keys = ['alarm_policy', 'resources', 'related_resource']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['alarm_policy', 'resources'],
                                             list_params=['resources']
                                             ):
            return None

        return self.send_request(action, body)

    def dissociate_alarm_policy(self, alarm_policy,
                                resources=None,
                                related_resource=None,
                                **ignore):
        """ Dissociate alarm policy.
        @param alarm_policy: The id of alarm policy you want to associate with resources.
        @param resources: the id of resources you want to associate alarm policy.
        @param related_resource: when the network load balancer is bound,
                                 related_resource needs to specify a public network IP ID associated with this load balancer.
        """
        action = const.ACTION_DISSOCIATE_ALARM_POLICY
        valid_keys = ['alarm_policy', 'resources', 'related_resource']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['alarm_policy'],
                                             list_params=['resources']
                                             ):
            return None

        return self.send_request(action, body)

    def apply_alarm_policy(self, alarm_policy,
                           **ignore):
        """ Apply alarm policy.
        @param alarm_policy: the ID of alarm policy which would be applied effective.
        """
        action = const.ACTION_APPLY_ALARM_POLICY
        valid_keys = ['alarm_policy']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['alarm_policy']
                                             ):
            return None
        return self.send_request(action, body)

    def describe_alarms(self, alarms=None,
                        policy=None,
                        status=None,
                        resource=None,
                        offset=None,
                        limit=None,
                        **ignore):
        """ Describe alarms filtered by condition.
        @param alarms: an array including IDs of the alarms you want to list.
        @param policy: the ID of alarm policy.
        @param status: ok stand for normal, alarm stand for alarming, insufficient stand for monitoring data cannot be collected.
        @param resource: The ID of resource which associated with the alarm.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_ALARMS
        valid_keys = ['alarms', 'policy', 'status', 'resource', 'offset', 'limit']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             integer_params=['offset', 'limit'],
                                             list_params=['alarms']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_alarm_history(self, alarm,
                               history_type=None,
                               offset=None,
                               limit=None,
                               **ignore):
        """ Describe alarm history filtered by condition.
        @param alarm: the ID of the resource alarm entity.
        @param history_type: the types including trigger_action, status_change, config_update.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_ALARM_HISTORY
        valid_keys = ['alarm', 'history_type', 'offset', 'limit']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['alarm'],
                                             integer_params=['offset', 'limit']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_shared_resource_groups(self,
                                        resource_groups=None,
                                        owner=None,
                                        **ignore):
        """ Describe resource groups which be shared with oneself.
        @param resource_groups: An array including IDs of resource groups.
        @param owner: The people who shares resource groups with oneself.
        """
        action = const.ACTION_DESCRIBE_SHARED_RESOURCE_GROUPS
        valid_keys = ['resource_groups', 'owner']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             list_params=['resource_groups']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_resource_groups(self,
                                 resource_groups=None,
                                 search_word=None,
                                 limit=None,
                                 offset=None,
                                 verbose=None,
                                 sort_key=None,
                                 reverse=None,
                                 **ignore):
        """ Describe the messages of resource groups filtered by condition.
        @param resource_groups: an array including IDs of resource groups.
        @param search_word: the search word which can be instance id and instance name.
        @param limit: specify the number of the returning results.
        @param offset: the starting offset of the returning results.
        @param verbose: Whether to return redundant message.
                        if it is 1, return the details of the instance related other resources.
        @param sort_key: the sort key, which defaults be create_time.
        @param reverse: 0 for Ascending order, 1 for Descending order.
        """
        action = const.ACTION_DESCRIBE_RESOURCE_GROUPS
        valid_keys = [
            'resource_groups', 'search_word', 'limit',
            'offset', 'verbose','sort_key','reverse'
        ]
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             integer_params=[
                                                 'offset', 'limit',
                                                 'verbose', 'reverse'
                                             ],
                                             list_params=['resource_groups']
                                             ):
            return None

        return self.send_request(action, body)

    def create_resource_groups(self,
                               resource_group_name=None,
                               description=None,
                               count=None,
                               **ignore):
        """ Create resource groups.
        @param resource_group_name: the name of resource groups.
        @param description: the description of resource groups.
        @param count: the number of resource groups created at one time.
        """
        action = const.ACTION_CREATE_RESOURCE_GROUPS
        valid_keys = ['resource_group_name','description','count']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             integer_params=['count']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_resource_group_attributes(self,
                                         resource_group,
                                         resource_group_name=None,
                                         description=None,
                                         **ignore):
        """ Modify resource group attributes.
        @param resource_group: The ID of resource group which attributes you want to modify.
        @param resource_group_name: The new name of the resource group which will be modified.
        @param description: The description of the resource group.
        """
        action = const.ACTION_MODIFY_RESOURCE_GROUP_ATTRIBUTES
        valid_keys = ['resource_group', 'resource_group_name', 'description']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['resource_group']
                                             ):
            return None

        return self.send_request(action, body)

    def delete_resource_groups(self,
                               resource_groups,
                               **ignore):
        """ Delete resource groups.
        @param resource_groups: An array including IDs of the resource groups which you want to delete.
        """
        action = const.ACTION_DELETE_RESOURCE_GROUPS
        valid_keys = ['resource_groups']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['resource_groups'],
                                             list_params=['resource_groups']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_resource_group_items(self,
                                      resource_groups=None,
                                      resources=None,
                                      limit=None,
                                      offset=None,
                                      verbose=None,
                                      sort_key=None,
                                      reverse=None,
                                      **ignore):
        """ Describe the items of resource groups filtered by condition.
        @param resource_groups: an array including IDs of resource groups.
        @param resources: an array including IDs of resources, used to query all resource groups for the resource.
        @param limit: specify the number of the returning results.
        @param offset: the starting offset of the returning results.
        @param verbose: Whether to return redundant message.
                        if it is 1, return the details of the instance related other resources.
        @param sort_key: the sort key, which defaults be create_time.
        @param reverse: 0 for ascending order, 1 for descending order.
        """
        action = const.ACTION_DESCRIBE_RESOURCE_GROUP_ITEMS
        valid_keys = [
            'resource_groups', 'search_word', 'limit',
            'offset', 'verbose', 'sort_key', 'reverse'
        ]
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             integer_params=[
                                                 'offset', 'limit',
                                                 'verbose', 'reverse'
                                             ],
                                             list_params=['resource_groups','resources']
                                             ):
            return None

        return self.send_request(action, body)

    def add_resource_group_items(self,
                                 resource_group,
                                 resources,
                                 **ignore):
        """ Add resources to the specified resource group.
        @param resource_group: the ID of the resource group.
        @param resources: a list of resources which you want to add.
        """
        action = const.ACTION_ADD_RESOURCE_GROUP_ITEMS
        valid_keys = ['resource_group', 'resources']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['resource_group', 'resources'],
                                             list_params=['resources']
                                             ):
            return None

        return self.send_request(action, body)

    def delete_resource_group_items(self,
                                    resource_group,
                                    resources,
                                    **ignore):
        """ Delete resources from the specified resource group.
        @param resource_group: the ID of the resource group.
        @param resources: An array including IDs of resources which you want to delete.
        """
        action = const.ACTION_DELETE_RESOURCE_GROUP_ITEMS
        valid_keys = ['resource_group', 'resources']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['resource_group', 'resources'],
                                             list_params=['resources']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_user_groups(self,
                             user_groups=None,
                             status=None,
                             search_word=None,
                             limit=None,
                             offset=None,
                             verbose=None,
                             sort_key=None,
                             reverse=None,
                             **ignore):
        """ Describe the messages of user groups filtered by condition.
        @param user_groups: an array including IDs of user groups.
        @param status: an array including filtering status.
        @param search_word: the search word which can be instance id and instance name.
        @param limit: specify the number of the returning results.
        @param offset: the starting offset of the returning results.
        @param verbose: Whether to return redundant message.
                        if it is 1, return the details of the instance related other resources.
        @param sort_key: the sort key, which defaults be create_time.
        @param reverse: 0 for Ascending order, 1 for Descending order.
        """
        action = const.ACTION_DESCRIBE_USER_GROUPS
        valid_keys = [
            'user_groups', 'status',
            'search_word', 'limit',
            'offset', 'verbose',
            'sort_key', 'reverse'
        ]
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             integer_params=[
                                                 'offset', 'limit',
                                                 'verbose', 'reverse'
                                             ],
                                             list_params=['user_groups', 'status']
                                             ):
            return None

        return self.send_request(action, body)

    def create_user_groups(self,
                           user_group_name=None,
                           description=None,
                           count=None,
                           **ignore):
        """ Create user groups.
        @param user_group_name: the name of user groups.
        @param description: the description of user groups.
        @param count: the number of user groups created at one time, defaults 1.
        """
        action = const.ACTION_CREATE_USER_GROUPS
        valid_keys = ['user_group_name', 'description', 'count']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             integer_params=['count']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_user_group_attributes(self,
                                     user_group,
                                     user_group_name=None,
                                     description=None,
                                     status=None,
                                     **ignore):
        """ Modify user group attributes.
        @param user_group: The ID of user group which attributes you want to modify.
        @param user_group_name: The new name of the user group which will be modified.
        @param description: The description of the resource group.
        @param status: the status of user group.
        """
        action = const.ACTION_MODIFY_USER_GROUP_ATTRIBUTES
        valid_keys = ['user_group', 'user_group_name', 'description', 'status']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['user_group']
                                             ):
            return None

        return self.send_request(action, body)

    def delete_user_groups(self,
                           user_groups,
                           **ignore):
        """ Delete the specified user groups.
        @param user_groups: An array including the IDs of the user groups.
        """
        action = const.ACTION_DELETE_USER_GROUPS
        valid_keys = ['user_groups']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['user_groups'],
                                             list_params=['user_groups']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_user_group_members(self,
                                    user_groups=None,
                                    users=None,
                                    status=None,
                                    search_word=None,
                                    limit=None,
                                    offset=None,
                                    verbose=None,
                                    sort_key=None,
                                    reverse=None,
                                    **ignore):
        """ Describe the messages of user group members filtered by condition.
        @param user_groups: an array including IDs of user groups.
        @param users: an array including IDs of users.
        @param status: an array including filtering status.
        @param search_word: the search word which can be instance id and instance name.
        @param limit: specify the number of the returning results.
        @param offset: the starting offset of the returning results.
        @param verbose: Whether to return redundant message.
                        if it is 1, return the details of the instance related other resources.
        @param sort_key: the sort key, which defaults be create_time.
        @param reverse: 0 for Ascending order, 1 for Descending order.
        """
        action = const.ACTION_DESCRIBE_USER_GROUP_MEMBERS
        valid_keys = [
            'user_groups', 'users', 'status',
            'search_word', 'limit', 'offset',
            'verbose', 'sort_key', 'reverse'
        ]
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             integer_params=[
                                                 'offset', 'limit',
                                                 'verbose', 'reverse'
                                             ],
                                             list_params=['user_groups', 'users', 'status']
                                             ):
            return None

        return self.send_request(action, body)

    def add_user_group_members(self,
                               user_group,
                               users,
                               **ignore):
        """ Add users to the specified user group.
        @param user_group: the ID of the user group.
        @param users: an array including IDs or emails of users which you want to add.
        """
        action = const.ACTION_ADD_USER_GROUP_MEMBERS
        valid_keys = ['user_group', 'users']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['user_group', 'users'],
                                             list_params=['users']
                                             ):
            return None

        return self.send_request(action, body)

    def modify_user_group_member_attributes(self,
                                            user_group,
                                            user,
                                            remarks=None,
                                            status=None,
                                            **ignore):
        """ Modify user group member attributes.
        @param user_group: The ID of user group which attributes you want to modify.
        @param user: The ID of user which attributes you want to modify.
        @param remarks: The remarks information.
        @param status: The status of user group.
        """
        action = const.ACTION_MODIFY_USER_GROUP_MEMBER_ATTRIBUTES
        valid_keys = ['user_group', 'user', 'remarks', 'status']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['user_group', 'user']
                                             ):
            return None

        return self.send_request(action, body)

    def delete_user_group_members(self,
                                  user_group,
                                  users,
                                  **ignore):
        """ Delete the specified user group members.
        @param user_group: the ID of the specified user group.
        @param users: an array including IDs of users which you want delete.
        """
        action = const.ACTION_DELETE_USER_GROUP_MEMBERS
        valid_keys = ['user_group', 'users']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['user_group', 'users'],
                                             list_params=['users']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_group_roles(self,
                             group_roles=None,
                             status=None,
                             search_word=None,
                             limit=None,
                             offset=None,
                             verbose=None,
                             sort_key=None,
                             reverse=None,
                             **ignore):
        """ Describe the group roles filtered by condition.
        @param group_roles: an array including IDs of user group roles.
        @param status: an array including role status.
        @param search_word: the search word which can be instance id and instance name.
        @param limit: specify the number of the returning results.
        @param offset: the starting offset of the returning results.
        @param verbose: Whether to return redundant message.
                        if it is 1, return the details of the instance related other resources.
        @param sort_key: the sort key, which defaults be create_time.
        @param reverse: 0 for Ascending order, 1 for Descending order.
        """
        action = const.ACTION_DESCRIBE_GROUP_ROLES
        valid_keys = [
            'group_roles', 'status',
            'search_word', 'limit',
            'offset', 'verbose',
            'sort_key', 'reverse'
        ]
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             integer_params=[
                                                 'offset', 'limit',
                                                 'verbose', 'reverse'
                                             ],
                                             list_params=['group_roles', 'status']
                                             ):
            return None

        return self.send_request(action, body)

    def create_group_roles(self,
                           role_type,
                           group_role_name=None,
                           description=None,
                           count=None,
                           **ignore):
            """ Create group roles.
            @param role_type: the type of role, Currently only support 'rule'.
            @param group_role_name: the name of group role.
            @param description: the description of group role.
            @param count: the number of user roles created at one time.
            """
            action = const.ACTION_CREATE_GROUP_ROLES
            valid_keys = ['role_type', 'group_role_name', 'description', 'count']
            body = filter_out_none(locals(), valid_keys)
            if not self.req_checker.check_params(body,
                                                 required_params=['role_type'],
                                                 integer_params=['count']
                                                 ):
                return None

            return self.send_request(action, body)

    def modify_group_role_attributes(self,
                                     group_role,
                                     role_type=None,
                                     group_role_name=None,
                                     description=None,
                                     status=None,
                                     **ignore):
        """ Modify group role attributes.
        @param group_role: The ID of group role which attributes you want to modify.
        @param role_type: The type of role, Currently only support 'rule'.
        @param group_role_name: The name of group role.
        @param description: the description of group role.
        @param status: The status of group role which could be 'disabled' or 'enabled'.
        """
        action = const.ACTION_MODIFY_GROUP_ROLE_ATTRIBUTES
        valid_keys = [
            'group_role', 'role_type', 'group_role_name', 'description', 'status'
        ]
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['group_role']
                                             ):
            return None

        return self.send_request(action, body)

    def delete_group_roles(self,
                           group_roles,
                           **ignore):
        """ Delete the specified user group members.
        @param group_roles: an array including the IDs of group roles.
        """
        action = const.ACTION_DELETE_GROUP_ROLES
        valid_keys = ['group_roles']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['group_roles'],
                                             list_params=['group_roles']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_group_role_rules(self,
                                  group_role_rules=None,
                                  group_roles=None,
                                  status=None,
                                  limit=None,
                                  offset=None,
                                  verbose=None,
                                  sort_key=None,
                                  reverse=None,
                                  **ignore):
        """ Describe the group role rules filtered by condition.
        @param group_role_rules: an array including IDs of group role rules.
        @param group_roles: an array including IDs of group roles.
        @param status: an array including status which could be 'disabled' or 'enabled'.
        @param limit: specify the number of the returning results.
        @param offset: the starting offset of the returning results.
        @param verbose: Whether to return redundant message.
                        if it is 1, return the details of the instance related other resources.
        @param sort_key: the sort key, which defaults be create_time.
        @param reverse: 0 for Ascending order, 1 for Descending order.
        """
        action = const.ACTION_DESCRIBE_GROUP_ROLE_RULES
        valid_keys = [
            'group_role_rules', 'group_roles',
            'status', 'limit', 'offset',
            'verbose', 'sort_key', 'reverse'
        ]
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             integer_params=[
                                                 'offset', 'limit',
                                                 'verbose', 'reverse'
                                             ],
                                             list_params=[
                                                 'group_role_rules', 'group_roles', 'status'
                                             ]
                                             ):
            return None

        return self.send_request(action, body)

    def add_group_role_rules(self,
                             group_role,
                             policy,
                             description=None,
                             **ignore):
        """ Add rules to the specified group role.
        @param group_role: the ID of the group role.
        @param policy: the policy whose format is 'resource_typeor.operation_type'.
                        See: https://docs.qingcloud.com/api/resource_acl/AddGroupRoleRules.html
        @param description: the description of rule.
        """
        action = const.ACTION_ADD_GROUP_ROLE_RULES
        valid_keys = ['group_role', 'policy', 'description']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['group_role', 'policy'],
                                             ):
            return None

        return self.send_request(action, body)

    def modify_group_role_rule_attributes(self,
                                          group_role_rule,
                                          description=None,
                                          policy=None,
                                          **ignore):
        """ Modify group role rule attributes.
        @param group_role_rule: the ID of group role rule whose attributes you want to modify.
        @param description: the description of group role rule.
        @param policy: the policy whose format is 'resource_type' or 'operation_type'.
        """
        action = const.ACTION_MODIFY_GROUP_ROLE_RULE_ATTRIBUTES
        valid_keys = ['group_role_rule', 'description', 'policy']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['group_role_rule']
                                             ):
            return None

        return self.send_request(action, body)

    def delete_group_role_rules(self,
                                group_role_rules=None,
                                group_roles=None,
                                **ignore):
        """ Delete some rules of group role.
        @param group_role_rules: an array including the IDs of group role rules.
        @param group_roles: an array including the IDs of group roles.
        """
        action = const.ACTION_DELETE_GROUP_ROLE_RULES
        valid_keys = ['group_role_rules', 'group_roles']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             list_params=['group_role_rules', 'group_roles']
                                             ):
            return None

        return self.send_request(action, body)

    def grant_resource_groups_to_user_groups(self,
                                             rur_set,
                                             **ignore):
        """ Grant the resource groups to user groups.
        @param rur_set: a list which contains ID of resource group,
                        ID of user group and ID of group role.
        """
        action = const.ACTION_GRANT_RESOURCE_GROUPS_TO_USER_GROUPS
        valid_keys = ['rur_set']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['rur_set'],
                                             list_params=['rur_set']
                                             ):
            return None

        if not self.req_checker.check_sg_rules(body.get('rur_set', [])):
            return None

        return self.send_request(action, body)

    def revoke_resource_groups_from_user_groups(self,
                                                ru_set,
                                                resource_groups=None,
                                                user_groups=None,
                                                group_roles=None,
                                                **ignore):
        """ Revoke the resource groups from user groups.
        @param ru_set: a list which contains ID of resource group and ID of user group.
        @param resource_groups: an array including IDs of resource groups.
                                if it is not empty, will revoke all authorization relationships of specified resource groups.
        @param user_groups: an array including IDs of user groups.
                            if it is not empty, will revoke all authorization relationships of specified user groups.
        @param group_roles: an array including IDs of group roles.
                            if it is not empty, will revoke all authorization relationships of specified group roles.
        """
        action = const.ACTION_REVOKE_RESOURCE_GROUPS_FROM_USER_GROUPS
        valid_keys = [
            'ru_set', 'resource_groups', 'user_groups', 'group_roles'
        ]
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['ru_set'],
                                             list_params=[
                                                 'ru_set', 'resource_groups',
                                                 'user_groups', 'group_roles'
                                             ]
                                             ):
            return None

        if not self.req_checker.check_sg_rules(body.get('ru_set', [])):
            return None

        return self.send_request(action, body)

    def describe_resource_user_groups(self,
                                      resource_groups=None,
                                      user_groups=None,
                                      group_roles=None,
                                      limit=None,
                                      offset=None,
                                      verbose=None,
                                      sort_key=None,
                                      reverse=None,
                                      **ignore):
        """ Describe the authorization relations between resource groups and user groups.
        @param resource_groups: an array including IDs of resource groups.
        @param user_groups: an array including IDs of user groups.
        @param group_roles: an array including IDs of group roles.
        @param limit: specify the number of the returning results.
        @param offset: the starting offset of the returning results.
        @param verbose: Whether to return redundant message.
                        if it is 1, return the details of the instance related other resources.
        @param sort_key: the sort key, which defaults be create_time.
        @param reverse: 0 for Ascending order, 1 for Descending order.
        """
        action = const.ACTION_DESCRIBE_RESOURCE_USER_GROUPS
        valid_keys = [
            'resource_groups', 'user_groups',
            'group_roles', 'limit', 'offset',
            'verbose', 'sort_key', 'reverse'
        ]
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             integer_params=[
                                                 'offset', 'limit',
                                                 'verbose', 'reverse'
                                             ],
                                             list_params=[
                                                 'resource_groups',
                                                 'user_groups',
                                                 'group_roles'
                                             ]
                                             ):
            return None

        return self.send_request(action, body)

    def create_notification_list(self, notification_list_name,
                                 notification_items,
                                 **ignore):
        """ Create new notification list.
        @param notification_list_name: the name of the notification list.
        @param notification_items: an array including IDs of the notification items.
        """
        action = const.ACTION_CREATE_NOTIFICATION_LIST
        valid_keys = ['notification_list_name', 'notification_items']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['notification_list_name', 'notification_items'],
                                             list_params=['notification_items']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_notification_lists(self, notification_lists=None,
                                    search_word=None,
                                    offset=None,
                                    limit=None,
                                    **ignore):
        """ Describe notification lists filtered by condition.
        @param notification_lists: an array including the IDs of the notification lists.
        @param search_word: the search word of notification list name.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_NOTIFICATION_LISTS
        valid_keys = ['notification_lists', 'search_word', 'offset', 'limit']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=[],
                                             integer_params=['offset', 'limit'],
                                             list_params=['notification_lists']):
            return None

        return self.send_request(action, body)

    def modify_notification_list_attributes(self, notification_list,
                                            notification_list_name=None,
                                            notification_items=None,
                                            **ignore):
        """ Modify notification list attributes.
        @param notification_list: The ID of notification list which attributes you want to modify.
        @param notification_list_name: The new name of the notification list which will be modified.
        @param notification_items: An array including IDs of notification items.
        """
        action = const.ACTION_MODIFY_NOTIFICATION_LIST_ATTRIBUTES
        valid_keys = ['notification_list', 'notification_list_name', 'notification_items']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['notification_list'],
                                             integer_params=[],
                                             list_params=['notification_items']
                                             ):
            return None

        return self.send_request(action, body)

    def delete_notification_lists(self, notification_lists,
                                  **ignore):
        """ Delete one or more notification lists.
            the notification list will not be deleted along with the notification items.
        @param notification_lists: An array including IDs of the notification lists which you want to delete.
        """
        action = const.ACTION_DELETE_NOTIFICATION_LISTS
        valid_keys = ['notification_lists']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['notification_lists'],
                                             integer_params=[],
                                             list_params=['notification_lists']
                                             ):
            return None

        return self.send_request(action, body)

    def create_notification_items(self, notification_items,
                                  **ignore):
        """ Create new notification items.
        @param notification_items: The message of notification items,each item in the array is an Object,
                                   including 'content','notification_item_type' and 'remarks'.
        """
        action = const.ACTION_CREATE_NOTIFICATION_ITEMS
        valid_keys = ['notification_items']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['notification_items'],
                                             integer_params=[],
                                             list_params=['notification_items']
                                             ):
            return None

        return self.send_request(action, body)

    def describe_notification_items(self,
                                    notification_items=None,
                                    notification_list=None,
                                    notification_item_type=None,
                                    offset=None,
                                    limit=None,
                                    **ignore):
        """ Describe notification items filtered by condition.
        @param notification_items: An array including IDs of notification items.
        @param notification_list: The ID of notification list.
        @param notification_item_type: The type of notification item, including 'email', 'phone' and 'webhook'.
        @param offset: the starting offset of the returning results.
        @param limit: specify the number of the returning results.
        """
        action = const.ACTION_DESCRIBE_NOTIFICATION_ITEMS
        valid_keys = ['notification_items', 'notification_list', 'notification_item_type', 'offset', 'limit']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             integer_params=['offset', 'limit'],
                                             list_params=['notification_items']
                                             ):
            return None

        return self.send_request(action, body)

    def delete_notification_items(self, notification_items,
                                  **ignore):
        """ Delete one or more notification items.
        @param notification_items: An array including IDs of the notification items which you want to delete.
        """
        action = const.ACTION_DELETE_NOTIFICATION_ITEMS
        valid_keys = ['notification_items']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['notification_items'],
                                             integer_params=[],
                                             list_params=['notification_items']
                                             ):
            return None

        return self.send_request(action, body)

    def verify_notification_item(self,
                                 notification_item_content,
                                 verification_code,
                                 **ignore):
        """ Verify the notification item.
            All notification items need to be verified to receive notifications.
        @param notification_item_content: The content of notification item which will be verified.
        @param verification_code: The verification code.
        """
        action = const.ACTION_VERIFY_NOTIFICATION_ITEM
        valid_keys = ['notification_item_content','verification_code']
        body = filter_out_none(locals(), valid_keys)
        if not self.req_checker.check_params(body,
                                             required_params=['notification_item_content','verification_code'],
                                             integer_params=[],
                                             list_params=[]
                                             ):
            return None

        return self.send_request(action, body)
