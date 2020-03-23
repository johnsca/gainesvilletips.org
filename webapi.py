import pickle
import random
from pathlib import Path
from traceback import format_exc

from fuzzywuzzy import process
from googleapiclient.discovery import build
from jinja2 import Template


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


def serve(event, context):
    try:
        template = Template(Path('template.html').read_text())
        params = event.get("queryStringParameters") or {}

        data = _load_data()

        if 'search' in params:
            search_results = process.extract(params['search'], data,
                                             limit=None)
            search_results = [row for row, score in search_results
                              if score >= 60]
        else:
            search_results = []
        remaining = [item for item in data if item not in search_results]
        random_results = random.sample(remaining, min(4, len(remaining)))

        response = {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'text/html',
            },
            'body': template.render({
                'search_results': search_results,
                'random_results': random_results,
                'search': params.get('search', ''),
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
            }),
        }

        return response
    except Exception:
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'text/plain',
            },
            'body': format_exc(),
        }
