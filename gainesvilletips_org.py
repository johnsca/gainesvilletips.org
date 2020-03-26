import os
import pickle
import random
from base64 import b64decode

import boto3
from flask import Flask, render_template, request
from flask_httpauth import HTTPBasicAuth
from fuzzywuzzy import process
from googleapiclient.discovery import build
from jinja2 import Markup


app = Flask(__name__)
auth = HTTPBasicAuth()
db = boto3.client('dynamodb')
table = os.environ.get('SERVERS_TABLE', 'servers-table-dev')
fields = [
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
    'moderated',
]


@auth.verify_password
def verify_auth(username, password):
    admin_token = os.environ.get('ADMIN_TOKEN')
    return admin_token and username == 'admin' and password == admin_token


@app.route('/', methods=['GET'])
def index():
    data = _load_data()

    if 'search' in request.args:
        search_results = process.extract(request.args['search'], data,
                                         limit=None)
        search_results = [row for row, score in search_results
                          if score >= 60]
    else:
        search_results = []
    remaining = [item for item in data if item not in search_results]
    random_results = random.sample(remaining, min(4, len(remaining)))

    return render_template('index.html', **{
        'search_results': search_results,
        'random_results': random_results,
        'search': request.args.get('search', ''),

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
    for item in data:
        db.put_item(TableName=table, Item=_unflatten_dynamodb_item(item))
    return 'Imported'


# Helper functions (maybe split into separate file)


def _load_data():
    if os.environ.get('USE_DYNAMODB', 'false').lower() == 'true':
        return _load_dynamodb_data()
    else:
        return _load_spreadsheet_data()


def _load_dynamodb_data():
    # XXX Full table scan; totally won't scale, but we're doing this for now
    # for the fuzzy searching and random results, and we don't have enough
    # data yet to worry about integrating ElasticSearch.
    return [_flatten_dynamodb_item(item)
            for item in db.scan(TableName=table)['Items']
            if item['moderated']['S'] == 'true']


def _load_spreadsheet_data():
    # The ID and range of a sample spreadsheet.
    SPREADSHEET_ID = '1nnPbkhFI-P5TR4wqxklePRTI_aQT7XNgvYx4MclWJ5U'
    RANGE_NAME = "'Live on Site'!A2:J"

    # The file token.pickle stores the user's access and refresh tokens.
    creds = pickle.loads(b64decode(os.environ['GOOGLE_TOKEN']))

    service = build('sheets', 'v4', credentials=creds)

    # Call the Sheets API
    sheet = service.spreadsheets()
    results = sheet.values().get(spreadsheetId=SPREADSHEET_ID,
                                 range=RANGE_NAME).execute().get('values', [])
    return [
        dict({column: result[i] if i < len(result) else ''
              for i, column in enumerate(fields)},
             id=f'spreadsheet:{row}', moderated='true')
        for row, result in enumerate(results)
    ]


def _flatten_dynamodb_item(item):
    "Make a DynamoDB record sane for use (aka, we don't care about types)"
    return {field: item.get(field, {}).get('S', '')
            for field in fields}


def _unflatten_dynamodb_item(item):
    "Prepare a record for insertion into DynamoDB"
    return {k: {'S': v}
            for k, v in item.items()
            if v}
