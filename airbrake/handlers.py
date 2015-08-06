import logging
import traceback
import urllib2
import os
import sys
from xml.etree.ElementTree import Element, tostring, SubElement

from django.core.urlresolvers import resolve
from django.http import Http404

from airbrake import __version__, __app_name__, __app_url__

from airbrake.middleware import get_current_request

# Adapted from Pulse Energy's AirbrakePy
# https://github.com/pulseenergy/airbrakepy
# Changes for django compatibility by Bouke Haarsma

_DEFAULT_API_URL = 'https://airbrakeapp.com/notifier_api/v2/notices'
_DEFAULT_ENV_VARIABLES = ['DJANGO_SETTINGS_MODULE', ]
_DEFAULT_META_VARIABLES = ['HTTP_USER_AGENT', 'HTTP_COOKIE', 'REMOTE_ADDR',
                           'SERVER_NAME', 'SERVER_SOFTWARE', ]
_DEFAULT_REDACTED_KEYS = []


def to_unicode(val):
    try:
        if type(val) is unicode:
            return val
        elif isinstance(val, basestring):
            return unicode(val, 'utf-8')
        else:
            return unicode(val)
    except:
        # We do this because in some rare cases, an unexpected exception
        # is raised when coercing a value to a unicode string. However, we don't
        # want that error to actually interrupt airbrake.
        return u"*** Airbrake is unable to coerce this value to unicode! ***"


class AirbrakeHandler(logging.Handler):
    def __init__(self, api_key, env_name, api_url=_DEFAULT_API_URL,
                 timeout=30, env_variables=_DEFAULT_ENV_VARIABLES,
                 meta_variables=_DEFAULT_META_VARIABLES,
                 redacted_keys=_DEFAULT_REDACTED_KEYS):
        logging.Handler.__init__(self)
        self.api_key = api_key
        self.api_url = api_url
        self.env_name = env_name
        self.env_variables = env_variables
        self.meta_variables = meta_variables
        self.timeout = timeout
        self.redacted_keys = redacted_keys

    def emit(self, record):
        self._sendMessage(self._generate_xml(record))

    def _generate_xml(self, record):
        exn = None
        trace = None
        if record.exc_info:
            _, exn, trace = record.exc_info

        message = record.getMessage()
        if exn:
            message = u"{0}: {1}".format(message, exn)

        xml = Element('notice', dict(version='2.0'))
        SubElement(xml, 'api-key').text = self.api_key

        notifier = SubElement(xml, 'notifier')
        SubElement(notifier, 'name').text = __app_name__
        SubElement(notifier, 'version').text = __version__
        SubElement(notifier, 'url').text = __app_url__

        server_env = SubElement(xml, 'server-environment')
        SubElement(server_env, 'environment-name').text = self.env_name

        request = get_current_request()
        if request is not None:
            request_xml = SubElement(xml, 'request')
            params = SubElement(request_xml, 'params')
            session = SubElement(request_xml, 'session')
            cgi_data = SubElement(request_xml, 'cgi-data')

            try:
                match = resolve(request.path_info)
            except Http404:
                match = None

            SubElement(request_xml, 'url').text = request.build_absolute_uri()

            if match:
                SubElement(request_xml, 'component').text = match.url_name
                SubElement(request_xml, 'action').text = request.method

            for key, value in request.REQUEST.items():
                if key in self.redacted_keys:
                    value = '*** REDACTED ***'
                SubElement(params, 'var', key=to_unicode(key)).text = to_unicode(value)

            for key, value in request.session.items():
                SubElement(session, 'var', key=to_unicode(key)).text = to_unicode(value)

            for key, value in os.environ.items():
                if key in self.env_variables:
                    SubElement(cgi_data, 'var', key=to_unicode(key)).text = to_unicode(value)
            for key, value in request.META.items():
                if key in self.meta_variables:
                    SubElement(cgi_data, 'var', key=to_unicode(key)).text = to_unicode(value)

            if request.user.is_authenticated():
                user = request.user.get_profile()
                SubElement(cgi_data, 'var', key='User').text = u"{0} <{1}> ({2})".format(
                    user.full_name,
                    user.primary_email_id,
                    user.pk)

            # Get variables from top-most stack frame
            if trace is not None:
                prev = trace
                curr = trace.tb_next
                while curr is not None:
                    prev = curr
                    curr = curr.tb_next
                for key, value in prev.tb_frame.f_locals.items():
                    if key not in ['request']:
                        SubElement(cgi_data, 'var', key=to_unicode(key)).text = to_unicode(value)

        error = SubElement(xml, 'error')

        exception_class_name = None
        if exn:
            exception_class_name = to_unicode(exn.__class__.__name__)
        if not exception_class_name:
            exception_class_name = 'NO CLASS NAME SUPPLIED'

        SubElement(error, 'class').text = exception_class_name
        SubElement(error, 'message').text = to_unicode(message)

        backtrace = SubElement(error, 'backtrace')
        if trace is None:
            SubElement(backtrace, 'line', file=record.pathname,
                                          number=str(record.lineno),
                                          method=record.funcName)
        else:
            for pathname, lineno, funcName, text in traceback.extract_tb(trace):
                SubElement(backtrace, 'line', file=pathname,
                                              number=str(lineno),
                                              method=(u'{}: {}'.format(to_unicode(funcName), to_unicode(text))))

        return tostring(xml)

    def _sendHttpRequest(self, headers, message):
        request = urllib2.Request(self.api_url, message, headers)
        try:
            response = urllib2.urlopen(request, timeout=self.timeout)
            status = response.getcode()
        except urllib2.HTTPError as e:
            status = e.code
        return status

    def _sendMessage(self, message):
        headers = {"Content-Type": "text/xml"}
        status = self._sendHttpRequest(headers, message)
        if status == 200:
            return

        exceptionMessage = "Unexpected status code {0}".format(str(status))

        if status == 403:
            exceptionMessage = "Unable to send using SSL"
        elif status == 422:
            exceptionMessage = "Invalid XML sent: {0}".format(message)
        elif status == 500:
            exceptionMessage = "Destination server is unavailable. " \
                               "Please check the remote server status."
        elif status == 503:
            exceptionMessage = "Service unavailable. You may be over your " \
                               "quota."

        print >>sys.stderr, '[django-airbrake]', exceptionMessage
