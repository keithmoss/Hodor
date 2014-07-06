import os
import sys
import logging
import json
import httplib2
import time
import random
import click
import socket

import mimetypes
mimetypes.init()
mimetypes.add_type("image/jpeg", ".jp2")
mimetypes.add_type("application/shp", ".shp")
mimetypes.add_type("application/shx", ".shx")
mimetypes.add_type("application/dbf", ".dbf")
mimetypes.add_type("application/prj", ".prj")

from oauth2client.client import OAuth2WebServerFlow
from oauth2client.client import flow_from_clientsecrets
from oauth2client.file import Storage as CredentialStorage
from oauth2client.tools import run as run_oauth2
from apiclient.discovery import build as discovery_build
from apiclient.errors import HttpError
from apiclient.http import MediaFileUpload

CONTEXT_SETTINGS = dict(auto_envvar_prefix='HODOR')

# Fix for the TCP send buffer being so riciculosuly low on Windows (8192)
# These two lines of code represent two days of work by multiple people.
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 5242880)

class Context(object):

    def __init__(self):
        self.verbose = False
        self.retry = 5
        self.home = os.getcwd()

        self.version = "v1"

        # Google Maps Engine scopes
        self.RW_SCOPE = 'https://www.googleapis.com/auth/mapsengine'
        self.RO_SCOPE = 'https://www.googleapis.com/auth/mapsengine.readonly'

        # File where the user confiurable OAuth details are stored.
        self.OAUTH_CONFIG = "oauth.json"

        # File where we will store authentication credentials after acquiring them.
        self.CREDENTIALS_FILE = 'credentials-store.json'

    def log(self, msg, *args):
        """Logs a message to stderr."""
        if args:
            msg %= args
        click.echo(msg, file=sys.stderr)

    def vlog(self, msg, *args):
        """Logs a message to stderr only if verbose is enabled."""
        if self.verbose:
            self.log(msg, *args)

    def get_authenticated_service(self, scope):
      self.vlog('Authenticating...')
      with open(self.OAUTH_CONFIG) as f:
        config = json.load(f)

      flow = OAuth2WebServerFlow(
        client_id=config['client_id'],
        client_secret=config['client_secret'],
        scope=scope,
        user_agent='Landgate-Hodor/1.0')

      credential_storage = CredentialStorage(self.CREDENTIALS_FILE)
      credentials = credential_storage.get()
      if credentials is None or credentials.invalid:
        credentials = run_oauth2(flow, credential_storage)

      # if credentials.access_token_expired is False:
          # credentials.refresh(httplib2.Http())

      self.vlog('Constructing Google Maps Engine service...')
      http = credentials.authorize(httplib2.Http())
      return discovery_build('mapsengine', self.version, http=http)

    def upload_file(self, file, id, resource):
      # Retry transport and file IO errors.
      RETRYABLE_ERRORS = (httplib2.HttpLib2Error, IOError)

      self.log("Uploading file '%s'" % (file))
      start_time = time.time()

      media = MediaFileUpload(file, chunksize=self.chunk_size, resumable=True)
      if not media.mimetype():
        raise Exception("Could not determine mime-type. Please make lib mimetypes aware of it.")
      request = resource.files().insert(id=id, filename=os.path.basename(file), media_body=media)

      progressless_iters = 0
      response = None
      while response is None:
        error = None
        try:
          progress, response = request.next_chunk()
          if progress:
            self.log('Upload %d%%' % (100 * progress.progress()))
        except HttpError, err:
          # Contray to the documentation GME does't return 201/200 for the last chunk
          if err.resp.status == 204:
            response = ""
          else:
            error = err
            if err.resp.status < 500:
              raise
        except RETRYABLE_ERRORS, err:
          error = err

        if error:
          progressless_iters += 1
          self.handle_progressless_iter(error, progressless_iters)
        else:
          progressless_iters = 0

      self.log("Upload completed and took %s minutes" % (round((time.time() - start_time) / 60, 2)))

    def handle_progressless_iter(self, error, progressless_iters):
      if progressless_iters > self.retry:
        self.log('Failed to make progress for too many consecutive iterations.')
        raise error

      sleeptime = random.random() * (2**progressless_iters)
      self.log('Caught exception (%s). Sleeping for %s seconds before retry #%d.'
             % (str(error), sleeptime, progressless_iters))
      time.sleep(sleeptime)


pass_context = click.make_pass_decorator(Context, ensure=True)
cmd_folder = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                          'commands'))


class HodorCLI(click.MultiCommand):

    def list_commands(self, ctx):
        rv = []
        for filename in os.listdir(cmd_folder):
            if filename.endswith('.py') and \
               filename.startswith('cmd_'):
                rv.append(filename[4:-3])
        rv.sort()
        return rv

    def get_command(self, ctx, name):
        try:
            if sys.version_info[0] == 2:
                name = name.encode('ascii', 'replace')
            mod = __import__('hodor.commands.cmd_' + name,
                             None, None, ['cli'])
        except ImportError:
            return
        return mod.cli


@click.command(cls=HodorCLI, context_settings=CONTEXT_SETTINGS)
@click.option('-v', '--verbose', is_flag=True,
              help='Enable verbose mode.')
@click.option('--retry', default=5,
              help='Number of times to retry failed requests before giving up.')
@pass_context
def cli(ctx, verbose, retry):
  """A command line interface for Google Maps Engine."""
  ctx.verbose = verbose
  ctx.retry = retry
  ctx.service = ctx.get_authenticated_service(ctx.RW_SCOPE)