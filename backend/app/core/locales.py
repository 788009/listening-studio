from __future__ import annotations

from typing import Annotated

from fastapi import Query, Request
from pydantic import BeforeValidator


DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = ("en", "zh-CN")

_ZH_ERROR_MESSAGES = {
    "forbidden": "没有权限执行此操作",
    "not_found": "未找到资源",
    "profile_incomplete": "请先完成个人资料设置",
    "conflict": "资源当前状态不允许此操作",
    "validation_error": "请求参数无效",
    "job_failed": "任务执行失败",
    "internal_error": "服务器内部错误",
    "http_401": "需要登录",
}


def match_supported_locale(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().replace("_", "-")
    if not candidate:
        return None
    lowered = candidate.casefold()
    for locale in SUPPORTED_LOCALES:
        if lowered == locale.casefold():
            return locale
    language = lowered.split("-", maxsplit=1)[0]
    if language == "en":
        return "en"
    if language == "zh":
        return "zh-CN"
    return None


def normalize_supported_locale(value: object) -> object:
    matched = match_supported_locale(value)
    if matched is None:
        raise ValueError("Unsupported locale")
    return matched


SupportedLocale = Annotated[str, BeforeValidator(normalize_supported_locale)]


def parse_accept_language(value: str | None) -> str | None:
    if not value:
        return None
    candidates: list[tuple[float, int, str]] = []
    for position, part in enumerate(value.split(",")):
        language, *parameters = part.strip().split(";")
        quality = 1.0
        for parameter in parameters:
            name, separator, raw_value = parameter.strip().partition("=")
            if name.casefold() != "q" or not separator:
                continue
            try:
                quality = float(raw_value)
            except ValueError:
                quality = 0.0
        matched = match_supported_locale(language)
        if matched is not None and quality > 0:
            candidates.append((quality, -position, matched))
    if not candidates:
        return None
    return max(candidates)[2]


def resolve_locale(
    *,
    explicit: object = None,
    user_locale: object = None,
    accept_language: str | None = None,
) -> str:
    if explicit is not None:
        matched = match_supported_locale(explicit)
        if matched is None:
            raise ValueError("Unsupported locale")
        return matched
    return (
        match_supported_locale(user_locale)
        or parse_accept_language(accept_language)
        or DEFAULT_LOCALE
    )


async def get_request_locale(
    request: Request,
    language: SupportedLocale | None = Query(default=None),
) -> str:
    principal = getattr(request.state, "principal", None)
    user = getattr(principal, "user", None)
    return resolve_locale(
        explicit=language,
        user_locale=getattr(user, "locale", None),
        accept_language=request.headers.get("Accept-Language"),
    )


def request_locale(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    user = getattr(principal, "user", None)
    explicit = request.query_params.get("language")
    try:
        return resolve_locale(
            explicit=explicit,
            user_locale=getattr(user, "locale", None),
            accept_language=request.headers.get("Accept-Language"),
        )
    except ValueError:
        return (
            match_supported_locale(getattr(user, "locale", None))
            or parse_accept_language(request.headers.get("Accept-Language"))
            or DEFAULT_LOCALE
        )


def localize_error_message(
    locale: str,
    code: str,
    english_message: str,
) -> str:
    if locale == "zh-CN":
        return _ZH_ERROR_MESSAGES.get(code, english_message)
    return english_message
