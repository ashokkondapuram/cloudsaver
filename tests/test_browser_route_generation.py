"""Browser exposure cannot expand or drift without an explicit contract decision."""
import pytest
from scripts import generate_browser_routes as generator


def test_generated_browser_admission_is_current():
    assert generator.TARGET.read_text()==generator.generate()


def test_new_api_route_is_not_implicitly_published(monkeypatch):
    monkeypatch.setattr(generator,'ROUTES',{**generator.ROUTES,('GET','/api/v1/unreviewed'):'scoped_read'})
    with pytest.raises(ValueError,match='Missing browser decisions'):
        generator.generate()


def test_internal_service_route_cannot_be_published(monkeypatch):
    altered=dict(generator.ROUTES)
    altered[('GET','/api/v1/me')]='service_identity'
    monkeypatch.setattr(generator,'ROUTES',altered)
    with pytest.raises(ValueError,match='Cannot publish'):
        generator.generate()
