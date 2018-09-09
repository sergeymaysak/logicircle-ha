"""
Support for Logi Circle 2 Cameras.
"""

import asyncio
import logging
import weakref
import time

import aiohttp
import async_timeout
import voluptuous as vol


from homeassistant.const import (
    CONF_NAME, CONF_USERNAME, CONF_PASSWORD)
from homeassistant.components.camera import (
    PLATFORM_SCHEMA, Camera)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_validation as cv
from homeassistant.util.async_ import run_coroutine_threadsafe

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = 'Logi Cam'
PLATFORM = 'logicircle'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_PASSWORD): cv.string,
    vol.Optional(CONF_USERNAME): cv.string,
})

class LogiPlatform:
    """Platform for Logi Circle 2 Camera."""
    def __init__(self, email, password, websession):
        """Initialize with transport and credentials."""
        self._email = email
        self._password = password
        self.session = websession
        self._last_status = 401

    async def async_login(self):
        """Perform login using provided credentials."""
        payload = {'email': self._email, 'password': self._password}
        url = 'https://video.logi.com/api/accounts/authorization'
        async with self.session.post(url, json=payload) as response:
            response.raise_for_status()
            return response.cookies['prod_session']

    @property
    def needs_login(self):
        """Identify if platform needs login/re-login."""
        return (len(self.session.cookie_jar.filter_cookies('https://video.logi.com')) == 0 or
                self._last_status == 401)

    async def async_fetch_cameras(self):
        """Fetch camera snapshort image (jpeg encoded) in async fashion."""
        if self.needs_login:
            await self.async_login()

        accessories_json = await self._fetch_json('https://video.logi.com/api/accessories')
        cameras = []
        if accessories_json:
            for spec in accessories_json:
                cam = LogiCam(self, spec)
                cameras.append(cam)
        return cameras

    async def _fetch_json(self, url):
        """Fetch json from platform by specified url."""
        async with self.session.get(url, headers={'content-type': 'application/json'}) as response:
            self._last_status = response.status
            return await response.json()

class LogiCam:
    """Naive implementation using still image url from Logi Cirle 2 camera."""
    def __init__(self, platform, spec):
        """Init with platform and camera json dictionary."""
        self._platform = weakref.ref(platform)
        self._spec = spec

    @property
    def name(self):
        """Name of camera."""
        return self._spec['name']

    @property
    def accessory_id(self):
        """Identifer of receiver."""
        return self._spec['accessoryId']

    @property
    def node_id(self):
        """Node id."""
        return self._spec['nodeId']

    @property
    def still_image_url(self):
        """Url to get still image from camera."""
        js_timestamp = int(time.time() * 1000)
        return 'https://{}/api/accessories/{}/image?anticache={}'.format(self.node_id,
                                                                         self.accessory_id,
                                                                         js_timestamp)

    @property
    def activities_url(self):
        """Url to get a list of activities videos."""
        return 'https://video.logi.com/api/accessories/{}/activities'.format(self.accessory_id)

    @property
    def accessory_info_url(self):
        """Url to get info for accessory."""
        return 'https://video.logi.com/api/accessories/{}'.format(self.accessory_id)

    async def async_fetch_accessory_info(self):
        """Fetch accessory info."""
        if self._platform().needs_login:
            await self._platform().async_login()

        headers = {'content-type': 'application/json'}
        async with self._platform().session.get(self.accessory_info_url,
                                                headers=headers) as response:
            self._last_status = response.status
            if response.status < 400:
                self._spec = await response.json()                

    async def async_fetch_image(self):
        """Fetch snapshort image in async fashion."""
        if self._platform().needs_login:
            await self._platform().async_login()

        await self.async_fetch_accessory_info()

        if self._platform().needs_login:
            await self._platform().async_login()
        headers = {'content-type': 'image/jpeg',
                   'Cache-Control': 'no-cache'}
        _LOGGER.info('LOGICIRCLE: websession: {}'.format(self._platform().session))
        async with self._platform().session.get(self.still_image_url,
                                                headers=headers) as response:
            self._last_status = response.status
            image_data = await response.read()
            _LOGGER.info("LOGICIRCLE: status: {}".format(response.status))
            return image_data

    async def async_fetch_activities(self):
        """Fetc a list of detected activities videos in async fashion."""
        if self._platform().needs_login:
            await self._platform().async_login()

        payload = {'extraFields': ['activitySet'], 'operator': '<=',
                   'limit': 80, 'scanDirectionNewer': True,
                   'filter': 'relevanceLevel = 0 OR relevanceLevel >= 1'}
        headers = {'Content-type': 'application/json',
                   'Accept': 'application/json, text/plain, */*'}
        async with self._platform().session.post(self.activities_url,
                                                 headers=headers, json=payload) as response:
            activities_response = await response.json()
            self._last_status = response.status
            return activities_response['activities']


async def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Set up a Logi Circle Platform."""

    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)

    try:
        websession = async_get_clientsession(hass)
        logi_platform = LogiPlatform(username, password, websession)
        cameras = await logi_platform.async_fetch_cameras()
        devices = []
        for camera in cameras:
            devices.append(LogiCircleCamera(hass, camera))
        hass.data[PLATFORM] = logi_platform
    except Exception as ex:
        hass.components.persistent_notification.async_create(
            "Error: {}<br />"
            "Please restart hass after fixing this."
            "".format(ex),
            title='Logi Circle 2 Setup',
            notification_id='logicircle2_camera_notification')
        return

    async_add_devices(devices)


class LogiCircleCamera(Camera):
    """An implementation of an Logi Circle 2 camera."""

    def __init__(self, hass, logi_cam_device):
        """Initialize camera."""
        super().__init__()
        self.hass = hass
        self.logi_cam_device = logi_cam_device
        self._frame_interval = 0.2
        self._last_image = None

    @property
    def frame_interval(self):
        """Return the interval between frames of the mjpeg stream."""
        return self._frame_interval

    def camera_image(self):
        """Return bytes of camera image."""
        return run_coroutine_threadsafe(
            self.async_camera_image(), self.hass.loop).result()

    async def async_camera_image(self):
        """Return a still image response from the camera."""
        try:
            with async_timeout.timeout(10, loop=self.hass.loop):
                self._last_image = await self.logi_cam_device.async_fetch_image()
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout getting camera image")
            return self._last_image
        except aiohttp.ClientError as err:
            _LOGGER.error("Error getting new camera image: %s", err)
            return self._last_image

        return self._last_image

    def should_poll(self):
        """Update the state periodically."""
        return True

    @property
    def name(self):
        """Return the name of this device."""
        return self.logi_cam_device.name
