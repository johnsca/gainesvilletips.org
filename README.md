# [GainesvilleTips.org](https://gainesvilletips.org/)

The front end and static content of the site is hosted by WordPress.  This repo
handles the backend logic for fetching and searching data from the Google Forms
responses spreadsheet.  It uses Python and is run on Amazon Serverless.  All
logic is in [webapi.py](webapi.py) and [template.html](template.html); the rest
is just boilerplate managed by the Serverless CLI (sls).

See the [issues][] for planned future work; issues tagged with `good first issue`
are ideal to start out with when contributing.

## Development

The [template.html](template.html) file can be opened locally in your browser, and
it will be populated with test results for both search and random.

There are not yet any unit or integration tests for the backend code, so manual testing
must be done by deploying to the dev stage on AWS.

## Deployment

Deploying requires that you have the Serverless CLI installed, with AWS credentials.
You will also need a `token.pickle` file to access the spreadsheet, which can be generated
using the [Python Quickstart](https://developers.google.com/sheets/api/quickstart/python)
example from Google.

To deploy to AWS using the dev stage, use:

```
sls deploy [--stage dev]
```

To deploy to production, use:

```
sls deploy --stage prod
```

To submit a test request, use:

```
sls invoke -f webapi
```

Or with a search parameter:

```
sls invoke -f webapi --data '{"queryStringParameters": {"search": "drew"}}'
```



[issues]: https://github.com/johnsca/gainesvilletips.org/issues
