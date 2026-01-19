import uuid
import logging
from threading import local

_thread_locals = local()


# Set the trace ID
def set_trace_id(trace_id=None):
    if trace_id:
        _thread_locals.trace_id = trace_id
    else:
        _thread_locals.trace_id = generate_trace_id()


# Generate a UUID-based random trace ID
def generate_trace_id(max_length=8):
    id = str(uuid.uuid4())
    return id if max_length is None else id[:max_length]


# Get the current trace ID from the thread local variables
def get_current_trace_id():
    return getattr(_thread_locals, "trace_id", None)


# Middelware for adding trace ID to the thread
class TraceIDMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_locals.trace_id = generate_trace_id()
        response = self.get_response(request)
        return response


# Logging filter which does not filter anything but just add trace ID to each log
class TraceIDFilter(logging.Filter):

    def filter(self, record):
        record.trace_id = get_current_trace_id()
        return True
