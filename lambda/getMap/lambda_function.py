import json

from apiutils.framework import beacon_map



def lambda_handler(event, context):
    print('Event Received: {}'.format(json.dumps(event)))
    response = beacon_map()
    print('Returning Response: {}'.format(json.dumps(response)))
    return responses.bundle_response(200, response)
