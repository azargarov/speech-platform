"""Check rendered Compose, including environment substitutions."""

import json
import sys

config = json.load(sys.stdin)
assert config["networks"]["speech"]["internal"]
for name, service in config["services"].items():
    assert service["read_only"] and service["user"] == "65532:65532"
    assert not service.get("privileged", False)
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert int(service["mem_limit"]) > 0 and float(service["cpus"]) > 0
    assert set(service["networks"]) == {"speech"}
    if name != "gateway":
        assert not service.get("ports")
        assert not service.get("depends_on")
