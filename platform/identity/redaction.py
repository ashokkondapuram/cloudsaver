"""Log redaction for platform processes: workspace keys and Stripe secrets never reach a log line."""
import logging
import re

from identity.keys import redact as redact_keys

STRIPE = re.compile(r'(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{8,}|whsec_[0-9A-Za-z_]{8,}')


def redact(text):
    return STRIPE.sub('[redacted]', redact_keys(text)) if isinstance(text, str) else text


def install_log_redaction():
    """Mask anything shaped like a workspace key or Stripe secret before a record is formatted or shipped."""
    factory = logging.getLogRecordFactory()
    if getattr(factory, 'platform_redacts', False):
        return

    def record(*args, **kwargs):
        item = factory(*args, **kwargs)
        if isinstance(item.msg, str):
            item.msg = redact(item.msg)
        if item.args and isinstance(item.args, tuple):
            item.args = tuple(redact(a) if isinstance(a, str) else a for a in item.args)
        return item
    record.platform_redacts = True
    logging.setLogRecordFactory(record)
