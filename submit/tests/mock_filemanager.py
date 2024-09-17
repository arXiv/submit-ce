"""Mock file management app for testing and development."""

from datetime import datetime
import json
from flask import Flask, Blueprint, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge, BadRequest, \
    Unauthorized, Forbidden, NotFound

from http import HTTPStatus as status

blueprint = Blueprint('filemanager', __name__)

UPLOADS = {
    1: dict(
        checksum='a1s2d3f4',
        size=593920,
        files={
            'thebestfile.pdf': dict(
                path='',
                name='thebestfile.pdf',
                file_type='PDF',
                modified=datetime.now().isoformat(),
                size=20505,
                ancillary=False,
                errors=[]
            )
        },
        errors=[]
    ),
    2: dict(checksum='4f3d2s1a', size=0, files={}, errors=[])
}


def _set_upload(upload_id, payload):
    upload_status = dict(payload)
    upload_status['files'] = {
        f'{f["path"]}{f["name"]}': f for f in upload_status['files']
    }
    UPLOADS[upload_id] = upload_status
    return _get_upload(upload_id)


def _get_upload(upload_id):
    try:
        status = dict(UPLOADS[upload_id])
    except KeyError:
        raise NotFound('Nope')
    if type(status['files']) is dict:
        status['files'] = list(status['files'].values())
    status['identifier'] = upload_id
    return status


def _add_file(upload_id, file_data):
    UPLOADS[upload_id]['files'][f'{file_data["path"]}{file_data["name"]}'] = file_data
    return _get_upload(upload_id)


@blueprint.route('/status')
def service_status():
    """Mock implementation of service status route."""
    return jsonify({'status': 'ok'})


@blueprint.route('/', methods=['POST'])
def upload_package():
    """Mock implementation of upload route."""
    if 'file' not in request.files:
        raise BadRequest('No file')
    content = request.files['file'].read()
    if len(content) > 80000:  # Arbitrary limit.
        raise RequestEntityTooLarge('Nope!')
    if 'Authorization' not in request.headers:
        raise Unauthorized('Nope!')
    if request.headers['Authorization'] != '!':     # Arbitrary value.
        raise Forbidden('No sir!')

    payload = json.loads(content)    # This is specific to the mock.
    # Not sure what the response will look like yet.
    upload_id = max(UPLOADS.keys()) + 1
    upload_status = _set_upload(upload_id, payload)
    return jsonify(upload_status), status.CREATED


@blueprint.route('/<int:upload_id>', methods=['POST'])
def add_file(upload_id):
    """Mock implementation of file upload route."""
    upload_status = _get_upload(upload_id)
    if 'file' not in request.files:
        raise BadRequest('{"error": "No file"}')
    content = request.files['file'].read()
    if len(content) > 80000:  # Arbitrary limit.
        raise RequestEntityTooLarge('{"error": "Nope!"}')
    if 'Authorization' not in request.headers:
        raise Unauthorized('{"error": "No chance"}')
    if request.headers['Authorization'] != '!':     # Arbitrary value.
        raise Forbidden('{"error": "No sir!"}')

    # Not sure what the response will look like yet.
    payload = json.loads(content)
    upload_status = _add_file(upload_id, payload)
    return jsonify(upload_status), status.CREATED


def create_fm_app():
    """Generate a mock file management app."""
    app = Flask('filemanager')
    app.register_blueprint(blueprint)
    return app
