"""Unit tests for src.main._build_http_bodies (HTTP account-pool rotation)."""

from __future__ import annotations

from src.main import _build_http_bodies


BODY_TEMPLATE = '{"email":"{email}","password":"{password}"}'
ACCOUNTS = {
    "email_prefix": "user",
    "email_suffix": "@test.com",
    "start": 1,
    "end": 100,
    "password": "123456",
}


def test_builds_100_bodies():
    bodies = _build_http_bodies({"body": BODY_TEMPLATE, "accounts": ACCOUNTS})
    assert len(bodies) == 100


def test_first_and_last_emails():
    bodies = _build_http_bodies({"body": BODY_TEMPLATE, "accounts": ACCOUNTS})
    assert bodies[0] == '{"email":"user1@test.com","password":"123456"}'
    assert bodies[-1] == '{"email":"user100@test.com","password":"123456"}'


def test_password_substituted():
    bodies = _build_http_bodies({"body": BODY_TEMPLATE, "accounts": ACCOUNTS})
    assert all('"password":"123456"' in b for b in bodies)
    assert all("{password}" not in b for b in bodies)


def test_no_accounts_returns_empty():
    assert _build_http_bodies({"body": BODY_TEMPLATE}) == []


def test_no_email_placeholder_returns_empty():
    body = '{"email":"admin@cleanbank.com","password":"admin123"}'
    assert _build_http_bodies({"body": body, "accounts": ACCOUNTS}) == []


def test_custom_range():
    accounts = dict(ACCOUNTS, start=1, end=3)
    bodies = _build_http_bodies({"body": BODY_TEMPLATE, "accounts": accounts})
    assert bodies == [
        '{"email":"user1@test.com","password":"123456"}',
        '{"email":"user2@test.com","password":"123456"}',
        '{"email":"user3@test.com","password":"123456"}',
    ]
