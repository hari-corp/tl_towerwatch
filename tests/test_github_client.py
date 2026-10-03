import respx
from httpx import Response

from tl_towerwatch.github.client import GitHubClient


@respx.mock
def test_get_authenticated_user():
    respx.get("https://api.github.com/user").mock(
        return_value=Response(
            200,
            json={"login": "dimh", "avatar_url": "https://x/y.png", "name": "D"},
            headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Reset": "1700000000"},
        )
    )
    c = GitHubClient(token="x")
    u = c.get_authenticated_user()
    assert u.login == "dimh"
    assert c.last_rate_limit().remaining == 4999