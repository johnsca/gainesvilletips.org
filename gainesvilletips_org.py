import pickle
import random
from pathlib import Path

from flask import Flask, render_template, request
from fuzzywuzzy import process
from googleapiclient.discovery import build
from jinja2 import Markup


app = Flask(__name__)


# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

# The ID and range of a sample spreadsheet.
SPREADSHEET_ID = '1nnPbkhFI-P5TR4wqxklePRTI_aQT7XNgvYx4MclWJ5U'
RANGE_NAME = "'Live on Site'!A2:J"
# RANGE_NAME = "A2:J"

# Columns
TIMESTAMP = 0
NAME = 1
EMAIL = 2
VENUE = 3
POSITION = 4
CASH_APP = 5
VENMO = 6
PAYPAL = 7
PHOTO = 8
THUMBNAIL = 9


def _load_data():
    # The file token.pickle stores the user's access and refresh tokens.
    creds = pickle.loads(Path('token.pickle').read_bytes())

    service = build('sheets', 'v4', credentials=creds)

    # Call the Sheets API
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID,
                                range=RANGE_NAME).execute()
    return result.get('values', [])


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
        'TIMESTAMP': TIMESTAMP,
        'NAME': NAME,
        'EMAIL': EMAIL,
        'VENUE': VENUE,
        'POSITION': POSITION,
        'CASH_APP': CASH_APP,
        'VENMO': VENMO,
        'PAYPAL': PAYPAL,
        'PHOTO': PHOTO,
        'THUMBNAIL': THUMBNAIL,

        # These are used to allow opening the template directly as HTML for
        # style editing with placeholder data but also do the right thing when
        # the template is rendered.
        'html_comment': Markup('<!--'),
        'html_comment_end': Markup('-->'),
        'js_comment': Markup('/*'),
        'js_comment_end': Markup('*/'),
    })
