from dataclasses import dataclass, field

import requests

from .defaults import (
    API_BASE_URL,
)


@dataclass
class Variable:
    api_key: str
    user_id: str
    version_id: str
    headers: dict = field(init=False)

    def __post_init__(self):
        self.headers = {
            'Authorization': self.api_key,
            'versionID': self.version_id,
        }

    def update(self, variables: dict):
        response = requests.patch(
            f'{API_BASE_URL}/state/user/{self.user_id}/variables',
            json=variables,
            headers=self.headers,
        )
        return response.json()
