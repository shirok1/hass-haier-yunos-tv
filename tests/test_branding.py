"""Check the names and serve real bundled images through HA's brand API."""

from pathlib import Path

import pytest
from homeassistant.helpers.translation import async_get_translations
from homeassistant.loader import async_get_integration
from homeassistant.setup import async_setup_component


async def test_translated_integration_name(hass):
    integration = await async_get_integration(hass, "haier_tv")
    assert integration.name == "Haier YunOS TV"
    assert integration.has_branding
    for language, expected in [("en", "Haier YunOS TV"), ("zh-Hans", "海尔 YunOS TV")]:
        translations = await async_get_translations(
            hass, language, "title", {"haier_tv"}
        )
        assert translations["component.haier_tv.title"] == expected


@pytest.mark.parametrize(
    "image", ["icon.png", "icon@2x.png", "logo.png", "logo@2x.png"]
)
async def test_local_brand_image(hass, hass_client, image):
    assert await async_setup_component(hass, "brands", {})
    client = await hass_client()
    response = await client.get(
        f"/api/brands/integration/haier_tv/{image}?placeholder=no"
    )
    assert response.status == 200
    assert response.content_type == "image/png"
    expected = await hass.async_add_executor_job(
        Path(f"custom_components/haier_tv/brand/{image}").read_bytes
    )
    assert await response.read() == expected
