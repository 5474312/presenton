from __future__ import annotations

import colorsys
import re
from collections import Counter
from typing import Any

from models.theme_data import ThemeData

HEX_COLOR = re.compile(r"^#?[0-9a-fA-F]{6}$")
DEFAULT_COLORS = ThemeData(
    primary="#4a6ebd",
    background="#ffffff",
    card="#e8e8e8",
    stroke="#d1d1d1",
    primary_text="#dedede",
    background_text="#060301",
    graph_0="#09256d",
    graph_1="#1c3c86",
    graph_2="#3153a0",
    graph_3="#476bba",
    graph_4="#5d83d4",
    graph_5="#749cef",
    graph_6="#8cb6ff",
    graph_7="#a5d0ff",
    graph_8="#bbe7ff",
    graph_9="#c8f5ff",
)


def _normalize_hex(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    color = value.strip()
    if not HEX_COLOR.fullmatch(color):
        return None
    return (color if color.startswith("#") else f"#{color}").lower()


def _channels(color: str) -> tuple[int, int, int]:
    value = int(color[1:], 16)
    return (value >> 16 & 255, value >> 8 & 255, value & 255)


def _relative_luminance(color: str) -> float:
    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (_channels(color))
    return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue)


def _contrast_ratio(first: str, second: str) -> float:
    a = _relative_luminance(first)
    b = _relative_luminance(second)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _saturation(color: str) -> float:
    red, green, blue = (channel / 255 for channel in _channels(color))
    return colorsys.rgb_to_hls(red, green, blue)[2]


def _mix(first: str, second: str, second_weight: float) -> str:
    channels = [
        round(a * (1 - second_weight) + b * second_weight)
        for a, b in zip(_channels(first), _channels(second), strict=True)
    ]
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def _record_color(
    color: str,
    path: str,
    roles: dict[str, Counter[str]],
) -> None:
    roles["total"][color] += 1
    if any(
        marker in path
        for marker in ("font", "text_color", "title_color", "legend_color")
    ):
        roles["text"][color] += 1
    elif any(marker in path for marker in ("stroke", "axis_color", "grid_color")):
        roles["stroke"][color] += 1
    elif any(marker in path for marker in ("chart", "infographic", "colors")):
        roles["graph"][color] += 1
    else:
        roles["fill"][color] += 1


def _collect_style(
    value: Any,
    path: tuple[str, ...],
    roles: dict[str, Counter[str]],
    fonts: Counter[str],
) -> None:
    if isinstance(value, list):
        for item in value:
            color = _normalize_hex(item)
            if color:
                _record_color(color, ".".join(path), roles)
            else:
                _collect_style(item, path, roles, fonts)
        return
    if not isinstance(value, dict):
        return

    for key, entry in value.items():
        normalized_key = str(key).lower()
        next_path = (*path, normalized_key)
        color = _normalize_hex(entry)
        if color:
            _record_color(color, ".".join(next_path), roles)
        elif normalized_key in {"family", "font_family"}:
            if isinstance(entry, str) and entry.strip():
                fonts[entry.strip()] += 1
        _collect_style(entry, next_path, roles, fonts)


def _ranked(
    colors: list[str],
    score,
) -> list[str]:
    insertion_order = {color: index for index, color in enumerate(colors)}
    return sorted(colors, key=lambda color: (-score(color), insertion_order[color]))


def derive_template_theme(
    layouts: Any,
    available_fonts: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Derive reference-compatible semantic roles from stored template JSON."""

    roles = {
        "fill": Counter(),
        "graph": Counter(),
        "stroke": Counter(),
        "text": Counter(),
        "total": Counter(),
    }
    fonts: Counter[str] = Counter()
    _collect_style(layouts, ("layouts",), roles, fonts)
    colors = list(roles["total"])
    if not colors:
        return None

    by_fill = _ranked(
        colors,
        lambda color: roles["fill"][color] * 4 + roles["total"][color],
    )
    background = by_fill[0]
    text_candidates = _ranked(
        colors,
        lambda color: roles["text"][color] * 6 + roles["total"][color],
    )
    background_text = next(
        (
            color
            for color in text_candidates
            if _contrast_ratio(color, background) >= 4.5
        ),
        "#ffffff" if _relative_luminance(background) < 0.45 else "#111111",
    )
    accent_candidates = [
        color
        for color in _ranked(
            colors,
            lambda color: roles["graph"][color] * 8
            + roles["fill"][color] * 2
            + roles["stroke"][color]
            + _saturation(color) * 6,
        )
        if color not in {background, background_text} and _saturation(color) > 0.08
    ]
    primary = accent_candidates[0] if accent_candidates else DEFAULT_COLORS.primary
    card = next(
        (color for color in by_fill if color not in {background, primary}),
        _mix(background, primary, 0.12),
    )
    stroke = next(
        (
            color
            for color in _ranked(
                colors,
                lambda candidate: roles["stroke"][candidate] * 6
                + roles["total"][candidate],
            )
            if color not in {background, background_text}
        ),
        _mix(background, background_text, 0.18),
    )
    graph_seeds = list(dict.fromkeys([*accent_candidates, primary]))
    graph_colors = [
        graph_seeds[index]
        if index < len(graph_seeds)
        else _mix(
            primary,
            background if index % 2 == 0 else background_text,
            0.08 * (index + 1),
        )
        for index in range(10)
    ]
    primary_text = (
        "#ffffff"
        if _contrast_ratio("#ffffff", primary) >= _contrast_ratio("#111111", primary)
        else "#111111"
    )
    colors_payload = ThemeData(
        primary=primary,
        background=background,
        card=card,
        stroke=stroke,
        primary_text=primary_text,
        background_text=background_text,
        **{f"graph_{index}": color for index, color in enumerate(graph_colors)},
    )

    font_payload: dict[str, Any] = {}
    dominant_font = fonts.most_common(1)[0][0] if fonts else None
    font_url = (available_fonts or {}).get(dominant_font or "")
    if dominant_font and isinstance(font_url, str) and font_url.strip():
        font_payload = {
            "textFont": {"name": dominant_font, "url": font_url.strip()}
        }

    return {
        "colors": colors_payload.model_dump(mode="json"),
        "fonts": font_payload,
    }
