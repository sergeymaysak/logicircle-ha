# logicircle-ha
Home Assistant camera definition for Logi Circle  2 Camera.

This is a naive implemention of Logi Circle 2 Camera support based on shapshort image url for Home Assistant as custom component.

## Supported features
This implementation exposes any acessories registered in your `logi circle` account as cameras in Home Assistant.

## How to use

1. Copy `custom_components/camera/logicircle.py` into folder where your `configuration.yaml` is located.
2. Add to `configuration.yaml`:
```yaml
camera:
  - platform: logicircle
    username: !secret email
    password: !secret password
```

Make sure you define in your secrets.yaml email and password for your Logi Circle 2 account.

3. Enjoy )

## Todo
- private mode switch
- WebRTC streaming for live view
- services to download activities and day brief
