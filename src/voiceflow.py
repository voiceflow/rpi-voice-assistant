import requests
from urllib.parse import urljoin

class MemoryStore:
  def __init__(self):
    self.store = None

  def get(self):
    return self.store

  def put(self, value):
    self.store = value

class Voiceflow:
  def __init__(self, apiKey, versionID, stateStore=MemoryStore):
    self.apiKey = apiKey
    self.stateStore = stateStore()
    self.url = "https://general-runtime.voiceflow.com"
    self.versionID = versionID

  def clear_state(self):
    self.stateStore.put(None)

  def interact(self, input):
    # Get state
    state = self.stateStore.get()

    # Call interactions
    body = {
      "state": state,
      "request": {
        "type": 'text',
        "payload": input,
      },
      "config": {
        "tts": "true",
      },
    }
    response = requests.post(urljoin(self.url, "/interact/"+versionID), json=body, headers={"Authorization":self.apiKey}).json()

    # Save state
    self.stateStore.put(response["state"])

    # Return response
    return response

  def init_state(self):
    # Get default state
    initialState = requests.get(urljoin(self.url, "/interact/"+self.versionID+"/state"), headers={"Authorization":self.apiKey}).json()

    # Begin initial session
    response = requests.post(urljoin(self.url, "/interact/"+self.versionID), json=initialState, headers={"Authorization":self.apiKey}).json()

    # Save state
    self.stateStore.put(response["state"])

    return response

  def state_uninitialized(self):
    return self.stateStore.store is None