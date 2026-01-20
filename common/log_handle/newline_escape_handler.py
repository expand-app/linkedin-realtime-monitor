import logging


class EscapeNewlineFormatter(logging.Formatter):
    def format(self, record):
        msg = super().format(record)
        msg = msg.replace('\n', '\\n').replace('\r', '\\r')
        return msg

