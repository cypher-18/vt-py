# Copyright © 2019 The vt-py authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import aiohttp
import asyncio
import enum
import json

from typing import Any
from typing import Dict


from .feed import Feed
from .object import Object
from .iterator import Iterator
from .version import __version__

__all__ = [
    'Client',
    'FeedType']


_API_HOST = 'https://www.virustotal.com'

# All API endpoints start with this prefix, you don't need to include the
# prefix in the paths you request as it's prepended automatically.
_ENDPOINT_PREFIX = '/api/v3'

# AppEngine server decides whether or not it should serve gzipped content
# based on Accept-Encoding and User-Agent. Non-standard UAs are not served
# with gzipped content unless it contains the string "gzip" somewhere.
# See: https://cloud.google.com/appengine/kb/#compression
_USER_AGENT_FMT = '{agent}; vtpy {version}; gzip'


def _make_sync(future):
  """Utility function that waits for an async call, making it sync."""
  return asyncio.get_event_loop().run_until_complete(future)


class APIError(Exception):
  """Class that encapsules errors returned by the VirusTotal API."""

  @classmethod
  def from_dict(cls, dict_error):
    return cls(dict_error['code'], dict_error.get('message'))

  def __init__(self, code, message):
    self.code = code
    self.message = message


class ClientResponse:
  """Class representing the HTTP responses returned by the client.

  This class is just a thing wrapper around aiohttp.ClientResponse that allows
  using it in both asynchronous and synchronous mode. Instances of this class
  have all the attributes that you can find in aiohttp.ClientResponse, like
  version, status, method, url, and so on. Methods in aiohttp.ClientResponse
  that return a coroutine have two flavors in this class: synchronous and
  asynchronous. For example, aiohttp.ClientResponse.read() becomes
  ClientResponse.read_async(), and ClientResponse.read() is the synchronous
  version of ClientResponse.read_async(). For more information about attributes
  and methods in aiohttp.ClientResponse the link below.

  https://aiohttp.readthedocs.io/en/stable/client_reference.html#aiohttp.ClientResponse
  """

  def __init__(self, aiohttp_resp):
    self._aiohttp_resp = aiohttp_resp

  def __getattr__(self, attr):
    return getattr(self._aiohttp_resp, attr)

  @property
  def content(self):
    return StreamReader(self._aiohttp_resp.content)

  async def read_async(self):
    return await self._aiohttp_resp.read()

  def read(self):
    return _make_sync(self.read_async())

  async def json_async(self):
    return await self._aiohttp_resp.json()

  def json(self):
    return _make_sync(self.json_async())

  async def text_async(self):
    return await self._aiohttp_resp.text()

  def text(self):
    return _make_sync(self.text_async())


class StreamReader:
  """Class representing the HTTP responses returned by the client.

  This class is just a thing wrapper around aiohttp.ClientResponse that allows
  using it in both asynchronous and synchronous mode. Instances of this class
  have all the attributes that you can find in aiohttp.ClientResponse, like
  version, status, method, url, and so on. Methods in aiohttp.ClientResponse
  that return a coroutine have two flavors in this class: synchronous and
  asynchronous. For example, aiohttp.ClientResponse.read() becomes
  ClientResponse.read_async(), and ClientResponse.read() is the synchronous
  version of ClientResponse.read_async(). For more information about attributes
  and methods in aiohttp.ClientResponse the link below.

  https://aiohttp.readthedocs.io/en/stable/client_reference.html#aiohttp.ClientResponse
  """

  def __init__(self, aiohttp_stream_reader):
    self._aiohttp_stream_reader = aiohttp_stream_reader

  def __getattr__(self, attr):
    return getattr(self._aiohttp_stream_reader, attr)

  async def read_async(self, n=-1):
    return await self._aiohttp_stream_reader.read(n)

  def read(self, n=-1):
    return _make_sync(self.read_async(n))

  async def readany_async(self):
    return await self._aiohttp_stream_reader.readany()

  def readany(self):
    return _make_sync(self.readany_async())

  async def readexactly_async(self, n):
    return await self._aiohttp_stream_reader.readexactly(n)

  def readexactly(self, n):
    return _make_sync(self.readexactly_async(n))

  async def readline_async(self):
    return await self._aiohttp_stream_reader.readline()

  def readline(self):
    return _make_sync(self.readline_async())

  async def readchunk_async(self):
    return await self._aiohttp_stream_reader.readchunk()

  def readchunk(self):
    return _make_sync(self.readchunk_async())


class FeedType(enum.Enum):
  FILES = 'files'


class Client:
  """Client for interacting with VirusTotal."""

  def __init__(self, apikey: str, agent: str="unknown", host: str=None):
    """Intialize the client with the provided API key.

    Args:
      apikey: VirusTotal API used by the client for authenticating.
      agent: Optional string identifying your application. Using a agent string
          is highly recommendable, as it may help in debugging issues with your
          requests server-side.
    """
    if not apikey:
      raise ValueError('Expecting API key, got: %s' % str(apikey))

    self._host = host or _API_HOST
    self._apikey = apikey
    self._agent = agent
    self._session = None

  def _full_url(self, path):
    if path.startswith('http'):
      return path
    return self._host + _ENDPOINT_PREFIX + path

  def _get_session(self):
    if not self._session:
      self._session = aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=False),
        headers={
            'X-Apikey': self._apikey,
            'Accept-Encoding': 'gzip',
            'User-Agent': _USER_AGENT_FMT.format_map({
                'agent': self._agent, 'version': __version__})})
    return self._session

  async def __aenter__(self):
    return self

  async def __aexit__(self, type, value, traceback):
    await self.close_async()

  def __enter__(self):
    return self

  def __exit__(self, type, value, traceback):
    self.close()

  def _extract_data_from_json(self, json_response):
    if not 'data' in json_response:
      raise ValueError('{} does not returns a data field'.format(path))
    return json_response['data']

  async def _response_to_json(self, response):
    error = await self.get_error(response)
    if error:
      raise error
    return await response.json_async()

  async def _response_to_object(self, response):
    json_response = await self._response_to_json(response)
    try:
      return Object.from_dict(self._extract_data_from_json(json_response))
    except ValueError as err:
      raise ValueError(
          '{} did not return an object: {}'.format(path, err))

  async def close_async(self):
    if self._session:
      await self._session.close()
      self._session = None

  def close(self, *args, **kwargs):
    return _make_sync(self.close_async(*args, **kwargs))

  async def get_error(self, response):
    if response.status == 200:
      return None
    if response.status >= 400 and response.status <= 499:
      json_response = await response.json_async()
      error = json_response.get('error')
      if error:
        return APIError.from_dict(error)
      return APIError('ClientError', await response.text_async())
    return APIError('ServerError', await response.text_async())

  async def get_async(self, path: str, params: Dict=None):
    """Sends a GET request to the given path.

    This is a low-level function that returns a raw HTTP response, no error
    checking nor response parsing is performed. See get_json_async,
    get_data_async and get_object_async for higher-level functions.
    """
    return ClientResponse(
        await self._get_session().get(self._full_url(path), params=params))

  async def get_json_async(self, path: str, params: Dict=None):
    """Sends a GET request to the given path and parses the response.

    Most VirusTotal API responses are JSON-encoded. This function parses the
    JSON, check for errors, and return the server response as a dictionary.
    """
    response = await self.get_async(path, params=params)
    return await self._response_to_json(response)

  async def get_data_async(self, path: str, params: Dict=None):
    """Sends a GET request to the given path and returns response's data.

    Most VirusTotal API responses are JSON-encoded with the following format:

      {
        "data": <response data>
      }

    This function parses the server's response and return only the data, if the
    response is not in the expected format an exception is raised. For endpoints
    where the data is a VirusTotal object you can use get_object_async instead.

    Args:
      path: A path to the VirusTotal API.

    Returns:
      Whatever the server returned in the response's data field, it may be a
      dict, list, string or other Python type, depending on the endpoint called.
    """
    json_response = await self.get_json_async(path, params=params)
    return self._extract_data_from_json(json_response)

  async def get_object_async(self, path: str, params: Dict=None):
    """Send a GET request to the given path and return an object.

    The endpoint specified by path must return an object, not a collection. This
    means that get_object_async can be used with endpoints like /files/{file_id}
    and /urls/{url_id}, which return an individual object but not with /comments,
    which returns a collection of objects.
    """
    response = await self.get_async(path, params=params)
    return await self._response_to_object(response)

  async def patch_async(self, path: str, data: Any=None):
    return ClientResponse(
        await self._get_session().patch(self._full_url(path), data=data))

  async def patch_object_async(self, path: str, obj: Object):
    data = json.dumps({'data': obj.to_dict()})
    response = await self.patch_async(path, data)
    return await self._response_to_object(response)

  async def post_async(self, path: str, data: Any=None):
    return ClientResponse(
        await self._get_session().post(self._full_url(path), data=data))

  async def post_object_async(self, path: str, obj: Object):
    data = json.dumps({'data': obj.to_dict()})
    response = await self.post_async(path, data)
    return await self._response_to_object(response)

  async def delete_async(self, path: str):
    return ClientResponse(
        await self._get_session().delete(self._full_url(path)))

  async def download_file_async(self, hash, file):
    """Download a file given its hash (SHA-256, SHA-1 or MD5).

    The file indentified by the hash will be written to the provided file
    object. The file object must be opened in write binary mode ('wb').

    Args:
      hash: File hash.
      file: A file object where the downloaded file will be written to.
    """
    response = await self.get_async('/files/{}/download'.format(hash))
    while True:
      chunk = await response.content.read_async(1024*1024)
      if not chunk:
        break
      file.write(chunk)

  def get(self, *args, **kwargs):
    return _make_sync(self.get_async(*args, **kwargs))

  def get_json(self, *args, **kwargs):
    return _make_sync(self.get_json_async(*args, **kwargs))

  def get_data(self, *args, **kwargs):
    return _make_sync(self.get_data_async(*args, **kwargs))

  def get_object(self, *args, **kwargs):
    return _make_sync(self.get_object_async(*args, **kwargs))

  def patch(self, *args, **kwargs):
    return _make_sync(self.patch_async(*args, **kwargs))

  def patch_object(self, *args, **kwargs):
    return _make_sync(self.patch_object_async(*args, **kwargs))

  def post(self, *args, **kwargs):
    return _make_sync(self.post_async(*args, **kwargs))

  def post_object(self, *args, **kwargs):
    return _make_sync(self.post_object_async(*args, **kwargs))

  def delete(self, *args, **kwargs):
    return _make_sync(self.delete_async(*args, **kwargs))

  def download_file(self, *args, **kwargs):
    return _make_sync(self.download_file_async(*args, **kwargs))

  def feed(self, feed_type: FeedType, cursor: str=None):
    """Returns an iterator for a VirusTotal feed.

    This functions returns an iterator that allows to retrieve a continuous
    stream of files as they are scanned by VirusTotal. See the documentation
    for the Feed class for more details.

    Args:
      feed_type: One of the supported feed types enumerated in FeedType.
      cursor: An optional cursor indicating where to start. This argument can
        be a string in the format 'YYYMMDDhhmm' indicating the date and time
        of the first package that will be retrieved.
    """
    return Feed(self, feed_type, cursor=cursor)

  def iterator(self, path: str, cursor: str=None,
               limit: int=None, batch_size: int=None):
    """Returns an iterator for the collection specified by the given path.

    The endpoint specified by path must return a collection of objects. An
    example of such an endpoint are /comments and /intelligence/search.

    Args:
      path: The path for an endpoint returning a collection.
      cursor: Cursor for resuming the iteration at the point it was left
          previously. A cursor can be obtained with Iterator.cursor(). This
         cursor is not the same one returned by the VirusTotal API.
      limit: Maximum number of objects that will be returned by the iterator.
         If a limit is not provided the iterator continues until it reaches the
         last object in the collection.
      batch_size: Maximum number objects retrieved on each call to the API. If
         not provided the server will decide how many objects to return.
    """
    return Iterator(self, path,
        cursor=cursor, limit=limit, batch_size=batch_size)