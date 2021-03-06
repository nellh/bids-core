import copy
import datetime

from .. import base
from .. import util
from .. import config
from .. import debuginfo
from .. import validators
from ..auth import containerauth, always_ok
from ..dao import (
    APIStorageException, containerstorage, snapshot, liststorage, openfmriutils
)
import containerhandler
import listhandler

log = config.log

class SnapshotHandler(containerhandler.ContainerHandler):
    use_object_id = {
        'projects': True,
        'sessions': True,
        'acquisitions': True
    }

    # This configurations are used by the SnapshotHandler class to load the storage and
    # the permissions checker to handle a request.
    #
    # "children_cont" represents the children container.
    # "list projection" is used to filter data in mongo.
    # "use_object_id" implies that the container ids are converted to ObjectId
    container_handler_configurations = {
        'projects': {
            'storage': containerstorage.ContainerStorage('project_snapshots', use_object_id=use_object_id['projects']),
            'permchecker': containerauth.default_container,
            'list_projection': {'metadata': 0, 'files': 0},
            'children_cont': 'session_snapshots'
        },
        'sessions': {
            'storage': containerstorage.ContainerStorage('session_snapshots', use_object_id=use_object_id['sessions']),
            'permchecker': containerauth.default_container,
            'parent_storage': containerstorage.ContainerStorage('project_snapshots', use_object_id=use_object_id['projects']),
            'list_projection': {'metadata': 0, 'files': 0},
            'children_cont': 'acquisition_snapshots'
        },
        'acquisitions': {
            'storage': containerstorage.ContainerStorage('acquisition_snapshots', use_object_id=use_object_id['acquisitions']),
            'permchecker': containerauth.default_container,
            'parent_storage': containerstorage.ContainerStorage('sessions', use_object_id=use_object_id['sessions']),
            'list_projection': {'metadata': 0, 'files': 0}
        }
    }

    def post(self, *args, **kwargs):
        self.abort(500, 'method not supported on snapshots')

    def put(self, *args, **kwargs):
        self.abort(500, 'method not supported on snapshots')

    def delete(self, *args, **kwargs):
        self.abort(500, 'method not supported on snapshots')

    def create(self, **kwargs):
        snap_id = kwargs.pop('cid', None)
        if snap_id:
            payload = {
                '_id': snap_id
            }
        else:
            payload = None
        origin_storage = containerstorage.ContainerStorage('projects', use_object_id=True)
        origin_id = self.get_param('project')
        if not origin_id:
            self.abort(404, 'project is required to create a snapshot')
        self.config = self.container_handler_configurations['projects']
        container = origin_storage.get_container(origin_id)
        permchecker = self._get_permchecker(container, container)
        result = permchecker(snapshot.create)('POST', _id=origin_id, payload=payload)
        return {'_id': result.inserted_id}

    def remove(self, cont_name, **kwargs):
        if cont_name != 'projects':
            self.abort(500, 'method supported only on project snapshots')
        snap_id = kwargs.pop('cid')
        self.config = self.container_handler_configurations[cont_name]
        self.storage = self.config['storage']
        container = self._get_container(snap_id)
        permchecker = self._get_permchecker(container, None)
        if not container:
            self.abort(404, 'snapshot does not exist')
        result = permchecker(snapshot.remove)('DELETE', _id=snap_id)
        return {'deleted': 1}

    def publish(self, cont_name, **kwargs):
        if cont_name != 'projects':
            self.abort(500, 'method supported only on project snapshots')
        snap_id = kwargs.pop('cid')
        payload_validator = validators.payload_from_schema_file(self, 'public.json')
        payload = self.request.json_body
        # use the validator for the POST route as the key 'value' is required
        payload_validator(payload, 'POST')
        self.config = self.container_handler_configurations[cont_name]
        self.storage = self.config['storage']
        container = self._get_container(snap_id)
        if not container:
            self.abort(404, 'snapshot does not exist')
        permchecker = self._get_permchecker(container, container)
        result = permchecker(snapshot.make_public)('PUT', _id=snap_id, payload=payload)
        return result

    def get_all_for_project(self, **kwargs):
        proj_id = kwargs.pop('cid')
        self.config = self.container_handler_configurations['projects']
        self.storage = self.config['storage']
        projection = self.config['list_projection']
        if self.is_true('metadata'):
            projection = None
        # select which permission filter will be applied to the list of results.
        if self.superuser_request:
            permchecker = always_ok
        elif self.public_request:
            permchecker = containerauth.list_public_request
        else:
            permchecker = containerauth.list_permission_checker(self)
        query = {
            'original': util.ObjectId(proj_id)
        }
        try:
            results = permchecker(self.storage.exec_op)('GET', query=query, projection=projection, public=self.public_request)
        except APIStorageException as e:
            self.abort(400, e.message)
        if results is None:
            self.abort(404, 'Element not found in container {} {}'.format(storage.cont_name, _id))
        return results

    def get_acquisitions_in_project(self, cont_name, **kwargs):
        assert cont_name == 'projects'
        _id = kwargs.pop('cid')

        self.config = self.container_handler_configurations[cont_name]
        self.storage = self.config['storage']
        container= self._get_container(_id)
        permchecker = self._get_permchecker(container)
        try:
            results = permchecker(openfmriutils.acquisitions_in_project_snapshot)('GET', _id)
        except APIStorageException as e:
            self.abort(400, e.message)
        if results is None:
            self.abort(404, 'Element not found in container {} {}'.format(cont_name, _id))
        return results

def initialize_snap_list_configurations():
    snap_list_handler_configurations = {}
    for cont_name in ['projects', 'sessions', 'acquisitions']:
        list_config = copy.copy(listhandler.list_handler_configurations[cont_name]['files'])
        list_config['storage'] = liststorage.ListStorage(
            cont_name[:-1] + '_snapshots',
            'files',
            use_object_id=list_config.get('use_object_id', False)
        )
        snap_list_handler_configurations[cont_name] = {
            'files': list_config
        }
    return snap_list_handler_configurations

snap_list_handler_configurations = initialize_snap_list_configurations()

class SnapshotFileListHandler(listhandler.FileListHandler):

    def __init__(self, request=None, response=None):
        super(SnapshotFileListHandler, self).__init__(request, response)
        self.list_handler_configurations = snap_list_handler_configurations

    def post(self, **kwargs):
        self.abort(400, 'operation not supported for snapshots')

    def delete(self, **kwargs):
        self.abort(400, 'operation not supported for snapshots')
