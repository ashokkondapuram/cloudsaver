"""Dedicated analysis-service process (per-resource rule evaluation and recommendations)."""
from services.common import service
from app.analysis_api import register


def create_app(settings=None, identity_validator=None):
    app, _settings, _tenant = service('analysis-service', settings, identity_validator)
    register(app)
    return app
