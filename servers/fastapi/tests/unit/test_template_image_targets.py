import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import uuid

import pytest

from api.v1.ppt.endpoints.presentation import _apply_template_content_to_ui
from models.image_prompt import ImagePrompt
from models.sql.slide import SlideModel
from services.chat.memory_layer import PresentationChatMemoryLayer
from services.image_generation_service import (
    DALLE3_IMAGE_SIZES,
    GEMINI_IMAGE_RATIOS,
    GPT_IMAGE_SIZES,
    ImageGenerationService,
    _closest_aspect_ratio,
)
from utils.process_slides import (
    image_target_sizes_from_template,
    process_slide_and_fetch_assets,
)


def test_image_target_sizes_match_slots_with_identical_prompts():
    layout = {
        "components": [{
            "id": "hero",
            "elements": [
                {"type": "image", "name": "wide", "decorative": False,
                 "size": {"width": 400, "height": 200}},
                {"type": "image", "name": "tall", "decorative": False,
                 "size": {"width": 100, "height": 300}},
            ],
        }],
    }
    content = {"hero": {
        "wide": {"image_prompt": "same prompt"},
        "tall": {"image_prompt": "same prompt"},
    }}

    sizes = image_target_sizes_from_template(
        layout, content, _apply_template_content_to_ui
    )

    assert sizes[(('key', 'hero'), ('key', 'wide'))] == (400, 200)
    assert sizes[(('key', 'hero'), ('key', 'tall'))] == (100, 300)
    assert "image_url" not in content["hero"]["wide"]


def test_chat_hydration_matches_repeated_image_slots():
    layout = {"components": [{"id": "gallery", "elements": [{
        "type": "grid", "name": "photos", "children": [
            {"type": "image", "name": "photo", "decorative": False,
             "size": {"width": 300, "height": 150}}
        ],
    }]}]}
    content = {"gallery": {"photos": [
        {"image_prompt": "same"}, {"image_prompt": "same"},
    ]}}

    sizes = image_target_sizes_from_template(
        layout, content, PresentationChatMemoryLayer._apply_template_content_to_ui
    )

    assert sizes[(('key', 'gallery'), ('key', 'photos'), ('index', 0))] == (300, 150)
    assert sizes[(('key', 'gallery'), ('key', 'photos'), ('index', 1))] == (300, 150)


@pytest.mark.anyio
async def test_asset_generation_receives_target_size_and_missing_size_falls_back():
    service = AsyncMock()
    service.generate_image.side_effect = [
        "https://example.com/wide.png", "https://example.com/square.png"
    ]
    slide = SlideModel(
        presentation=uuid.uuid4(), layout_group="test", layout="test", index=0,
        content={"first": {"image_prompt": "wide"}, "second": {"image_prompt": "default"}},
    )
    sizes = {(('key', 'first'),): (400, 200)}

    await process_slide_and_fetch_assets(service, slide, image_target_sizes=sizes)

    requests = [call.args[0] for call in service.generate_image.await_args_list]
    assert [request.target_size for request in requests] == [(400, 200), None]


def test_provider_size_selection_and_square_fallback():
    assert _closest_aspect_ratio(None, GPT_IMAGE_SIZES) == "1024x1024"
    assert _closest_aspect_ratio((500, 300), GPT_IMAGE_SIZES) == "1536x1024"
    assert _closest_aspect_ratio((300, 500), DALLE3_IMAGE_SIZES) == "1024x1792"
    assert _closest_aspect_ratio((1600, 900), GEMINI_IMAGE_RATIOS) == "16:9"
    assert ImagePrompt(prompt="default").target_size is None


@pytest.mark.anyio
async def test_service_passes_target_size_to_provider_and_keeps_default_call():
    service = object.__new__(ImageGenerationService)
    service.output_directory = "/tmp"
    service.is_image_generation_disabled = False
    service.is_stock_provider_selected = lambda: False
    service.image_gen_func = AsyncMock(return_value="https://example.com/generated.png")

    await service.generate_image(ImagePrompt(prompt="wide", target_width=400, target_height=200))
    assert service.image_gen_func.await_args.kwargs == {"target_size": (400, 200)}

    await service.generate_image(ImagePrompt(prompt="default"))
    assert service.image_gen_func.await_args.kwargs == {}


@pytest.mark.anyio
async def test_openai_provider_uses_supported_size_and_square_fallback(tmp_path):
    service = ImageGenerationService(str(tmp_path))
    client = SimpleNamespace(images=SimpleNamespace(generate=AsyncMock(
        return_value=SimpleNamespace(data=[SimpleNamespace(
            b64_json=base64.b64encode(b"image").decode()
        )])
    )))
    with patch("services.image_generation_service.AsyncOpenAI", return_value=client):
        await service.generate_image_openai(
            "landscape", str(tmp_path), "dall-e-3", "standard", (1600, 900)
        )
        assert client.images.generate.await_args.kwargs["size"] == "1792x1024"

        await service.generate_image_openai(
            "default", str(tmp_path), "dall-e-3", "standard"
        )
        assert client.images.generate.await_args.kwargs["size"] == "1024x1024"
