import json
import logging

MAX_RESPONSE_CONTENT_LENGTH = 1000


def parse_request_body(request, include_file=False):
    body = None

    # For POST/PUT/PATCH requests, parse the request body depending on content type
    if request.method in ["POST", "PUT", "PATCH"]:
        # Handle application/json
        if request.content_type == 'application/json':
            try:
                body = json.loads(request.body)
            except json.JSONDecodeError:
                body = "Invalid JSON: %s" % request.body

        # Handle application/x-www-form-urlencoded
        elif request.content_type == 'application/x-www-form-urlencoded':
            body = request.POST
        elif request.content_type.startswith('multipart/form-data'):
            # Add non-file key-value pairs
            body = {k: v for k, v in request.POST.items()}

            # Add file key-value pairs
            if include_file:
                for k, v in request.FILES.items():
                    body[k] = str(v)

        # Handle text/plain
        elif request.content_type == 'text/plain':
            try:
                body = dict(line.split('=', 1)
                            for line in request.body.decode().splitlines())
            except ValueError:
                body = "Invalid text/plain format: %s" % request.body.decode()

        # Unknown content types
        else:
            # Handle other content types
            body = "Unsupported content type: %s" % request.content_type
    else:
        # For other HTTP methods, access GET parameters with request.GET
        body = request.GET

    return body


class RequestMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Log request
        logging.info(
            "Request: method=%s; path=%s; body=%s",
            request.method,
            request.get_full_path(),
            parse_request_body(request, True),
        )

        response = self.get_response(request)

        # Log response
        logging.info(
            "Response: status_code=%s; content=%s",
            response.status_code,
            response.content[:MAX_RESPONSE_CONTENT_LENGTH] + b'... (truncated)' if len(
                response.content) >= MAX_RESPONSE_CONTENT_LENGTH else response.content,
        )

        return response
