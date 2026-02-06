from __future__ import annotations

from typing import Any, Callable, Sequence

InputProvider = Callable[[str], str]
OutputWriter = Callable[[str], None]


def render_header(
    title: str,
    *,
    subtitle: str | None = None,
    output: OutputWriter = print,
) -> None:
    normalized_title = title.strip() if isinstance(title, str) else ""
    if not normalized_title:
        normalized_title = "MMO"
    rule = "=" * max(16, len(normalized_title))
    output("")
    output(rule)
    output(normalized_title)
    output(rule)
    if isinstance(subtitle, str) and subtitle.strip():
        output(subtitle.strip())


def choose_from_list(
    title: str,
    options: Sequence[str],
    *,
    default_index: int = 0,
    input_provider: InputProvider = input,
    output: OutputWriter = print,
) -> int:
    normalized_options = [str(item) for item in options]
    if not normalized_options:
        raise ValueError("options must not be empty.")
    if not 0 <= default_index < len(normalized_options):
        raise ValueError("default_index is out of range.")

    while True:
        render_header(title, output=output)
        for index, label in enumerate(normalized_options, start=1):
            default_suffix = " (default)" if index - 1 == default_index else ""
            output(f"{index}. {label}{default_suffix}")
        response = input_provider(
            f"Choose 1-{len(normalized_options)} (Enter={default_index + 1}): "
        ).strip()
        if not response:
            return default_index
        if response.isdigit():
            index = int(response)
            if 1 <= index <= len(normalized_options):
                return index - 1
        output("Please enter a valid option number.")


def yes_no(
    prompt: str,
    *,
    default: bool = True,
    input_provider: InputProvider = input,
    output: OutputWriter = print,
) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        response = input_provider(f"{prompt} [{suffix}]: ").strip().casefold()
        if not response:
            return default
        if response in {"y", "yes"}:
            return True
        if response in {"n", "no"}:
            return False
        output("Please answer y or n.")


def multi_toggle(
    title: str,
    options: Sequence[dict[str, Any]],
    *,
    input_provider: InputProvider = input,
    output: OutputWriter = print,
) -> dict[str, bool]:
    normalized: list[dict[str, Any]] = []
    for item in options:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        label = item.get("label")
        if not isinstance(key, str) or not key.strip():
            continue
        if not isinstance(label, str) or not label.strip():
            continue
        normalized.append(
            {
                "key": key.strip(),
                "label": label.strip(),
                "enabled": item.get("enabled") is True,
                "locked": item.get("locked") is True,
            }
        )
    if not normalized:
        return {}

    states = {
        str(item["key"]): bool(item.get("enabled"))
        for item in normalized
    }
    labels = {
        str(item["key"]): str(item.get("label"))
        for item in normalized
    }
    locked = {
        str(item["key"]): bool(item.get("locked"))
        for item in normalized
    }
    ordered_keys = [str(item["key"]) for item in normalized]

    while True:
        render_header(title, output=output)
        for index, key in enumerate(ordered_keys, start=1):
            marker = "x" if states[key] else " "
            if locked[key]:
                locked_suffix = " (always on)" if states[key] else " (locked)"
            else:
                locked_suffix = ""
            output(f"{index}. [{marker}] {labels[key]}{locked_suffix}")

        response = input_provider(
            "Toggle numbers (comma-separated), Enter to continue: "
        ).strip()
        if not response:
            return {key: states[key] for key in ordered_keys}

        raw_tokens = [token.strip() for token in response.split(",") if token.strip()]
        if not raw_tokens:
            return {key: states[key] for key in ordered_keys}

        parsed: set[int] = set()
        valid = True
        for token in raw_tokens:
            if not token.isdigit():
                valid = False
                break
            index = int(token)
            if not 1 <= index <= len(ordered_keys):
                valid = False
                break
            parsed.add(index - 1)
        if not valid:
            output("Please enter valid option numbers.")
            continue

        for index in sorted(parsed):
            key = ordered_keys[index]
            if locked[key]:
                continue
            states[key] = not states[key]
