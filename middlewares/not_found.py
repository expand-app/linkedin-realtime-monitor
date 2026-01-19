import logging
from django.http import HttpResponseNotFound

not_found_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LinkedIn Connector 404</title>
</head>
<body>
    <div style="display: flex; justify-content: center; align-items: center; min-width: 100vw; min-height: 100vh;">
        <h1>404 Not Found</h1>
    </div>
</body>
</html>
"""


class NotFoundMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        logging.info(response.status_code)

        # If response status code is 404, modify it or replace it
        if response.status_code == 404:
            return HttpResponseNotFound(not_found_html)

        return response
