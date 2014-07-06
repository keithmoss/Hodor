import click
from apiclient.errors import HttpError
from retries import retries, gme_exc_handler
from hodor.cli import pass_context

@click.command('projects', short_help='List accessible Google Maps Engine projects.')
@pass_context
@retries(2, exceptions=(HttpError), hook=gme_exc_handler)
def cli(ctx):
  response = ctx.service.projects().list().execute()
  for project in response['projects']:
   click.echo("%s (%s)" % (project["id"], project["name"]))
