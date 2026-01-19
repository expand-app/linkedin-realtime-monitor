class SilenceLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Modify this condition to fit the actual pattern of Selenium's requests
        if "/session/" in request.path:
            # Attach an attribute to the request to signal that it shouldn't be logged
            request.is_silence_log = True

        response = self.get_response(request)
        return response


class SilenceLoggingFilter:
    def filter(self, record):
        return record.is_silence_log
