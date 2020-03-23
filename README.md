# GainesvilleTips.org Backend Code

This repo handles the backend logic for fetching and searching data from the
Google Forms responses spreadsheet.  It uses Python and is run on Amazon Serverless.

## Deployment

To deploy to the dev stage, use:

```
sls deploy
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
