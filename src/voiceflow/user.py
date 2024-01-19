from dataclasses import dataclass, field
from requests import JSONDecodeError

import requests

from .defaults import (
    API_BASE_URL,
)


@dataclass
class UserState:
    api_key: str
    user_id: str
    version_id: str
    headers: dict = field(init=False)

    def __post_init__(self):
        self.headers = {
            'Authorization': self.api_key,
            'versionID': self.version_id,
        }

    def fetch(self) -> dict:
        response = requests.get(
            f'{API_BASE_URL}/state/user/{self.user_id}',
            headers=self.headers,
        )
        return response.json()

    @staticmethod
    def update() -> dict:
        return NotImplemented

    def delete(self) -> dict:
        delete_response = {}
        response = requests.delete(
            f'{API_BASE_URL}/state/user/{self.user_id}',
            headers=self.headers,
        )

        try:
            delete_response = response.json()
        except JSONDecodeError:
            pass

        return delete_response

    __call__ = fetch
