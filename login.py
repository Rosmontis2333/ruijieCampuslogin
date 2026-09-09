#!/usr/bin/env python3
#"""Automate the captured campus-network CAS + ePortal login flow."""

#from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from playwright.async_api import APIRequestContext, Browser, Frame, Page, async_playwright


PORTAL_HOST = os.getenv("CAMPUS_PORTAL_HOST", "10.254.241.66")
TRIGGER_URL = os.getenv("CAMPUS_TRIGGER_URL", "http://123.123.123.123/")
USERNAME = os.getenv("CAMPUS_USER")
PASSWORD = os.getenv("CAMPUS_PASSWORD")
SERVICE = os.getenv("CAMPUS_SERVICE", "ctcc").lower()
LOGIN_TIMEOUT = float(os.getenv("CAMPUS_LOGIN_TIMEOUT", "60"))
SERVICE_WAIT_TIMEOUT = float(os.getenv("CAMPUS_SERVICE_WAIT_TIMEOUT", "30"))
HEADLESS_SETTING = os.getenv("CAMPUS_HEADLESS",1)
HEADLESS = (
    HEADLESS_SETTING == "1"
    if HEADLESS_SETTING is not None
    else sys.platform.startswith("linux") and not os.getenv("DISPLAY")
)
KEEP_OPEN = os.getenv("CAMPUS_KEEP_OPEN") == "1"
BROWSER_CHANNEL = os.getenv("CAMPUS_BROWSER_CHANNEL")
BROWSER_EXECUTABLE = os.getenv("CAMPUS_BROWSER_EXECUTABLE")
DISABLE_SANDBOX = os.getenv("CAMPUS_DISABLE_SANDBOX") == "1"

SERVICE_LABELS = {"ctcc": "电信", "cmcc": "移动", "unicom": "联通"}


async def find_login_frame(page: Page, timeout_seconds: float = 20) -> Frame | None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        for frame in page.frames:
            if await frame.locator("#normalLoginForm").count():
                return frame
        await asyncio.sleep(0.25)
    return None


async def visible_captcha(frame: Frame) -> bool:
    selectors = (
        "iframe[src*='captcha']",
        "iframe[src*='recaptcha']",
        ".geetest_box",
        ".geetest_panel",
        "input[name='captcha_code']",
    )
    for selector in selectors:
        elements = frame.locator(selector)
        for index in range(await elements.count()):
            try:
                if await elements.nth(index).is_visible():
                    return True
            except Exception:
                pass
    return False


async def accept_required_agreement(frame: Frame) -> bool:
    """Accept the login-page agreement only when the portal requires it."""
    component = frame.locator("useless-protocol-agreement")
    if not await component.count():
        return False

    checkbox = component.locator("input[type='checkbox']").first
    try:
        # The agreement component is populated asynchronously.
        await checkbox.wait_for(state="attached", timeout=5_000)
        if not await checkbox.is_checked():
            await checkbox.check(force=True)
        if not await checkbox.is_checked():
            raise RuntimeError("The user-agreement checkbox did not stay checked.")
        return True
    except Exception as checkbox_error:
        # Fallback for portal skins that replace or fully hide the native input.
        labels = component.locator(
            "label.protocol__track, label[nz-checkbox], .ant-checkbox-wrapper"
        )
        if await labels.count():
            await labels.first.click(force=True)
            await asyncio.sleep(0.2)
            if await checkbox.count() and not await checkbox.is_checked():
                raise RuntimeError("The user-agreement checkbox is still unchecked.")
            return True
        raise RuntimeError(
            "The user agreement is required but could not be selected."
        ) from checkbox_error


async def visible_login_error(frame: Frame) -> str | None:
    selectors = (
        ".normal-toast.tail-error",
        ".error-msg",
        ".ant-message-error",
        ".ant-notification-notice-message",
        ".ant-notification-notice-description",
    )
    for selector in selectors:
        elements = frame.locator(selector)
        for index in range(await elements.count()):
            element = elements.nth(index)
            try:
                if await element.is_visible():
                    text = " ".join((await element.inner_text()).split())
                    if text:
                        return text
            except Exception:
                pass
    return None


async def wait_for_portal_session(
    frame: Frame, session_future: asyncio.Future[str], timeout_seconds: float
) -> str:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        if session_future.done():
            return session_future.result()
        if await visible_captcha(frame):
            raise RuntimeError("The server requested a CAPTCHA; manual completion is required.")
        error = await visible_login_error(frame)
        if error:
            raise RuntimeError(f"CAS rejected the login: {error}")
        await asyncio.sleep(0.2)
    raise RuntimeError("CAS login did not advance to ePortal before the timeout.")


async def portal_post(
    request_context: APIRequestContext, path: str, payload: dict[str, Any]
) -> dict[str, Any]:
    response = await request_context.post(
        f"http://{PORTAL_HOST}{path}",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Origin": f"http://{PORTAL_HOST}",
            "Referer": f"http://{PORTAL_HOST}/portal/",
            "isPortal": "true",
        },
        timeout=20_000,
    )
    try:
        result = await response.json()
    except Exception as exc:
        raise RuntimeError(f"{path} returned non-JSON HTTP {response.status}.") from exc
    if not response.ok or result.get("code") != 200:
        raise RuntimeError(result.get("message") or f"{path} returned HTTP {response.status}.")
    return result


async def wait_for_service_options(
    request_context: APIRequestContext,
    session_id: str,
    desired_service: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_offered: set[str] = set()
    while asyncio.get_running_loop().time() < deadline:
        services = await portal_post(
            request_context,
            "/eportal/network/serviceSelection",
            {"sessionId": session_id},
        )
        last_offered = {
            item.get("value")
            for item in services.get("data", [])
            if isinstance(item, dict) and item.get("value")
        }
        if desired_service in last_offered:
            return services
        await asyncio.sleep(1)
    offered_text = ", ".join(sorted(last_offered)) or "none"
    raise RuntimeError(
        f"Service {desired_service} was not offered after waiting; offered: {offered_text}."
    )


async def login() -> int:
    if not USERNAME or not PASSWORD:
        print("Missing CAMPUS_USER or CAMPUS_PASSWORD.", file=sys.stderr)
        return 2
    if SERVICE not in SERVICE_LABELS:
        print("CAMPUS_SERVICE must be ctcc, cmcc, or unicom.", file=sys.stderr)
        return 2

    async with async_playwright() as playwright:
        launch_options: dict[str, Any] = {"headless": HEADLESS}
        if BROWSER_CHANNEL:
            launch_options["channel"] = BROWSER_CHANNEL
        if BROWSER_EXECUTABLE:
            launch_options["executable_path"] = BROWSER_EXECUTABLE
        if DISABLE_SANDBOX:
            print(
                "Warning: Chromium sandbox is disabled; use only inside an isolated host/container.",
                file=sys.stderr,
            )
            launch_options["args"] = ["--no-sandbox", "--disable-setuid-sandbox"]

        browser: Browser = await playwright.chromium.launch(**launch_options)
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(20_000)

        loop = asyncio.get_running_loop()
        portal_session: asyncio.Future[str] = loop.create_future()

        async def capture_session_after_response(request: Any) -> None:
            if "/eportal/workFlow/getCurrentNode" not in request.url:
                return
            try:
                body = request.post_data_json
                session_id = body.get("sessionId") if isinstance(body, dict) else None
                response = await request.response()
                response_body = await response.json() if response is not None else {}
                current_path = (response_body.get("data") or {}).get("currentNodePath")
                if (
                    session_id
                    and response is not None
                    and response.ok
                    and response_body.get("code") == 200
                    and current_path == "serviceSelection"
                    and not portal_session.done()
                ):
                    portal_session.set_result(session_id)
            except Exception:
                pass

        def schedule_session_capture(request: Any) -> None:
            if "/eportal/workFlow/getCurrentNode" in request.url:
                asyncio.create_task(capture_session_after_response(request))

        page.on("request", schedule_session_capture)

        try:
            print(f"Opening captive-portal trigger: {TRIGGER_URL}")
            await page.goto(TRIGGER_URL, wait_until="domcontentloaded", timeout=25_000)

            frame = await find_login_frame(page)
            if frame is None:
                if PORTAL_HOST not in page.url:
                    print("No captive redirect appeared; the device is probably already online.")
                    return 0
                success_text = page.get_by_text("您已成功连接网络！", exact=True)
                if await success_text.count() and await success_text.first.is_visible():
                    print("The campus portal already reports this device online.")
                    return 0
                raise RuntimeError("Portal opened, but the username/password form was not found.")

            await frame.locator("input[name='username']").fill(USERNAME)
            # The CAPTCHA decision is account-dependent and may only update after blur.
            await frame.locator("input[name='username']").press("Tab")
            await frame.locator("#normalLoginForm input[type='password']").fill(PASSWORD)
            await asyncio.sleep(0.5)
            if await accept_required_agreement(frame):
                print("Accepted the required user agreement.")
            if await visible_captcha(frame):
                raise RuntimeError(
                    "The server requested a CAPTCHA; manual completion is required."
                )
            await frame.locator("#submitBtn").click()
            print("CAS form submitted; waiting for the operator-selection stage.")

            session_id = await wait_for_portal_session(
                frame, portal_session, LOGIN_TIMEOUT
            )
            print("Operator-selection stage is ready; waiting for service options.")

            services = await wait_for_service_options(
                context.request,
                session_id,
                SERVICE,
                SERVICE_WAIT_TIMEOUT,
            )
            offered = {
                item.get("value")
                for item in services.get("data", [])
                if isinstance(item, dict)
            }
            if SERVICE not in offered:
                raise RuntimeError(f"Service {SERVICE} is not offered by this account.")

            result = await portal_post(
                context.request,
                "/eportal/network/serviceLogin",
                {"sessionId": session_id, "service": SERVICE},
            )
            login_data = result.get("data") or {}
            if login_data.get("authResult") != "success":
                raise RuntimeError(
                    login_data.get("authMessage") or "Network service login failed."
                )

            online = await portal_post(
                context.request,
                "/eportal/network/userOnline",
                {"sessionId": session_id},
            )
            if (online.get("data") or {}).get("online") is not True:
                raise RuntimeError("Portal did not report the device online.")

            print(f"Campus network connected through {SERVICE_LABELS[SERVICE]}.")
            return 0
        except Exception as exc:
            print(f"Login failed: {exc}", file=sys.stderr)
            return 1
        finally:
            if KEEP_OPEN:
                print("CAMPUS_KEEP_OPEN=1; leaving Chrome open. Press Ctrl-C to exit.")
                try:
                    await asyncio.Event().wait()
                except (KeyboardInterrupt, asyncio.CancelledError):
                    pass
            await browser.close()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(login()))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
