"""Exact-origin identity egress decisions, including rebinding/private address rejection."""
import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('identity_egress',Path(__file__).parents[1]/'platform/egress/proxy.py')
proxy=importlib.util.module_from_spec(spec);spec.loader.exec_module(proxy)

@pytest.mark.parametrize('target',['evil.example:443','login.microsoftonline.com:80','login.microsoftonline.com.evil.example:443','127.0.0.1:443','user@login.microsoftonline.com:443'])
def test_egress_refuses_unapproved_authorities(target):
    with pytest.raises(ValueError):proxy.destination(target,proxy.approved_hosts('login.microsoftonline.com'))

@pytest.mark.parametrize('address',['127.0.0.1','169.254.169.254','10.0.0.1','::1','fd00::1'])
def test_egress_rejects_dns_rebinding_to_private_addresses(monkeypatch,address):
    monkeypatch.setattr(proxy.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',(address,443))])
    with pytest.raises(ValueError):proxy.destination('login.microsoftonline.com:443',{'login.microsoftonline.com'})
