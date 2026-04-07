import logging
import os

if (_loglevel := os.environ.get('MINIQA_LOGLEVEL')) is not None:
    logging.basicConfig(level=_loglevel.upper())
