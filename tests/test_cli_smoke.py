"""Smoke tests for the CLI — verify all commands respond to --help."""

from __future__ import annotations

from typer.testing import CliRunner

from antifraudies.cli import app

runner = CliRunner()


def test_app_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_enumerate_help():
    result = runner.invoke(app, ["enumerate", "--help"])
    assert result.exit_code == 0


def test_scrape_help():
    result = runner.invoke(app, ["scrape", "--help"])
    assert result.exit_code == 0


def test_report_help():
    result = runner.invoke(app, ["report", "--help"])
    assert result.exit_code == 0


def test_detect_help():
    result = runner.invoke(app, ["detect", "--help"])
    assert result.exit_code == 0


def test_findings_help():
    result = runner.invoke(app, ["findings", "--help"])
    assert result.exit_code == 0
