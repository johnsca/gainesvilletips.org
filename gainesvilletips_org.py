import io
import mimetypes
import os
import pickle
import random
from base64 import b64decode
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError
from flask import abort, Flask, redirect, render_template, request
from flask_httpauth import HTTPBasicAuth
from fuzzywuzzy import process
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from jinja2 import Markup
from PIL import Image


app = Flask(__name__)
auth = HTTPBasicAuth()
db = boto3.client('dynamodb')
s3 = boto3.client('s3')
table = os.environ.get('SERVERS_TABLE', 'servers-table-dev')
photo_bucket_name = 'images-gainevilletipsorg'
photo_bucket_url = f'https://{photo_bucket_name}.s3.amazonaws.com/'
thumbnail_size = (88, 88)


@auth.verify_password
def verify_auth(username, password):
    admin_token = os.environ.get('ADMIN_TOKEN')
    return admin_token and username == 'admin' and password == admin_token


@app.route('/', methods=['GET'])
def index():
    is_added = 'added' in request.args
    if is_added:
        search_results = _load_data(request.args['added'])
        random_results = []
        if not search_results:
            abort(404)
    else:
        data = [record for record in _load_data() if record.moderated]
        if 'search' in request.args:
            search_results = process.extractBests(
                request.args['search'],
                data,
                limit=None,
                score_cutoff=60)
            search_results = [result[0] for result in search_results]
        else:
            search_results = []
        remaining = [item for item in data if item not in search_results]
        random_results = random.sample(remaining, min(4, len(remaining)))

    return render_template('index.html', **{
        'search': request.args.get('search', ''),
        'is_added': is_added,
        'search_results': search_results,
        'random_results': random_results,

        # These are used to allow opening the template directly as HTML for
        # style editing with placeholder data but also do the right thing when
        # the template is rendered.
        'html_comment': Markup('<!--'),
        'html_comment_end': Markup('-->'),
        'js_comment': Markup('/*'),
        'js_comment_end': Markup('*/'),
    })


@app.route('/form', methods=['GET'])
def form():
    return render_template('form.html', **{
        'error': '',
        'form': {},

        # These are used to allow opening the template directly as HTML for
        # style editing with placeholder data but also do the right thing when
        # the template is rendered.
        'html_comment': Markup('<!--'),
        'html_comment_end': Markup('-->'),
        'js_comment': Markup('/*'),
        'js_comment_end': Markup('*/'),
    })


@app.route('/add-server', methods=['POST'])
def add_server():
    try:
        if os.environ.get('USE_DYNAMODB', 'false').lower() != 'true':
            raise FormError('Cannot update spreadsheet')
        record = Record.from_request(request)
        if record.photo:
            _save_form_photo(record)
            _upload_photo(record)
        try:
            db.put_item(TableName=table, Item=record.to_dynamodb())
        except ClientError as e:
            raise FormError('Failed to save record') from e
        return redirect(f'/?added={record.id}', code=303)
    except FormError as e:
        return render_template('form.html', **{
            'errors': e.errors,
            'form': request.form,

            # These are used to allow opening the template directly as HTML for
            # style editing with placeholder data but also do the right thing
            # when the template is rendered.
            'html_comment': Markup('<!--'),
            'html_comment_end': Markup('-->'),
            'js_comment': Markup('/*'),
            'js_comment_end': Markup('*/'),
        })


@app.route('/moderate', methods=['GET', 'POST'])
@auth.login_required
def moderate():
    if os.environ.get('USE_DYNAMODB', 'false').lower() != 'true':
        abort(404)
    if request.method == 'POST':
        record_id = request.form.get('id')
        if request.form.get('accept') and record_id:
            db.update_item(TableName=table,
                           Key={'id': {'S': record_id}},
                           UpdateExpression='SET #field = :value',
                           ExpressionAttributeNames={'#field': 'moderated'},
                           ExpressionAttributeValues={
                               ':value': {'BOOL': True},
                           })
        elif request.form.get('delete') and record_id:
            db.delete_item(TableName=table,
                           Key={'id': {'S': record_id}})
        return redirect(f'/moderate', code=303)
    data = [record for record in _load_data() if not record.moderated]
    return render_template('index.html', **{
        'search': '',
        'is_added': False,
        'is_moderating': True,
        'search_results': data,
        'random_results': [],

        # These are used to allow opening the template directly as HTML for
        # style editing with placeholder data but also do the right thing when
        # the template is rendered.
        'html_comment': Markup('<!--'),
        'html_comment_end': Markup('-->'),
        'js_comment': Markup('/*'),
        'js_comment_end': Markup('*/'),
    })


@app.route('/import')
@auth.login_required
def import_from_spreadsheet():
    data = _load_spreadsheet_data()

    # TODO: Use batch_write_item to improve efficiency
    for record in data:
        if record._drive_file_id:
            _save_drive_photo(record)
            _upload_photo(record)
        db.put_item(TableName=table, Item=record.to_dynamodb())
    return 'Imported'


# Helper functions (maybe split into separate file)


class FormError(Exception):
    def __init__(self, errors):
        if not isinstance(errors, (list, tuple)):
            errors = [errors]
        self.errors = errors


class Record(dict):
    fields = [
        'id',
        'moderated',
        'timestamp',
        'name',
        'email',
        'venue',
        'position',
        'cash_app',
        'venmo',
        'paypal',
        'photo',
        'thumbnail',
    ]
    required_fields = ['name', 'email', 'venue', 'position']
    payment_fields = ['cash_app', 'venmo', 'paypal']
    spreadsheet_columns = {
        'timestamp': 0,
        'name': 1,
        'email': 2,
        'venue': 3,
        'position': 4,
        'cash_app': 5,
        'venmo': 6,
        'paypal': 7,
        'photo': 8,
        'thumbnail': 9,
    }
    allowed_image_exts = ['.jpg', '.jpeg', '.png', '.gif']

    def __init__(self):
        super().__init__({field: '' for field in self.fields})
        self['moderated'] = False
        self._drive_file_id = None

    def __getattr__(self, name):
        if name not in self:
            raise AttributeError(name)
        return self[name]

    def __setattr__(self, name, value):
        if name in self:
            self[name] = value
        else:
            super().__setattr__(name, value)

    @classmethod
    def _validate_request(cls, request):
        errors = []
        missing = []
        for field in ('name', 'email', 'venue', 'position'):
            if not request.form.get(field, ''):
                missing.append(field)
            elif field == 'email' and '@' not in request.form['email']:
                missing.append('a valid email')
        if not any([request.form.get(field, '')
                    for field in cls.payment_fields]):
            missing.append('at least one payment method')
        if missing:
            if 'payment' not in missing[0]:
                missing[0] = f'your {missing[0]}'
            if len(missing) > 1:
                missing[-1] = f'and {missing[-1]}'
            errors.append(f'Please provide {", ".join(missing)}')
        photo_filename = _filename(request, 'photo')
        if photo_filename:
            suffix = Path(photo_filename).suffix
            if suffix not in cls.allowed_image_exts:
                errors.append(f'Unsupported photo format: {suffix}')
        # TODO: Check for dupes
        if errors:
            raise FormError(errors)

    @classmethod
    def from_request(cls, request):
        cls._validate_request(request)
        self = cls()
        self.id = str(uuid4())
        self.moderated = False
        self.timestamp = datetime.now().isoformat()
        self.name = request.form['name']
        self.email = request.form['email']
        self.venue = request.form['venue']
        self.position = request.form['position']
        self.cash_app = request.form['cash_app']
        self.venmo = request.form['venmo']
        self.paypal = request.form['paypal']
        photo_filename = _filename(request, 'photo')
        if photo_filename:
            self.photo = f'{photo_bucket_url}{self.id}{self._suffix}'
            self.thumbnail = f'{photo_bucket_url}{self.id}-thumb{self._suffix}'
        else:
            self.photo = ''
            self.thumbnail = ''
        return self

    @classmethod
    def from_dynamodb(cls, item):
        self = cls()
        for field, value in item.items():
            setattr(self, field, list(value.values())[0])
        return self

    @classmethod
    def from_spreadsheet(cls, row_num, data):
        self = cls()
        self.id = f'spreadsheet-{row_num}'
        self.moderated = True
        for field, col_num in self.spreadsheet_columns.items():
            value = data[col_num] if col_num < len(data) else ''
            setattr(self, field, value)
        if self.photo.startswith('https://drive.google.com/'):
            self._drive_file_id = parse_qs(urlparse(self.photo).query)['id'][0]
            self.photo = ''
        return self

    def to_dynamodb(self):
        item = {}
        for field, value in self.items():
            if not value:
                continue
            item_type = 'BOOL' if field == 'moderated' else 'S'
            item[field] = {item_type: value}
        return item

    @property
    def photo_filename(self):
        return Path(urlparse(self.photo).path).name

    @property
    def thumb_filename(self):
        return Path(urlparse(self.thumbnail).path).name


def _load_data(item_id=None):
    if os.environ.get('USE_DYNAMODB', 'false').lower() == 'true':
        return _load_dynamodb_data(item_id)
    else:
        return _load_spreadsheet_data(item_id)


def _load_dynamodb_data(item_id=None):
    if item_id is not None:
        result = db.get_item(TableName=table, Key={'id': {'S': item_id}})
        if 'Item' not in result:
            return []
        return [Record.from_dynamodb(result['Item'])]
    # XXX Full table scan; totally won't scale, but we're doing this for now
    # for the fuzzy searching and random results, and we don't have enough
    # data yet to worry about integrating ElasticSearch.
    results = db.scan(TableName=table)
    if 'Items' not in results:
        return []
    return [Record.from_dynamodb(item) for item in results['Items']]


def _gapi(api_name, version):
    creds = pickle.loads(b64decode(os.environ['GOOGLE_TOKEN']))
    service = build(api_name, version, credentials=creds)
    return service


def _load_spreadsheet_data(item_id=None):
    # The ID and range of a sample spreadsheet.
    SPREADSHEET_ID = '1nnPbkhFI-P5TR4wqxklePRTI_aQT7XNgvYx4MclWJ5U'
    RANGE_NAME = "'Live on Site'!A2:J"

    sheet = _gapi('sheets', 'v4').spreadsheets()
    results = sheet.values().get(spreadsheetId=SPREADSHEET_ID,
                                 range=RANGE_NAME).execute().get('values', [])
    return [Record.from_spreadsheet(row_num, data)
            for row_num, data in enumerate(results)]


def _filename(request, field):
    if field not in request.files:
        return None
    return request.files[field].filename or None


def _save_form_photo(record):
    request.files['photo'].save(f'/tmp/{record.photo_filename}')


def _save_drive_photo(record):
    drive = _gapi('drive', 'v3').files()

    metadata = drive.get(fileId=record._drive_file_id).execute()
    suffix = '.' + metadata['mimeType'].split('/')[1]
    record.photo = f'{photo_bucket_url}{record.id}{suffix}'
    record.thumbnail = f'{photo_bucket_url}{record.id}-thumb{suffix}'

    request = drive.get_media(fileId=record._drive_file_id)
    with open(f'/tmp/{record.photo_filename}', 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()


def _upload_photo(record):
    content_type = mimetypes.guess_type(record.photo_filename)[0]
    photo_tmp_file = f'/tmp/{record.photo_filename}'
    thumb_tmp_file = f'/tmp/{record.thumb_filename}'
    try:
        thumb = Image.open(photo_tmp_file)
        thumb.thumbnail(thumbnail_size)
        thumb.save(thumb_tmp_file)
    except Exception as e:
        if app.debug:
            raise
        raise FormError('Unable to process photo') from e
    try:
        s3.upload_file(photo_tmp_file,
                       photo_bucket_name,
                       record.photo_filename,
                       ExtraArgs={'ContentType': content_type})
        s3.upload_file(thumb_tmp_file,
                       photo_bucket_name,
                       record.thumb_filename,
                       ExtraArgs={'ContentType': content_type})
    except ClientError as e:
        if app.debug:
            raise
        raise FormError('Unable to upload photo') from e
