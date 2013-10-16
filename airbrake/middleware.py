# vim: set fileencoding=utf-8 :

"""
    threadlocals middleware
    ~~~~~~~~~~~~~~~~~~~~~~~

    make the request object everywhere available (e.g. in model instance). 

    based on: http://code.djangoproject.com/wiki/CookBookThreadlocalsAndUser
    adapted for the django-airbrake library to support logging request objects
    no matter where the exception comes from.

    Put this into your settings:
    --------------------------------------------------------------------------
        MIDDLEWARE_CLASSES = (
            ...
            'django-airbrake.middleware.ThreadLocalMiddleware',
            ...
        )
    --------------------------------------------------------------------------


    Usage:
    --------------------------------------------------------------------------
    from django-airbrake.middleware import get_current_request

    # Get the current request object:
    request = get_current_request()
    --------------------------------------------------------------------------

    :copyleft: 2009-2011 by the django-tools team, see AUTHORS for more details.
    :license: GNU GPL v3 or above, see LICENSE for more details.
"""


try:
    from threading import local
except ImportError:
    from django.utils._threading_local import local


_thread_locals = local()


def get_current_request():
    """ returns the request object for this thead """
    return getattr(_thread_locals, "request", None)


class ThreadLocalMiddleware(object):
    """ Simple middleware that adds the request object in thread local storage."""
    def process_request(self, request):
        _thread_locals.request = request
